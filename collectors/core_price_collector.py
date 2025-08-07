import os
import sys
import datetime
import pandas as pd
import time
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from typing import Optional

# Adiciona a raiz do projeto ao path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.logger import logger

class CorePriceCollector:
    def __init__(self):
        logger.info("Initializing CorePriceCollector...")
        db_config = config_manager.get_section('INFLUXDB')
        db_config['url'] = f"http://{db_config['host']}:{db_config['port']}"
        self.db_manager = DatabaseManager(config=db_config)
        self.binance_client = self._init_binance_client()
        self.symbol = config_manager.get('APP', 'symbol')
        self.measurement = f"btc_prices"

    def _init_binance_client(self) -> Optional[Client]:
        if config_manager.getboolean('APP', 'force_offline_mode', fallback=False):
            logger.warning("Force offline mode is enabled. Binance client will not be initialized.")
            return None
        try:
            use_testnet = config_manager.getboolean('APP', 'use_testnet', fallback=False)
            if use_testnet:
                binance_config = config_manager.get_section('BINANCE_TESTNET')
            else:
                binance_config = config_manager.get_section('BINANCE_LIVE')

            api_key = binance_config.get('api_key')
            api_secret = binance_config.get('api_secret')

            if not api_key or not api_secret:
                logger.warning("Binance API Key/Secret not found.")
                return None

            client = Client(api_key, api_secret, tld='com', testnet=use_testnet)
            client.ping()
            logger.info(f"Binance client initialized successfully in {'TESTNET' if use_testnet else 'LIVE'} mode.")
            return client
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"Failed to connect to Binance: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred during Binance client initialization: {e}", exc_info=True)
            return None

    def _write_dataframe_to_influx(self, df: pd.DataFrame, measurement: str):
        logger.info(f"Preparing to write {len(df)} rows to InfluxDB measurement '{measurement}'...")
        write_api = self.db_manager.get_write_api()
        if not write_api:
            logger.error("InfluxDB write API is not available. Aborting write operation.")
            return

        try:
            write_api.write(
                bucket=self.db_manager.bucket,
                record=df,
                data_frame_measurement_name=measurement,
                data_frame_timestamp_column="timestamp"
            )
            logger.info(f"Successfully wrote {len(df)} new candles to InfluxDB.")
        except Exception as e:
            logger.error(f"Error writing data to InfluxDB: {e}", exc_info=True)

    def _query_last_timestamp(self) -> Optional[pd.Timestamp]:
        logger.info(f"Querying last timestamp from measurement '{self.measurement}'...")
        query_api = self.db_manager.get_query_api()
        if not query_api:
            logger.error("InfluxDB query API is not available.")
            return None

        query = f'from(bucket:"{self.db_manager.bucket}") |> range(start: 0) |> filter(fn: (r) => r._measurement == "{self.measurement}") |> last() |> keep(columns: ["_time"])'

        try:
            result = query_api.query(query)
            if not result or not result[0].records:
                logger.info("No existing data found in measurement.")
                return None

            last_timestamp = pd.to_datetime(result[0].records[0].get_time()).tz_convert('UTC')
            logger.info(f"Last timestamp found in DB: {last_timestamp}")
            return last_timestamp
        except Exception as e:
            logger.error(f"Error querying last timestamp from InfluxDB: {e}", exc_info=True)
            return None

    def _get_historical_klines(self, start_dt: datetime.datetime, end_dt: datetime.datetime) -> pd.DataFrame:
        logger.info(f"Fetching OHLCV data for {self.symbol} from {start_dt} to {end_dt}...")
        if not self.binance_client:
            logger.warning("Binance client not initialized. Cannot fetch historical klines.")
            return pd.DataFrame()

        try:
            klines = self.binance_client.get_historical_klines(self.symbol, Client.KLINE_INTERVAL_1MINUTE, str(start_dt), str(end_dt))
            if not klines:
                logger.info("No new klines found for the specified period.")
                return pd.DataFrame()

            df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','qav','nt','tbbav','tbqav','ignore'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)
            df = df[['open','high','low','close','volume']].astype(float)
            logger.info(f"Fetched {len(df)} new candles from Binance.")
            return df
        except Exception as e:
            logger.error(f"API Error fetching klines: {e}", exc_info=True)
            return pd.DataFrame()

    def run(self):
        logger.info("--- Starting price collection ---")

        last_timestamp = self._query_last_timestamp()

        if last_timestamp:
            start_date = last_timestamp + pd.Timedelta(minutes=1)
        else:
            start_date_str = config_manager.get('DATA_PIPELINE', 'start_date_ingestion', fallback='2023-01-01')
            start_date = pd.to_datetime(start_date_str, utc=True)
            logger.info(f"No existing data. Starting collection from {start_date_str}.")

        end_date = datetime.datetime.now(datetime.timezone.utc)

        if start_date >= end_date:
            logger.info("Price data is already up to date. No new data to fetch.")
            return

        df_new_prices = self._get_historical_klines(start_date, end_date)

        if not df_new_prices.empty:
            self._write_dataframe_to_influx(df_new_prices, self.measurement)

        logger.info("--- Price collection finished ---")

if __name__ == '__main__':
    collector = CorePriceCollector()
    collector.run()
