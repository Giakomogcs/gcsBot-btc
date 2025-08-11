from jules_bot.utils.config_manager import ConfigManager

class StrategyRules:
    def __init__(self, config_manager: ConfigManager):
        self.rules = config_manager.get_section('STRATEGY_RULES')
        self.trading_strategy_config = config_manager.get_section('TRADING_STRATEGY')

    def get_next_buy_amount(self, available_balance: float) -> float:
        """
        Calculates the USDT amount for the next purchase based on risk management rules.
        The amount is the lesser of a fixed base amount and a percentage of the total available capital.
        """
        base_amount = float(self.trading_strategy_config.get('usd_per_trade', 100.0))

        max_capital_percent = float(self.rules.get('max_capital_per_trade_percent', 0.02))

        # Calculate the maximum trade size based on the available balance
        max_trade_size_from_balance = available_balance * max_capital_percent

        # Return the smaller of the two values to ensure we don't risk too much
        return min(base_amount, max_trade_size_from_balance)
