from decimal import Decimal, getcontext
from jules_bot.utils.config_manager import ConfigManager

# Set precision for Decimal calculations
getcontext().prec = 28

class StrategyRules:
    def __init__(self, strategy_params: dict):
        self.rules = strategy_params
        self.max_capital_per_trade_percent = Decimal(self.rules.get('max_capital_per_trade_percent', '0.02'))
        self.base_usd_per_trade = Decimal(self.rules.get('base_usd_per_trade', '20.0'))
        self.sell_factor = Decimal(self.rules.get('sell_factor', '0.9'))
        self.commission_rate = Decimal(self.rules.get('commission_rate', '0.001'))
        self.target_profit = Decimal(self.rules.get('target_profit', '0.01'))

    def evaluate_buy_signal(self, market_data: dict, open_positions_count: int, difficulty_factor: int = 0) -> tuple[bool, str, str]:
        """
        Evaluates if a buy signal is present, providing detailed reasons for no signal.
        """
        current_price = market_data.get('close')
        high_price = market_data.get('high')
        ema_100 = market_data.get('ema_100')
        ema_20 = market_data.get('ema_20')
        bbl = market_data.get('bbl_20_2_0')

        # Ensure all required data is present
        if any(v is None for v in [current_price, high_price, ema_100, ema_20, bbl]):
            return False, "unknown", "Not enough indicator data"

        # Convert to Decimal for precision
        current_price = Decimal(str(current_price))
        high_price = Decimal(str(high_price))
        ema_100 = Decimal(str(ema_100))
        ema_20 = Decimal(str(ema_20))

        # Adjust the Bollinger Band buy threshold based on the difficulty factor
        difficulty_multiplier = Decimal(1) - (Decimal(difficulty_factor) * Decimal('0.01'))
        adjusted_bbl = Decimal(str(bbl)) * difficulty_multiplier

        # --- Logic with Detailed Failure Reasons ---
        reason = ""
        if open_positions_count == 0:
            # Logic for the first entry
            if current_price > ema_100:
                if current_price > ema_20:
                    return True, "uptrend", "Aggressive first entry (price > ema_20)"
                else: # price is between ema_100 and ema_20
                    reason = f"Price ${current_price:,.2f} is above EMA100 but below EMA20 ${ema_20:,.2f}"
            else: # price is below ema_100
                if current_price <= adjusted_bbl:
                    return True, "downtrend", f"Aggressive first entry (volatility breakout at difficulty {difficulty_factor})"
                else: # price is below ema_100 but above adjusted BBL
                    distance = current_price - adjusted_bbl
                    reason = f"Price ${current_price:,.2f} is ${distance:,.2f} above adjusted BBL ${adjusted_bbl:,.2f} (diff {difficulty_factor})"
        else:
            # Logic for subsequent entries
            if current_price > ema_100:
                if high_price > ema_20 and current_price < ema_20:
                    return True, "uptrend", "Uptrend pullback"
                else:
                    reason = f"In uptrend (price > EMA100), but no pullback signal found (high > ema20 and current < ema20)"
            else: # price is below ema_100
                if current_price <= adjusted_bbl:
                    return True, "downtrend", f"Downtrend volatility breakout (difficulty {difficulty_factor})"
                else:
                    distance = current_price - adjusted_bbl
                    reason = f"Price ${current_price:,.2f} is ${distance:,.2f} above adjusted BBL ${adjusted_bbl:,.2f} (diff {difficulty_factor}, {open_positions_count} pos)"

        return False, "unknown", reason or "No signal"

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
