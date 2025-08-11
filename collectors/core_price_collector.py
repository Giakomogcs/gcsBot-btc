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
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.logger import logger

class CorePriceCollector:
    def __init__(self, bucket_name: Optional[str] = None):
        logger.info("Initializing CorePriceCollector...")
        db_config = config_manager.get_db_config()

        if bucket_name:
            bucket = bucket_name
        else:
            bucket = config_manager.get('INFLUXDB', 'bucket_prices')
        
        db_config['bucket'] = bucket
        self.db_manager = DatabaseManager(config=db_config)
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

    def _write_dataframe_to_influx(self, df: pd.DataFrame):
        """
        Writes a DataFrame to InfluxDB in chunks with a progress bar, adding required tags.
        """
        if df.empty:
            logger.info("DataFrame is empty, nothing to write.")
            return

        logger.info(f"Preparing to write {len(df)} rows to InfluxDB measurement '{self.measurement}'...")
        df['symbol'] = self.symbol
        df['source'] = self.source
        df['interval'] = self.interval

        chunk_size = 50_000
        try:
            with tqdm(total=len(df), desc="Writing data to InfluxDB", unit="rows") as pbar:
                for i in range(0, len(df), chunk_size):
                    chunk = df.iloc[i:i + chunk_size]
                    self.db_manager.write_api.write(
                        bucket=self.db_manager.bucket,
                        record=chunk,
                        data_frame_measurement_name=self.measurement,
                        data_frame_tag_columns=['symbol', 'source', 'interval']
                    )
                    pbar.update(len(chunk))
            logger.info(f"\nSuccessfully wrote {len(df)} new candles to '{self.db_manager.bucket}'.")
        except Exception as e:
            logger.error(f"\nError writing data to InfluxDB: {e}", exc_info=True)

    def _query_last_timestamp(self) -> Optional[pd.Timestamp]:
        """
        Queries the last timestamp for the specific symbol, source, and interval.
        """
        logger.info(f"Querying last timestamp for {self.symbol}/{self.source}/{self.interval} in bucket '{self.db_manager.bucket}'...")
        query = f'''
        from(bucket:"{self.db_manager.bucket}")
            |> range(start: 0)
            |> filter(fn: (r) => r._measurement == "{self.measurement}")
            |> filter(fn: (r) => r.symbol == "{self.symbol}")
            |> filter(fn: (r) => r.source == "{self.source}")
            |> filter(fn: (r) => r.interval == "{self.interval}")
            |> last()
            |> keep(columns: ["_time"])
        '''
        try:
            result = self.db_manager.query_api.query(query)
            if not result or not result[0].records:
                logger.info("No existing data found for this series in the measurement.")
                return None
            last_timestamp = pd.to_datetime(result[0].records[0].get_time()).tz_convert('UTC')
            logger.info(f"Last timestamp found in DB: {last_timestamp}")
            return last_timestamp
        except Exception as e:
            logger.error(f"Error querying last timestamp from InfluxDB: {e}", exc_info=True)
            return None

    def _get_historical_klines(self, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
        """
        Fetches historical OHLCV data from Binance, handling pagination automatically.
        """
        logger.info(f"Fetching OHLCV data for {self.symbol} from {start_dt} to {end_dt}...")
        if not self.binance_client:
            logger.warning("Binance client not initialized. Cannot fetch historical klines.")
            return pd.DataFrame()

        all_klines = []
        current_start_dt = start_dt
        end_ms = int(end_dt.timestamp() * 1000)

        with tqdm(total=(end_dt - start_dt).total_seconds() / 60, desc="Downloading from Binance", unit=" candles") as pbar:
            while True:
                current_start_ms = int(current_start_dt.timestamp() * 1000)
                try:
                    klines = self.binance_client.get_historical_klines(
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
        logger.info(f"--- Starting live price collection for bucket '{self.db_manager.bucket}' ---")
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
                    self._write_dataframe_to_influx(df_new_prices)
            
            time.sleep(60)


def prepare_backtest_data(days: int, force_reload: bool = False):
    """
    Acts as a smart guardian for the historical database. It ensures the database
    is up-to-date by downloading only missing data from Binance.
    """
    logger.info("--- Starting Intelligent Data Preparation ---")
    
    collector = CorePriceCollector(bucket_name=config_manager.get('INFLUXDB', 'bucket_backtest'))

    if force_reload:
        logger.warning("`--force-reload` flag detected. Deleting all existing price data for a full refresh.")
        collector.db_manager.clear_measurement(collector.measurement)

    online_mode = collector.connect_binance_client()

    last_ts = collector._query_last_timestamp()
    
    if last_ts is None:
        # Case 1: Database is empty
        logger.info("Database is empty. Performing initial data download.")
        if not online_mode:
            logger.error("CRITICAL: Database is empty and Binance is offline. Cannot proceed.")
            return
        
        end_date = datetime.datetime.now(datetime.timezone.utc)
        start_date = end_date - timedelta(days=days)
        logger.info(f"Downloading data for the last {days} days (from {start_date} to {end_date}).")
        
        df_to_write = collector._get_historical_klines(start_date, end_date)
        if not df_to_write.empty:
            collector._write_dataframe_to_influx(df_to_write)

    else:
        # Case 2: Database has data, check for updates
        if not online_mode:
            logger.warning(f"Binance is offline. Backtest will use existing data up to {last_ts}.")
            logger.info("--- Data Preparation Finished (Offline Mode) ---")
            return

        start_date = last_ts + timedelta(minutes=1)
        end_date = datetime.datetime.now(datetime.timezone.utc)

        if start_date >= end_date:
            logger.info(f"Data is already up-to-date. Last record at {last_ts}. No action needed.")
        else:
            logger.info(f"Data is outdated. Synchronizing new data from {start_date} to {end_date}.")
            df_to_write = collector._get_historical_klines(start_date, end_date)
            if not df_to_write.empty:
                collector._write_dataframe_to_influx(df_to_write)
    
    logger.info("--- Intelligent Data Preparation Finished ---")


if __name__ == '__main__':
    # The main entry point is now intended for live collection.
    # Backtest data preparation is handled by its own script.
    logger.info("Running CorePriceCollector in live collection mode...")
    collector = CorePriceCollector()
    collector.run()
