from decimal import Decimal, getcontext
from jules_bot.utils.config_manager import ConfigManager

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

    def evaluate_buy_signal(self, market_data: dict, open_positions_count: int) -> tuple[bool, str, str]:
        """
        Evaluates if a buy signal is present. Non-financial logic, so floats are acceptable here
        for performance with technical indicators.
        """
        current_price = market_data.get('close')
        high_price = market_data.get('high')
        ema_100 = market_data.get('ema_100')
        ema_20 = market_data.get('ema_20')
        bbl = market_data.get('bbl_20_2_0')

        if any(v is None for v in [current_price, high_price, ema_100, ema_20, bbl]):
            return False, "unknown", "Not enough indicator data"

        if open_positions_count == 0:
            if current_price > ema_100:
                if current_price > ema_20:
                    return True, "uptrend", "Aggressive first entry (price > ema_20)"
            else:
                if current_price <= bbl:
                    return True, "downtrend", "Aggressive first entry (volatility breakout)"
        else:
            if current_price > ema_100:
                if high_price > ema_20 and current_price < ema_20:
                    return True, "uptrend", "Uptrend pullback"
            else:
                if current_price <= bbl:
                    return True, "downtrend", "Downtrend volatility breakout"

        return False, "unknown", "No signal"

    def get_next_buy_amount(self, available_balance: Decimal) -> Decimal:
        """
        Calculates the USDT amount for the next purchase using Decimal.
        """
        available_balance = Decimal(available_balance)
        capital_based_size = available_balance * self.max_capital_per_trade_percent
        trade_size = min(self.base_usd_per_trade, capital_based_size)
        return trade_size

    def calculate_take_profit_details(self, total_cost_invested: Decimal, total_quantity_bought: Decimal) -> dict:
        """
        Calculates take-profit details based on a target monetary profit.

        Args:
            total_cost_invested: The total amount in quote currency (e.g., USDT) used to open the position.
            total_quantity_bought: The total amount of the base asset (e.g., BTC) acquired.

        Returns:
            A dictionary containing:
            - trigger_price: The calculated sell price to hit the profit target.
            - sell_quantity: The amount of base asset to sell.
            - treasury_quantity: The amount of base asset remaining after the sell.
        """
        # Ensure inputs are Decimal for precision
        total_cost_invested = Decimal(total_cost_invested)
        total_quantity_bought = Decimal(total_quantity_bought)
        one = Decimal('1')

        # Step 1: Calculate the desired net value (money in pocket)
        # This is the total amount we want back after selling, including profit.
        desired_net_value = total_cost_invested * (one + self.target_profit)

        # Step 2: Calculate the quantity of the asset to be sold
        # This is a fraction of the total position, defined by sell_factor.
        quantity_to_sell = total_quantity_bought * self.sell_factor

        # Step 3: Calculate the trigger sell price
        # This is the price that, when executed for `quantity_to_sell`, gives us the `desired_net_value` after fees.
        # The formula is derived from: trigger_price * quantity_to_sell * (1 - commission_rate) = desired_net_value
        denominator = quantity_to_sell * (one - self.commission_rate)
        if denominator == 0:
            # Avoid division by zero; this would only happen if quantity_to_sell is zero.
            trigger_price = Decimal('inf')
        else:
            trigger_price = desired_net_value / denominator

        # Calculate the quantity that will remain as treasury
        treasury_quantity = total_quantity_bought - quantity_to_sell

        return {
            "trigger_price": trigger_price,
            "sell_quantity": quantity_to_sell,
            "treasury_quantity": treasury_quantity,
        }

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
