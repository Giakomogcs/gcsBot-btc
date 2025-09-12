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
        self.db_manager = PostgresManager()
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

    def _query_last_timestamp(self, symbol: str) -> Optional[pd.Timestamp]:
        """
        Queries the last timestamp for the specific symbol.
        """
        logger.info(f"Querying last timestamp for {symbol} in table '{self.measurement}'...")
        with self.db_manager.get_db() as db:
            try:
                last_record = db.query(PriceHistory).filter(PriceHistory.symbol == symbol).order_by(desc(PriceHistory.timestamp)).first()
                if not last_record:
                    logger.info("No existing data found for this series in the table.")
                    return None
                last_timestamp = pd.to_datetime(last_record.timestamp).tz_localize('UTC')
                logger.info(f"Last timestamp found in DB: {last_timestamp}")
                return last_timestamp
            except Exception as e:
                logger.error(f"Error querying last timestamp from PostgreSQL: {e}", exc_info=True)
                return None

    def _get_historical_klines(self, start_dt: datetime.datetime, end_dt: datetime.datetime, client: Optional[Client] = None) -> pd.DataFrame:
        """
        Fetches historical OHLCV data from Binance, handling pagination automatically.
        """
        logger.info(f"Fetching OHLCV data for {self.symbol} from {start_dt} to {end_dt}...")
        
        # If no specific client is provided, use the instance's default client.
        active_client = client if client else self.binance_client

        if not active_client:
            logger.warning("Binance client not initialized. Cannot fetch historical klines.")
            return pd.DataFrame()

        all_klines = []
        current_start_dt = start_dt
        end_ms = int(end_dt.timestamp() * 1000)

        with tqdm(total=(end_dt - start_dt).total_seconds() / 60, desc="Downloading from Binance", unit=" candles") as pbar:
            while True:
                current_start_ms = int(current_start_dt.timestamp() * 1000)
                try:
                    klines = active_client.get_historical_klines(
                        self.symbol, Client.KLINE_INTERVAL_1MINUTE, start_str=current_start_ms, end_str=end_ms, limit=1000
                    )
                    if not klines:
                        break
                    all_klines.extend(klines)
                    pbar.update(len(klines))
                    last_kline_ts_ms = klines[-1][0]
                    next_start_dt = pd.to_datetime(last_kline_ts_ms, unit='ms', utc=True) + pd.Timedelta(minutes=1)
                    if next_start_dt > end_dt:
                        break
                    current_start_dt = next_start_dt
                    time.sleep(0.1) # Small delay to be respectful to the API
                except (BinanceAPIException, BinanceRequestException) as e:
                    logger.error(f"API Error fetching klines: {e}", exc_info=True)
                    break
        
        if not all_klines:
            return pd.DataFrame()

        # Format the dataframe
        df = pd.DataFrame(all_klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'nt', 'tbbav', 'tbqav', 'ignore'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        df = df.loc[start_dt:end_dt]
        logger.info(f"\nFetched a total of {len(df)} candles from Binance.")
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
            last_timestamp = self._query_last_timestamp(self.symbol)
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


def prepare_backtest_data(days: int):
    """
    Acts as a smart guardian for the historical database. It ensures the database
    contains the required range of data, downloading only missing data from Binance
    without ever deleting existing records.
    This function will always use the LIVE Binance API for data to ensure quality,
    regardless of the testnet setting in the config.
    """
    logger.info("--- Starting Intelligent and Safe Data Preparation ---")
    
    collector = CorePriceCollector()
    symbol = collector.symbol
    
    # For reliable backtesting, always use the live Binance client for historical data.
    # This client does not require API keys for public data endpoints.
    try:
        logger.info("Initializing temporary live Binance client for accurate historical data...")
        # Aumentar o timeout para 30 segundos
        requests_params = {"timeout": 30}
        historical_client = Client(api_key="", api_secret="", requests_params=requests_params)
        historical_client.ping()
        online_mode = True
        logger.info("Live Binance client connected successfully.")
    except (BinanceAPIException, BinanceRequestException) as e:
        logger.error(f"Could not connect to live Binance API for historical data: {e}", exc_info=True)
        online_mode = False
    except Exception as e:
        logger.error(f"An unexpected error occurred while connecting to live Binance API: {e}", exc_info=True)
        online_mode = False

    if not online_mode:
        logger.warning("Could not connect to live API. Data preparation will rely solely on existing database content.")

    # 1. Define the required data range
    required_end_date = datetime.datetime.now(datetime.timezone.utc)
    required_start_date = required_end_date - timedelta(days=days)
    logger.info(f"Required data range for backtest: {required_start_date} to {required_end_date}")

    # 2. Check the current state of the database
    db_first_ts = collector.db_manager.query_first_timestamp(symbol)
    db_last_ts = collector._query_last_timestamp(symbol)

    # 3. Download historical data if needed (older than what we have)
    if online_mode:
        if db_first_ts is None or db_first_ts > required_start_date:
            download_start = required_start_date
            download_end = (db_first_ts - timedelta(minutes=1)) if db_first_ts else required_end_date
            
            logger.info(f"Downloading historical data from {download_start} to {download_end} using LIVE client.")
            df_hist = collector._get_historical_klines(download_start, download_end, client=historical_client)
            if not df_hist.empty:
                collector._write_dataframe_to_postgres(df_hist)
        else:
            logger.info("Sufficient historical data already exists. No historical download needed.")

        # 4. Download recent data if needed (newer than what we have)
        db_last_ts = collector._query_last_timestamp(symbol) # Re-query in case of historical download
        if db_last_ts is None:
             db_last_ts = required_start_date - timedelta(minutes=1)

        if required_end_date > db_last_ts:
            download_start = db_last_ts + timedelta(minutes=1)
            download_end = required_end_date
            logger.info(f"Downloading recent data from {download_start} to {download_end} using LIVE client.")
            df_recent = collector._get_historical_klines(download_start, download_end, client=historical_client)
            if not df_recent.empty:
                collector._write_dataframe_to_postgres(df_recent)
        else:
            logger.info("Recent data is already up-to-date. No recent download needed.")
    else:
        logger.warning("Cannot download new data in offline mode. Proceeding with existing data.")

    logger.info("--- Intelligent and Safe Data Preparation Finished ---")


if __name__ == '__main__':
    # The main entry point is now intended for live collection.
    # Backtest data preparation is handled by its own script.
    logger.info("Running CorePriceCollector in live collection mode...")
    collector = CorePriceCollector()
    collector.run()
