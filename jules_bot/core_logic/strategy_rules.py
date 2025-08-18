from decimal import Decimal, getcontext
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.core.market_mode import MarketMode

# Set precision for Decimal calculations
getcontext().prec = 28

class StrategyRules:
    def __init__(self, config_manager: ConfigManager):
        self.rules = config_manager.get_section('STRATEGY_RULES')
        self.max_capital_per_trade_percent = Decimal(self.rules.get('max_capital_per_trade_percent', '0.02'))
        self.base_usd_per_trade = Decimal(self.rules.get('base_usd_per_trade', '20.0'))
        self.sell_factor = Decimal(self.rules.get('sell_factor', '0.9'))
        self.commission_rate = Decimal(self.rules.get('commission_rate', '0.001'))
        self.target_profit = Decimal(self.rules.get('target_profit', '0.01'))
        # Adaptive Strategy Params
        self.stable_spacing_percent = Decimal(self.rules.get('stable_spacing_percent', '0.005'))
        self.freefall_spacing_percent = Decimal(self.rules.get('freefall_spacing_percent', '0.02'))
        self.uptrend_spacing_percent = Decimal(self.rules.get('uptrend_spacing_percent', '0.003'))

    def determine_buy_decision(self, market_mode: MarketMode, current_price: Decimal, last_buy_price: Decimal, high_price: Decimal) -> tuple[bool, str]:
        """
        Determines whether to buy based on the current market mode and price.
        """
        if last_buy_price == Decimal('inf'):
            return True, "First purchase"

        if market_mode == MarketMode.DEFENSIVE:
            target_price = last_buy_price * (Decimal('1') - self.freefall_spacing_percent)
            if current_price <= target_price:
                return True, f"Defensive buy triggered at {current_price:.2f} (target: {target_price:.2f})"

        elif market_mode == MarketMode.STANDARD:
            target_price = last_buy_price * (Decimal('1') - self.stable_spacing_percent)
            if current_price <= target_price:
                return True, f"Standard buy triggered at {current_price:.2f} (target: {target_price:.2f})"

        elif market_mode == MarketMode.AGGRESSIVE:
            target_price = high_price * (Decimal('1') - self.uptrend_spacing_percent)
            if current_price <= target_price:
                return True, f"Aggressive buy triggered at {current_price:.2f} (target: {target_price:.2f}, high: {high_price:.2f})"

        return False, "No buy signal"

    def get_next_buy_amount(self, available_balance: Decimal) -> Decimal:
        """
        Calculates the USDT amount for the next purchase using Decimal.
        """
        available_balance = Decimal(available_balance)
        capital_based_size = available_balance * self.max_capital_per_trade_percent
        trade_size = min(self.base_usd_per_trade, capital_based_size)
        return trade_size

    def calculate_sell_target_price(self, purchase_price: Decimal) -> Decimal:
        """
        Calculates the target sell price using Decimal.
        """
        purchase_price = Decimal(purchase_price)
        one = Decimal('1')

        numerator = purchase_price * (one + self.commission_rate)
        denominator = one - self.commission_rate

        if denominator == 0:
            return Decimal('inf')

        break_even_price = numerator / denominator
        sell_target_price = break_even_price * (one + self.target_profit)
        return sell_target_price

    def calculate_realized_pnl(self, buy_price: Decimal, sell_price: Decimal, quantity_sold: Decimal) -> Decimal:
        """
        Calculates the realized profit or loss from a trade using Decimal.
        """
        buy_price = Decimal(buy_price)
        sell_price = Decimal(sell_price)
        quantity_sold = Decimal(quantity_sold)
        one = Decimal('1')

        net_revenue_per_unit = sell_price * (one - self.commission_rate)
        net_cost_per_unit = buy_price * (one + self.commission_rate)
        
        profit_per_unit = net_revenue_per_unit - net_cost_per_unit
        realized_pnl = profit_per_unit * quantity_sold
        return realized_pnl

    def calculate_net_unrealized_pnl(self, entry_price: Decimal, current_price: Decimal, total_quantity: Decimal) -> Decimal:
        """
        Calculates the net unrealized PnL for an open position using Decimal.
        """
        entry_price = Decimal(entry_price)
        current_price = Decimal(current_price)
        total_quantity = Decimal(total_quantity)

        quantity_to_sell = total_quantity * self.sell_factor
        
        net_unrealized_pnl = self.calculate_realized_pnl(
            buy_price=entry_price,
            sell_price=current_price,
            quantity_sold=quantity_to_sell
        )
        return net_unrealized_pnl
