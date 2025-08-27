import os
import pandas as pd
import logging
from binance.client import Client
from jules_bot.utils.config_manager import config_manager

class ExchangeManager:
    """
    Handles all direct communication with the Binance API.
    """
    def __init__(self, mode: str = 'trade', bot_name: str = None):
        self.mode = mode
        self.bot_name = bot_name
        self.client = self._initialize_binance_client()

    def _initialize_binance_client(self):
        """Initializes the Binance client based on the execution mode."""
        testnet = False

        # This is the crucial part for multi-bot support.
        # We re-initialize the config_manager with the specific bot name
        # so it can fetch the correct, bot-specific environment variables.
        if self.bot_name:
            config_manager.initialize(self.bot_name)

        if self.mode == 'test':
            api_key = config_manager.get('BINANCE_TESTNET', 'api_key')
            api_secret = config_manager.get('BINANCE_TESTNET', 'api_secret')
            testnet = True
        elif self.mode == 'trade':
            api_key = config_manager.get('BINANCE_LIVE', 'api_key')
            api_secret = config_manager.get('BINANCE_LIVE', 'api_secret')
            testnet = False
        else:
            logging.warning("ExchangeManager initialized without a client (mode is not 'trade' or 'test').")
            return None

        if not api_key or not api_secret:
            raise ValueError(f"API keys for {self.mode} mode are not set in the environment.")

        requests_params = {"timeout": 30}
        client = Client(api_key, api_secret, testnet=testnet, requests_params=requests_params)
        logging.info(f"Binance client initialized for {'testnet' if testnet else 'mainnet'}.")
        return client

    def get_historical_candles(self, symbol: str, interval: str, limit: int = 1000) -> pd.DataFrame:
        """
        Fetches historical OHLCV data from Binance.
        """
        if not self.client:
            logging.error("Binance client not initialized.")
            return pd.DataFrame()
        try:
            # Fetch the data from Binance
            klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)

            # Create a DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])

            # Convert timestamp to datetime and set as index
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('timestamp', inplace=True)

            # Select and convert necessary columns to numeric
            ohlcv_columns = ['open', 'high', 'low', 'close', 'volume']
            df = df[ohlcv_columns]
            df = df.apply(pd.to_numeric)

            return df

        except Exception as e:
            logging.error(f"Error fetching historical candles from Binance: {e}")
            return pd.DataFrame()

    def get_current_price(self, symbol: str) -> float | None:
        """
        Fetches the current price for a specific symbol.
        """
        if not self.client:
            logging.error("Binance client not initialized.")
            return None
        try:
            ticker = self.client.get_ticker(symbol=symbol)
            return float(ticker['lastPrice'])
        except Exception as e:
            logging.error(f"Error fetching current price for {symbol}: {e}")
            return None

    def get_account_balance(self) -> list:
        """
        Fetches account balance from Binance.
        """
        if not self.client:
            logging.error("Binance client not initialized.")
            return []
        try:
            account_info = self.client.get_account()
            balances = [
                {
                    'asset': balance['asset'],
                    'free': balance['free'],
                    'locked': balance['locked']
                }
                for balance in account_info['balances']
                if float(balance['free']) > 0 or float(balance['locked']) > 0
            ]
            return balances
        except Exception as e:
            logging.error(f"CRITICAL_ERROR: Failed to fetch account balance from Binance API. This is likely due to incorrect API keys or permissions. Error: {e}", exc_info=True)
            return []

    def get_open_orders(self, symbol: str) -> list:
        """
        Fetches open orders for a specific symbol from Binance.
        """
        if not self.client:
            logging.error("Binance client not initialized.")
            return []
        try:
            open_orders = self.client.get_open_orders(symbol=symbol)
            return open_orders
        except Exception as e:
            logging.error(f"Error fetching open orders for {symbol}: {e}")
            return []
