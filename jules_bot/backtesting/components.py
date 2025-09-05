import pandas as pd
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator

class BacktestFeatureCalculator:
    """
    A mock feature calculator for backtesting.
    It holds a complete historical dataframe with pre-calculated features
    and provides it to the TradingBot one candle at a time, mimicking
    the behavior of the LiveFeatureCalculator.
    """
    def __init__(self, full_feature_df: pd.DataFrame):
        self._full_feature_df = full_feature_df
        self._current_candle = None
        self._current_index = -1

    def get_features_dataframe(self) -> pd.DataFrame:
        """
        Returns a DataFrame containing only the current candle for the backtest.
        """
        if self._current_candle is None:
            return pd.DataFrame()
        # The trading bot's logic expects a DataFrame, so we return the current
        # candle (which is a Series) as a single-row DataFrame.
        return self._current_candle.to_frame().T

    def advance_to_next_candle(self) -> bool:
        """
        Advances the internal pointer to the next candle in the historical data.
        Returns True if successful, False if the end of the data is reached.
        """
        self._current_index += 1
        if self._current_index >= len(self._full_feature_df):
            self._current_candle = None
            return False

        self._current_candle = self._full_feature_df.iloc[self._current_index]
        return True

    @property
    def current_candle(self):
        return self._current_candle

from jules_bot.core.mock_exchange import MockTrader
from decimal import Decimal

class BacktestPortfolioManager:
    """
    A mock portfolio manager for backtesting.
    It interfaces with the MockTrader to get the current portfolio value.
    """
    def __init__(self, mock_trader: MockTrader):
        self._mock_trader = mock_trader

    def get_total_portfolio_value(self, current_price: Decimal, force_recalculation: bool = False) -> Decimal:
        """
        Returns the total portfolio value from the mock trader.
        The 'current_price' is used by the mock trader, which is updated on each cycle.
        """
        return self._mock_trader.get_total_portfolio_value()
