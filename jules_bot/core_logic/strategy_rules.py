from decimal import Decimal, getcontext, InvalidOperation
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.utils.logger import logger
from typing import Dict

# Set precision for Decimal calculations
getcontext().prec = 28

class StrategyRules:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.section_name = 'STRATEGY_RULES'

        # Load all parameters using the safe getter
        self.max_capital_per_trade_percent = self._safe_get_decimal('max_capital_per_trade_percent', '0.02')
        self.base_usd_per_trade = self._safe_get_decimal('base_usd_per_trade', '20.0')
        self.sell_factor = self._safe_get_decimal('sell_factor', '0.9')
        self.commission_rate = self._safe_get_decimal('commission_rate', '0.001')
        self.difficulty_adjustment_factor = self._safe_get_decimal('difficulty_adjustment_factor', '0.005')

        # Boolean values don't need Decimal conversion
        self.use_reversal_buy_strategy = self.config_manager.getboolean(
            self.section_name, 'use_reversal_buy_strategy', fallback=True
        )

    def _safe_get_decimal(self, key: str, fallback: str) -> Decimal:
        """
        Safely gets a parameter from the STRATEGY_RULES section and converts it to a Decimal.
        Logs a critical error and uses the fallback if conversion fails.
        """
        value_str = self.config_manager.get(self.section_name, key, fallback=fallback)

        if value_str is None:
            logger.warning(f"Config value for '{key}' in section '{self.section_name}' is missing. Using fallback '{fallback}'.")
            return Decimal(fallback)

        try:
            return Decimal(value_str)
        except (InvalidOperation, TypeError) as e:
            logger.critical(
                f"Invalid config value for '{key}' in section '{self.section_name}'. Could not convert to Decimal. "
                f"Value was: '{value_str}'. Using fallback '{fallback}'. Error: {e}"
            )
            return Decimal(fallback)

    def evaluate_buy_signal(self, market_data: dict, open_positions_count: int, difficulty_factor: int = 0, params: Dict[str, Decimal] = None) -> tuple[bool, str, str]:
        """
        Evaluates if a buy signal is present, providing detailed reasons for no signal.
        Uses dynamic parameters for buy dip percentage.
        """
        current_price = market_data.get('close')
        high_price = market_data.get('high')
        ema_100 = market_data.get('ema_100')
        ema_20 = market_data.get('ema_20')
        bbl = market_data.get('bbl_20_2_0')

        if any(v is None for v in [current_price, high_price, ema_100, ema_20, bbl]):
            return False, "unknown", "Not enough indicator data"

        current_price = Decimal(str(current_price))
        high_price = Decimal(str(high_price))
        ema_100 = Decimal(str(ema_100))
        ema_20 = Decimal(str(ema_20))
        
        difficulty_multiplier = Decimal(1) - (Decimal(difficulty_factor) * self.difficulty_adjustment_factor)
        adjusted_bbl = Decimal(str(bbl)) * difficulty_multiplier

        # --- Dynamic Dip Logic with Difficulty Adjustment ---
        base_buy_dip = params.get('buy_dip_percentage', Decimal('0.02')) if params else Decimal('0.02')
        difficulty_adjustment = Decimal(difficulty_factor) * self.difficulty_adjustment_factor
        adjusted_buy_dip_percentage = base_buy_dip + difficulty_adjustment
        price_dip_target = high_price * (Decimal('1') - adjusted_buy_dip_percentage)

        reason = ""
        if open_positions_count == 0:
            if current_price > ema_100:
                if current_price > ema_20:
                    return True, "uptrend", "Aggressive first entry (price > ema_20)"
                elif current_price <= price_dip_target:
                    if self.use_reversal_buy_strategy:
                        return True, "START_MONITORING", f"Dip target hit at {adjusted_buy_dip_percentage:.2%}. Starting reversal monitoring."
                    else:
                        return True, "uptrend", f"Dip buy signal triggered at {adjusted_buy_dip_percentage:.2%}"
                else:
                    reason = f"Price ${current_price:,.2f} is above EMA100 but below EMA20 ${ema_20:,.2f}"
            else:
                if current_price <= adjusted_bbl:
                    return True, "downtrend", f"Aggressive first entry (volatility breakout at difficulty {difficulty_factor})"
                else:
                    reason = f"Buy target: ${adjusted_bbl:,.2f}. Price is too high."
        else:
            if current_price > ema_100:
                if high_price > ema_20 and current_price < ema_20:
                    return True, "uptrend", "Uptrend pullback"
                elif current_price <= price_dip_target:
                    if self.use_reversal_buy_strategy:
                        return True, "START_MONITORING", f"Dip target hit on existing position at {adjusted_buy_dip_percentage:.2%}. Starting reversal monitoring."
                    else:
                        return True, "uptrend", f"Dip buy signal on existing position at {adjusted_buy_dip_percentage:.2%}"
                else:
                    reason = f"In uptrend (price > EMA100), but no pullback signal found"
            else:
                if current_price <= adjusted_bbl:
                    return True, "downtrend", f"Downtrend volatility breakout (difficulty {difficulty_factor})"
                else:
                    reason = f"Buy target: ${adjusted_bbl:,.2f}. Price is too high."
        
        return False, "unknown", reason or "No signal"

    def calculate_sell_target_price(self, purchase_price: Decimal, params: Dict[str, Decimal] = None) -> Decimal:
        """
        Calculates the target sell price using dynamic sell_rise_percentage.
        Handles cases where params might be None.
        """
        purchase_price = Decimal(purchase_price)

        # If params is None (e.g., during historical sync), use default values.
        if params is None:
            params = {}

        # Use sell_rise_percentage for the calculation, not target_profit
        sell_rise_percentage = params.get('sell_rise_percentage', Decimal('0.01'))
        one = Decimal('1')

        numerator = purchase_price * (one + self.commission_rate)
        denominator = one - self.commission_rate

        if denominator == 0:
            return Decimal('inf')

        break_even_price = numerator / denominator
        # The sell target is based on the rise percentage from the break-even price
        sell_target_price = break_even_price * (one + sell_rise_percentage)
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
