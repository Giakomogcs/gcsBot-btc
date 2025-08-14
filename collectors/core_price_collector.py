import os
import sys
import datetime
from datetime import timedelta
import pandas as pd
import time
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from typing import Optional
from pathlib import Path
from tqdm import tqdm

# Adiciona a raiz do projeto ao path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.logger import logger
from jules_bot.database.models import PriceHistory
from sqlalchemy import desc

class CorePriceCollector:
    def __init__(self, bucket_name: Optional[str] = None):
        logger.info("Initializing CorePriceCollector...")
        db_config = config_manager.get_db_config('POSTGRES')
        
        self.db_manager = PostgresManager(config=db_config)
        self.binance_client = None  # Initialize as None. Will be connected on demand.
        self.symbol = config_manager.get('APP', 'symbol')
        self.interval = config_manager.get('DATA', 'interval', fallback='1m')
        self.source = config_manager.get('DATA', 'source', fallback='binance')
        self.measurement = "price_history"

    def connect_binance_client(self) -> bool:
        """
        Initializes the Binance client. Returns True on success, False on failure.
        """
        if self.binance_client:
            logger.info("Binance client is already connected.")
            return True

        if config_manager.getboolean('APP', 'force_offline_mode', fallback=False):
            logger.warning("Force offline mode is enabled. Binance client will not be initialized.")
            return False
        try:
            use_testnet = config_manager.getboolean('APP', 'use_testnet', fallback=False)
            mode = 'TESTNET' if use_testnet else 'LIVE'
            logger.info(f"Attempting to initialize Binance client in {mode} mode...")

            binance_config = config_manager.get_section(f'BINANCE_{mode}')
            api_key = binance_config.get('api_key')
            api_secret = binance_config.get('api_secret')

            if not api_key or not api_secret:
                logger.error(f"API Key/Secret for {mode} mode not found in config.ini.")
                return False

            client = Client(api_key, api_secret, tld='com', testnet=use_testnet)
            client.ping()
            logger.info(f"Binance client initialized successfully in {mode} mode.")
            self.binance_client = client
            return True
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"A Binance API error occurred during client initialization: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"An unexpected error occurred during Binance client initialization: {e}", exc_info=True)
            return False

    def _write_dataframe_to_postgres(self, df: pd.DataFrame):
        """
        Writes a DataFrame to PostgreSQL in chunks with a progress bar.
        """
        if df.empty:
            logger.info("DataFrame is empty, nothing to write.")
            return

        logger.info(f"Preparing to write {len(df)} rows to PostgreSQL table '{self.measurement}'...")
        df['symbol'] = self.symbol

        chunk_size = 50_000
        with self.db_manager.get_db() as db:
            try:
                with tqdm(total=len(df), desc="Writing data to PostgreSQL", unit="rows") as pbar:
                    for i in range(0, len(df), chunk_size):
                        chunk = df.iloc[i:i + chunk_size]
                        chunk.to_sql(self.measurement, self.db_manager.engine, if_exists='append', index=True, chunksize=1000)
                        pbar.update(len(chunk))
                logger.info(f"\nSuccessfully wrote {len(df)} new candles to '{self.measurement}'.")
            except Exception as e:
                logger.error(f"\nError writing data to PostgreSQL: {e}", exc_info=True)

    def _query_last_timestamp(self) -> Optional[pd.Timestamp]:
        """
        Queries the last timestamp for the specific symbol.
        """
        logger.info(f"Querying last timestamp for {self.symbol} in table '{self.measurement}'...")
        with self.db_manager.get_db() as db:
            try:
                last_record = db.query(PriceHistory).filter(PriceHistory.symbol == self.symbol).order_by(desc(PriceHistory.timestamp)).first()
                if not last_record:
                    logger.info("No existing data found for this series in the table.")
                    return None
                last_timestamp = pd.to_datetime(last_record.timestamp).tz_localize('UTC')
                logger.info(f"Last timestamp found in DB: {last_timestamp}")
                return last_timestamp
            except Exception as e:
                logger.error(f"Error querying last timestamp from PostgreSQL: {e}", exc_info=True)
                return None

    def _get_historical_klines(self, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
        """
        Fetches historical OHLCV data from Binance, handling pagination and API errors with retries.
        """
        logger.info(f"Fetching OHLCV data for {self.symbol} from {start_dt} to {end_dt}...")
        if not self.binance_client:
            logger.warning("Binance client not initialized. Cannot fetch historical klines.")
            return pd.DataFrame()

        all_klines = []
        current_start_dt = start_dt
        end_ms = int(end_dt.timestamp() * 1000)
        
        retries = 5
        backoff_factor = 0.5

        with tqdm(total=(end_dt - start_dt).total_seconds() / 60, desc="Downloading from Binance", unit=" candles") as pbar:
            while current_start_dt < end_dt:
                klines_fetched_in_batch = False
                for i in range(retries):
                    try:
                        current_start_ms = int(current_start_dt.timestamp() * 1000)
                        klines = self.binance_client.get_historical_klines(
                            self.symbol, Client.KLINE_INTERVAL_1MINUTE, start_str=current_start_ms, end_str=end_ms, limit=1000
                        )
                        
                        if not klines:
                            # This can happen on testnet if there's a gap in trading.
                            # Instead of stopping, we log it and advance our start time to skip the gap.
                            logger.warning(f"No klines returned from Binance for start time {current_start_dt}. Advancing to next chunk.")
                            current_start_dt += pd.Timedelta(minutes=1000) # Advance by the API limit
                            klines_fetched_in_batch = True
                            break # Exit retry loop and continue pagination

                        all_klines.extend(klines)
                        pbar.update(len(klines))
                        
                        last_kline_ts_ms = klines[-1][0]
                        current_start_dt = pd.to_datetime(last_kline_ts_ms, unit='ms', utc=True) + pd.Timedelta(minutes=1)
                        
                        klines_fetched_in_batch = True
                        time.sleep(0.1) # Be respectful to the API
                        break # Success, exit retry loop

                    except (BinanceAPIException, BinanceRequestException) as e:
                        if i < retries - 1:
                            sleep_time = backoff_factor * (2 ** i)
                            logger.warning(f"API Error fetching klines: {e}. Retrying in {sleep_time} seconds...")
                            time.sleep(sleep_time)
                        else:
                            logger.error(f"API Error after {retries} retries for start time {current_start_dt}. Skipping this chunk.")
                            # Advance the start time to skip the problematic chunk and continue downloading
                            current_start_dt += pd.Timedelta(minutes=1000)
                            klines_fetched_in_batch = True # Mark as 'handled' to continue the main loop
                            break # Exit retry loop
                
                if not klines_fetched_in_batch:
                    # This should now be unreachable, but as a safeguard:
                    logger.error("A downloader logic error occurred. Aborting.")
                    break

        if not all_klines:
            return pd.DataFrame()

        # Format the dataframe
        df = pd.DataFrame(all_klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'nt', 'tbbav', 'tbqav', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        
        if df.index.has_duplicates:
            num_duplicates = df.index.duplicated().sum()
            logger.warning(f"Received {num_duplicates} duplicate timestamps from Binance. Removing them.")
            df = df[~df.index.duplicated(keep='first')]

        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df = df.sort_index() # Ensure data is sorted before slicing
        df = df.loc[start_dt:end_dt]
        
        unique_candles = len(df)
        logger.info(f"\nFetched a total of {unique_candles} unique candles from Binance.")
        return df

    def run(self):
        """
        This method is for live data collection, continuously updating the database.
        """
        logger.info(f"--- Starting live price collection for table '{self.measurement}' ---")
        if not self.connect_binance_client():
            logger.error("Could not connect to Binance. Live price collection cannot start.")
            return
        
        while True:
            last_timestamp = self._query_last_timestamp()
            if last_timestamp:
                start_date = last_timestamp + pd.Timedelta(minutes=1)
            else:
                start_date_str = config_manager.get('DATA_PIPELINE', 'start_date_ingestion', fallback='2023-01-01')
                start_date = pd.to_datetime(start_date_str, utc=True)
                logger.info(f"No existing data. Starting collection from {start_date_str}.")

            end_date = datetime.datetime.now(datetime.timezone.utc)

            if start_date >= end_date:
                logger.info("Price data is already up to date. No new data to fetch. Sleeping for 1 minute.")
            else:
                df_new_prices = self._get_historical_klines(start_date, end_date)
                if not df_new_prices.empty:
                    self._write_dataframe_to_postgres(df_new_prices)
            
            time.sleep(60)


def prepare_backtest_data(days: int, force_reload: bool = False):
    """
    Acts as a smart guardian for the historical database. It ensures the database
    is up-to-date and contains at least the required number of days of data.
    This function is non-destructive, only downloading missing data.
    """
    logger.info("--- Starting Intelligent Data Preparation ---")
    
    collector = CorePriceCollector()
    online_mode = collector.connect_binance_client()

    if force_reload:
        logger.warning("`--force-reload` flag detected. Deleting all existing price data for a full refresh.")
        collector.db_manager.clear_all_tables()

    if not online_mode:
        logger.warning("Binance is offline. Using existing local data only.")
        logger.info("--- Data Preparation Finished (Offline Mode) ---")
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    
    # --- Phase 1: Historical Backfill (Backward-fill) ---
    # Ensures the database has at least the required number of days of history.
    required_start_date = now - timedelta(days=days)
    first_ts_in_db = collector.db_manager.query_first_timestamp(collector.measurement)

    if first_ts_in_db is None:
        # Database is empty. Perform an initial download for the entire required period.
        logger.info(f"Database is empty. Performing initial download for the last {days} days...")
        df_historical = collector._get_historical_klines(required_start_date, now)
        if not df_historical.empty:
            collector._write_dataframe_to_postgres(df_historical)
    elif first_ts_in_db > required_start_date:
        # We have data, but not enough history. Download only the missing older chunk.
        backward_fill_end_date = first_ts_in_db - timedelta(minutes=1)
        logger.info(f"Insufficient history. Back-filling older data from {required_start_date} to {backward_fill_end_date}.")
        df_historical = collector._get_historical_klines(required_start_date, backward_fill_end_date)
        if not df_historical.empty:
            collector._write_dataframe_to_postgres(df_historical)
    else:
        # The oldest record is older than or at the required start date.
        logger.info(f"Sufficient historical data found (oldest record at {first_ts_in_db}). No back-fill needed.")

    # --- Phase 2: Incremental Update (Forward-fill) ---
    # Ensures the data is up-to-date from the last record to now.
    last_ts_in_db = collector._query_last_timestamp()

    if last_ts_in_db:
        forward_fill_start_date = last_ts_in_db + timedelta(minutes=1)
        if forward_fill_start_date < now:
            logger.info(f"Synchronizing new data from {forward_fill_start_date} up to present.")
            df_new = collector._get_historical_klines(forward_fill_start_date, now)
            if not df_new.empty:
                collector._write_dataframe_to_postgres(df_new)
        else:
            logger.info("Data is already up-to-date. No forward-fill needed.")
    else:
        # This case should ideally not be hit if the backfill logic is correct, but is here as a safeguard.
        logger.warning("No data found after historical backfill. Forward-fill will not run.")

    logger.info("--- Intelligent Data Preparation Finished ---")


if __name__ == '__main__':
    # The main entry point is now intended for live collection.
    # Backtest data preparation is handled by its own script.
    logger.info("Running CorePriceCollector in live collection mode...")
    collector = CorePriceCollector()
    collector.run()
