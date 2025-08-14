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
        Fetches historical OHLCV data from Binance using the robust klines generator.
        """
        logger.info(f"Fetching OHLCV data for {self.symbol} from {start_dt} to {end_dt}...")
        if not self.binance_client:
            logger.warning("Binance client not initialized. Cannot fetch historical klines.")
            return pd.DataFrame()

        # Convert datetimes to the string format required by the generator
        start_str = start_dt.strftime("%d %b, %Y %H:%M:%S")
        end_str = end_dt.strftime("%d %b, %Y %H:%M:%S")

        klines_generator = self.binance_client.get_historical_klines_generator(
            self.symbol, Client.KLINE_INTERVAL_1MINUTE, start_str, end_str=end_str
        )

        # Use tqdm to show progress as we consume the generator
        total_minutes = (end_dt - start_dt).total_seconds() / 60
        all_klines = []
        with tqdm(total=total_minutes, desc="Downloading from Binance", unit=" candles") as pbar:
            for kline in klines_generator:
                all_klines.append(kline)
                pbar.update(1)

        if not all_klines:
            logger.warning("No klines returned from Binance generator.")
            return pd.DataFrame()

        # Format the dataframe
        df = pd.DataFrame(all_klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'nt', 'tbbav', 'tbqav', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)

        # Remove duplicates and set index
        df.drop_duplicates(subset=['timestamp'], inplace=True)
        df.set_index('timestamp', inplace=True)

        # Select and cast columns
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

        # The generator can sometimes fetch data slightly outside the requested range, so we filter it.
        df = df.loc[start_dt:end_dt]

        logger.info(f"\nFetched a total of {len(df)} unique candles from Binance.")
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
    contains AT LEAST the required number of days of data, and that this data is
    up-to-date by downloading only missing data from Binance.
    """
    logger.info("--- Starting Intelligent Data Preparation ---")
    
    collector = CorePriceCollector()
    online_mode = collector.connect_binance_client()

    if force_reload:
        logger.warning("`--force-reload` flag detected. Deleting all existing price data for a full refresh.")
        collector.db_manager.clear_price_history()
        collector.db_manager.clear_backtest_trades()

    # --- New Logic to ensure sufficient historical data ---
    end_date = datetime.datetime.now(datetime.timezone.utc)
    required_start_date = end_date - timedelta(days=days)
    
    first_ts_in_db = collector.db_manager.query_first_timestamp(collector.measurement)

    if first_ts_in_db is None or first_ts_in_db > required_start_date:
        download_start_date = required_start_date
        download_end_date = first_ts_in_db if first_ts_in_db is not None else end_date

        logger.info(f"Database is missing older data. Downloading from {download_start_date} to {download_end_date}.")
        if not online_mode:
            logger.error(f"CRITICAL: Database needs older data, but Binance is offline. Cannot proceed.")
            return

        df_to_write = collector._get_historical_klines(download_start_date, download_end_date)
        if not df_to_write.empty:
            collector._write_dataframe_to_postgres(df_to_write)
        else:
            logger.warning("Failed to download any historical data.")

    # --- Incremental update logic (runs after ensuring history is sufficient) ---
    if not online_mode:
        logger.warning("Binance is offline. Cannot perform incremental update. Using existing data.")
        logger.info("--- Data Preparation Finished (Offline Mode) ---")
        return

    last_ts_in_db = collector._query_last_timestamp()

    if last_ts_in_db:
        incremental_start_date = last_ts_in_db + timedelta(minutes=1)

        if incremental_start_date < end_date:
            logger.info(f"History is sufficient. Synchronizing new data from {incremental_start_date} to {end_date}.")
            df_to_write = collector._get_historical_klines(incremental_start_date, end_date)
            if not df_to_write.empty:
                collector._write_dataframe_to_postgres(df_to_write)
        else:
            logger.info(f"Data is already up-to-date. Last record at {last_ts_in_db}. No action needed.")
    
    logger.info("--- Intelligent Data Preparation Finished ---")


if __name__ == '__main__':
    # The main entry point is now intended for live collection.
    # Backtest data preparation is handled by its own script.
    logger.info("Running CorePriceCollector in live collection mode...")
    collector = CorePriceCollector()
    collector.run()
