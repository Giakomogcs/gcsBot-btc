from enum import Enum, auto

class MarketRegime(Enum):
    UPTREND = auto()
    DOWNTREND = auto()
    HIGH_VOLATILITY = auto()

class RegimeManager:
    """
    Determines the current market regime based on technical indicators.
    """
    def __init__(self, config_manager=None):
        # In the future, thresholds could be loaded from config_manager
        self.config = config_manager
        # This threshold is an example. A better approach would be to calculate it based on historical percentile.
        self.volatility_threshold = 4.0

    def get_regime(self, market_data: dict) -> MarketRegime:
        """
        Determines the market regime from the latest market data candle.

        Args:
            market_data: A dictionary-like object (e.g., a pandas Series) containing
                         the latest market data with calculated indicators.

        Returns:
            The determined MarketRegime (UPTREND, DOWNTREND, or HIGH_VOLATILITY).
        """
        current_price = market_data.get('close')
        ema_100 = market_data.get('ema_100')
        bollinger_bandwidth = market_data.get('bbb_20_2_0')

        if any(v is None for v in [current_price, ema_100, bollinger_bandwidth]):
            # Default to downtrend if data is missing, as it's the most conservative stance
            return MarketRegime.DOWNTREND

        # High volatility overrides trend direction
        if bollinger_bandwidth > self.volatility_threshold:
            return MarketRegime.HIGH_VOLATILITY

        # Determine trend based on EMA
        if current_price > ema_100:
            return MarketRegime.UPTREND
        else:
            return MarketRegime.DOWNTREND
