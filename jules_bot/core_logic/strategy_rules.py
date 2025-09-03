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
        self.trailing_stop_percent = self._safe_get_decimal('trailing_stop_percent', '0.001')

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

    def calculate_sell_target_price(self, purchase_price: Decimal, quantity: "Decimal | None" = None, params: "Dict[str, Decimal] | None" = None) -> Decimal:
        """
        Calculates the target sell price using dynamic sell_rise_percentage.
        Handles cases where params might be None.
        NOTE: The 'quantity' parameter is included to match an expected signature in
        parts of the application, preventing a TypeError. It is not currently used
        in the calculation itself.
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

    def calculate_break_even_price(self, purchase_price: Decimal) -> Decimal:
        """
        Calculates the break-even price for a trade, accounting for both
        buy and sell commissions.
        """
        purchase_price = Decimal(purchase_price)
        one = Decimal('1')

        numerator = purchase_price * (one + self.commission_rate)
        denominator = one - self.commission_rate

        if denominator == 0:
            # Avoid division by zero, though commission_rate would have to be 100%
            return Decimal('inf')

        return numerator / denominator

    def calculate_realized_pnl(
        self,
        buy_price: Decimal,
        sell_price: Decimal,
        quantity_sold: Decimal,
        buy_commission_usd: Decimal,
        sell_commission_usd: Decimal,
        buy_quantity: Decimal
    ) -> Decimal:
        """
        Calculates the net realized profit or loss from a trade in USD,
        accounting for pro-rata buy commissions and sell commissions.
        """
        if any(v is None for v in [buy_price, sell_price, quantity_sold, buy_commission_usd, sell_commission_usd, buy_quantity]):
            logger.warning(f"Cannot calculate PnL with missing values.")
            return Decimal('0.0')

        try:
            buy_price = Decimal(buy_price)
            sell_price = Decimal(sell_price)
            quantity_sold = Decimal(quantity_sold)
            buy_commission_usd = Decimal(buy_commission_usd)
            sell_commission_usd = Decimal(sell_commission_usd)
            buy_quantity = Decimal(buy_quantity)

            # Calculate the gross profit from the price difference
            gross_pnl = (sell_price - buy_price) * quantity_sold

            # Calculate the portion of the original buy commission that applies to this partial sell
            buy_commission_prorated = (quantity_sold / buy_quantity) * buy_commission_usd if buy_quantity > 0 else Decimal('0')

            # Subtract both buy and sell commissions to get the net PnL
            net_pnl = gross_pnl - buy_commission_prorated - sell_commission_usd

            return net_pnl
        except (TypeError, InvalidOperation) as e:
            logger.error(f"Error calculating realized PnL: {e}", exc_info=True)
            return Decimal('0.0')

    def calculate_net_unrealized_pnl(self, entry_price: Decimal, current_price: Decimal, total_quantity: Decimal, buy_commission_usd: Decimal) -> Decimal:
        """
        Calculates the net unrealized PnL for an open position, accounting for buy
        commission and estimated sell commission.
        """
        try:
            entry_price = Decimal(entry_price)
            current_price = Decimal(current_price)
            total_quantity = Decimal(total_quantity)
            buy_commission_usd = Decimal(buy_commission_usd) if buy_commission_usd is not None else Decimal('0')

            # Gross PnL is the change in value of the asset
            gross_pnl = (current_price - entry_price) * total_quantity

            # Estimate the commission for selling the asset at the current price
            estimated_sell_value = current_price * total_quantity
            estimated_sell_commission = estimated_sell_value * self.commission_rate

            # Net PnL subtracts the already-paid buy commission and the estimated sell commission
            net_pnl = gross_pnl - buy_commission_usd - estimated_sell_commission

            return net_pnl
        except (TypeError, InvalidOperation) as e:
            logger.error(f"Error calculating unrealized PnL: {e}", exc_info=True)
            return Decimal('0.0')
