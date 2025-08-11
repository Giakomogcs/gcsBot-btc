from jules_bot.utils.config_manager import ConfigManager

class StrategyRules:
    def __init__(self, config_manager: ConfigManager):
        self.rules = config_manager.get_section('STRATEGY_RULES')

    def get_next_buy_amount(self, available_balance: float) -> float:
        """
        Calculates the USDT amount for the next purchase based on a fixed
        percentage of the available capital.
        """
        max_capital_percent = float(self.rules.get('max_capital_per_trade_percent', 0.02))

        # Calculate the trade size based on the available balance and the configured percentage
        trade_size = available_balance * max_capital_percent

        return trade_size
