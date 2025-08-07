# File: gcs_bot/core/market_data_provider.py
import logging
import pandas as pd
from jules_bot.database.database_manager import DatabaseManager

class MarketDataProvider:
    """
    Responsible for fetching historical market data from a dedicated InfluxDB bucket.
    """
    def __init__(self, db_manager: DatabaseManager):
        """
        Initializes the provider with a DatabaseManager instance that is already
        configured to point to the historical data bucket.
        """
        self.db_manager = db_manager
        logging.info(f"MarketDataProvider initialized for bucket: '{self.db_manager.bucket}'")

    def get_historical_data(self, symbol: str, start: str, end: str = "now()") -> pd.DataFrame | None:
        """
        Queries the InfluxDB bucket for OHLCV data for a given symbol and time range.

        Args:
            symbol (str): The trading symbol to fetch (e.g., 'BTC/USD').
            start (str): The start of the time range (e.g., '-7d', '2023-01-01T00:00:00Z').
            end (str): The end of the time range, defaults to now.

        Returns:
            A Pandas DataFrame indexed by timestamp with columns [open, high, low, close, volume],
            or None if an error occurs or no data is found.
        """
        try:
            # This query assumes your historical data has the measurement "crypto_prices"
            # and fields named 'open', 'high', 'low', 'close', 'volume'.
            # Adjust if your schema is different.
            flux_query = f'''
            from(bucket: "{self.db_manager.bucket}")
              |> range(start: {start}, stop: {end})
              |> filter(fn: (r) => r._measurement == "crypto_prices" and r.symbol == "{symbol}")
              |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
              |> keep(columns: ["_time", "open", "high", "low", "close", "volume"])
              |> sort(columns: ["_time"], desc: false)
            '''

            logging.debug(f"Querying market data for {symbol} from {start} to {end}")
            df = self.db_manager.query_api.query_data_frame(query=flux_query, org=self.db_manager.org)

            if df.empty:
                logging.warning(f"No market data found for {symbol} in the specified range.")
                return None

            # Clean up the DataFrame
            df = df.rename(columns={'_time': 'timestamp'})
            df = df.set_index('timestamp')
            df = df.drop(columns=['result', 'table'], errors='ignore')

            # Ensure correct data types
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            return df

        except Exception as e:
            logging.error(f"Failed to fetch or process market data from InfluxDB: {e}")
            return None
