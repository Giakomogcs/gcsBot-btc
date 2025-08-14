import logging
import pandas as pd
from jules_bot.database.postgres_manager import PostgresManager

class MarketDataProvider:
    """
    Responsible for fetching historical market data from the PostgreSQL database.
    """
    def __init__(self, db_manager: PostgresManager):
        """
        Initializes the provider with a PostgresManager instance.
        """
        self.db_manager = db_manager
        logging.info("MarketDataProvider initialized with PostgresManager.")

    def get_historical_data(self, symbol: str, start: str, end: str = "now()") -> pd.DataFrame | None:
        """
        Queries the PostgreSQL database for OHLCV data for a given symbol and time range.

        Args:
            symbol (str): The trading symbol to fetch (e.g., 'BTCUSDT').
            start (str): The start of the time range (e.g., '-7d', '2023-01-01T00:00:00Z').
            end (str): The end of the time range, defaults to now.

        Returns:
            A Pandas DataFrame indexed by timestamp with columns [open, high, low, close, volume],
            or None if an error occurs or no data is found.
        """
        try:
            logging.debug(f"Querying market data for {symbol} from {start} to {end}")
            # The 'measurement' in the old system is now the 'symbol' in the new system
            df = self.db_manager.get_price_data(measurement=symbol, start_date=start, end_date=end)

            if df.empty:
                logging.warning(f"No market data found for {symbol} in the specified range.")
                return None

            return df

        except Exception as e:
            logging.error(f"Failed to fetch or process market data from PostgreSQL: {e}", exc_info=True)
            return None
