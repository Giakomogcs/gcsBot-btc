from decimal import Decimal, getcontext, InvalidOperation
from jules_bot.utils.config_manager import ConfigManager

# Set precision for Decimal calculations
getcontext().prec = 28

def _calculate_progress_pct(current_price: Decimal, start_price: Decimal, target_price: Decimal) -> Decimal:
    """
    Calculates the percentage progress of a value from a starting point to a target.
    Clamps the result between 0 and 100.
    """
    if current_price is None or start_price is None or target_price is None:
        return Decimal('0.0')

    # Avoid division by zero if start and target prices are the same.
    if target_price == start_price:
        return Decimal('100.0') if current_price >= target_price else Decimal('0.0')

    try:
        # Calculate progress as a percentage. This works for both long and short scenarios.
        progress = (current_price - start_price) / (target_price - start_price) * Decimal('100')

        # Clamp the result between 0% and 100%.
        return max(Decimal('0'), min(progress, Decimal('100')))
    except (InvalidOperation, ZeroDivisionError):
        return Decimal('0.0')


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

    def get_buy_target_info(self, market_data: dict, open_positions_count: int) -> tuple[Decimal, Decimal]:
        """
        Calculates the target price for the next buy and the progress towards it.
        This is the single source of truth for the buy target displayed in the TUI.
        """
        try:
            current_price = Decimal(str(market_data.get('close')))
            ema_20 = Decimal(str(market_data.get('ema_20')))
            bbl = Decimal(str(market_data.get('bbl_20_2_0')))
            ema_100 = Decimal(str(market_data.get('ema_100')))
            high_price = Decimal(str(market_data.get('high', current_price)))
        except (InvalidOperation, TypeError):
            return Decimal('0'), Decimal('0')

        # This logic should mirror `evaluate_buy_signal` to determine the *next* target.

        # Case 1: No open positions, looking for the first entry.
        if open_positions_count == 0:
            if current_price > ema_100:  # In an uptrend
                # The strategy buys aggressively if price > ema_20.
                # The "target" is ema_20, but for a pullback.
                # If we are already above, the next logical target is a pullback to ema_20.
                target_price = ema_20
                # Progress is how close we are to pulling back to ema_20 from the high.
                progress = _calculate_progress_pct(current_price, high_price, target_price)
            else:  # In a downtrend
                # The strategy buys on a volatility breakout at the lower Bollinger Band.
                target_price = bbl
                # Progress is how close the current price is to hitting the bbl from the high.
                progress = _calculate_progress_pct(current_price, high_price, target_price)
            return target_price, progress

        # Case 2: Already have open positions, looking for pullbacks or breakouts.
        if current_price > ema_100:  # In an uptrend, waiting for a pullback.
            target_price = ema_20
            progress = _calculate_progress_pct(current_price, high_price, target_price)
        else:  # In a downtrend, waiting for a breakout.
            target_price = bbl
            progress = _calculate_progress_pct(current_price, high_price, target_price)

        return target_price, progress

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
