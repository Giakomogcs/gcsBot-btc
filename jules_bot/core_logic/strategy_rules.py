from jules_bot.utils.config_manager import ConfigManager

class StrategyRules:
    def __init__(self, config_manager: ConfigManager):
        self.rules = config_manager.get_section('STRATEGY_RULES')
        self.max_capital_per_trade_percent = float(self.rules.get('max_capital_per_trade_percent', 0.02))
        self.base_usd_per_trade = float(self.rules.get('base_usd_per_trade', 20.0))
        self.sell_factor = float(self.rules.get('sell_factor', 0.9))

    def evaluate_buy_signal(self, market_data: dict) -> (bool, str, str):
        """
        Evaluates if a buy signal is present based on the market regime.
        Returns a tuple of (should_buy, regime, reason).
        """
        current_price = market_data.get('close')
        high_price = market_data.get('high')
        ema_100 = market_data.get('ema_100')
        ema_20 = market_data.get('ema_20')
        bbl = market_data.get('bbl_20_2_0')

        if any(v is None for v in [current_price, high_price, ema_100, ema_20, bbl]):
            return False, "unknown", "Not enough indicator data"

        # Determine market regime
        if current_price > ema_100:
            regime = "uptrend"
            # Uptrend Regime Logic
            if high_price > ema_20 and current_price < ema_20:
                return True, regime, "Uptrend pullback"
        else:
            regime = "downtrend"
            # Downtrend Regime Logic
            if current_price <= bbl:
                return True, regime, "Downtrend volatility breakout"

        return False, regime, "No signal"

    def get_next_buy_amount(self, available_balance: float) -> float:
        """
        Calculates the USDT amount for the next purchase.
        """
        # Calculate trade size based on percentage of available capital
        capital_based_size = available_balance * self.max_capital_per_trade_percent

        # The trade size is the smaller of the base amount or the capital-based amount
        trade_size = min(self.base_usd_per_trade, capital_based_size)

        return trade_size

    def calculate_sell_target_price(self, purchase_price: float) -> float:
        """
        Calculates the target sell price based on the purchase price, commission,
        and target profit.
        """
        commission_rate = float(self.rules.get('commission_rate', 0.001))
        target_profit = float(self.rules.get('target_profit', 0.01))

        # Formula to calculate the price needed to break even, accounting for commissions on both buy and sell
        # P_sell * (1 - commission) = P_buy * (1 + commission)
        # P_sell_breakeven = P_buy * (1 + commission) / (1 - commission)
        numerator = purchase_price * (1 + commission_rate)
        denominator = (1 - commission_rate)

        if denominator == 0:
            return float('inf') # Avoid division by zero, return infinity

        break_even_price = numerator / denominator

        # Apply the target profit to the break-even price
        sell_target_price = break_even_price * (1 + target_profit)

        return sell_target_price
