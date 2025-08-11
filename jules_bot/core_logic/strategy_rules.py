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
