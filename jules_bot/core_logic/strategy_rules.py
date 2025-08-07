from jules_bot.utils.config_manager import ConfigManager

class StrategyRules:
    def __init__(self, config_manager: ConfigManager):
        self.rules = config_manager.get_section('STRATEGY_RULES')

    def get_next_buy_trigger(self, open_positions_count: int) -> float:
        """
        This method will contain the logic for the "Dynamic Grid Scaling".
        Based on the number of open positions, it will return the required
        percentage drop for the next buy (e.g., 0.01 for 1%, 0.015 for 1.5%).
        """
        if open_positions_count < 5:
            return float(self.rules['buy_trigger_few_positions'])
        else:
            return float(self.rules['buy_trigger_many_positions'])

    def get_next_buy_amount(self, capital_allocated_percent: float, base_amount: float) -> float:
        """
        This method will contain the logic for "Dynamic Capital Allocation".
        Based on the percentage of capital already in use, it will return
        the calculated USDT amount for the next purchase (e.g., base_amount * 0.8).
        """
        if capital_allocated_percent < 0.5:
            return base_amount * float(self.rules['buy_amount_low_allocation_multiplier'])
        else:
            return base_amount * float(self.rules['buy_amount_high_allocation_multiplier'])
