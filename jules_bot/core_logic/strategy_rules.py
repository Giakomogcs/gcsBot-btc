from decimal import Decimal, getcontext, InvalidOperation
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.utils.logger import logger
from typing import Dict, Tuple, Optional

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
        
        # --- Difficulty Adjustment ---
        self.difficulty_adjustment_factor = self._safe_get_decimal('difficulty_adjustment_factor', '0.006')
        self.consecutive_buys_threshold = self.config_manager.getint(self.section_name, 'consecutive_buys_threshold', fallback=2)
        self.difficulty_reset_timeout_hours = self.config_manager.getint(self.section_name, 'difficulty_reset_timeout_hours', fallback=2)

        # --- Standard & Dynamic Trailing Stop ---
        self.trailing_stop_profit = self._safe_get_decimal('trailing_stop_profit', '0.015') # Profit % to activate trailing stop
        self.fixed_trail_percentage = self._safe_get_decimal('dynamic_trail_percentage', '0.02')  # Legacy key for fixed trail
        self.use_dynamic_trailing_stop = self.config_manager.getboolean(self.section_name, 'use_dynamic_trailing_stop', fallback=False)
        self.dynamic_trail_min_pct = self._safe_get_decimal('dynamic_trail_min_pct', '0.01')      # e.g., 1%
        self.dynamic_trail_max_pct = self._safe_get_decimal('dynamic_trail_max_pct', '0.05')      # e.g., 5%
        self.dynamic_trail_profit_scaling = self._safe_get_decimal('dynamic_trail_profit_scaling', '0.1') # Determines how fast the trail widens

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

    def _calculate_dynamic_trail_percentage(self, highest_profit_pnl: Decimal, entry_price: Decimal, total_quantity: Decimal) -> Decimal:
        """
        Calculates a dynamic trail percentage based on the highest unrealized profit percentage.
        The trail widens as the profit percentage increases.
        """
        if entry_price <= 0 or total_quantity <= 0:
            return self.dynamic_trail_min_pct

        # Calculate the initial investment to determine profit percentage
        initial_investment = entry_price * total_quantity
        if initial_investment <= 0:
            return self.dynamic_trail_min_pct

        # Calculate profit as a percentage of the initial investment
        profit_percentage = highest_profit_pnl / initial_investment

        # The trail percentage increases with the profit percentage, controlled by a scaling factor.
        # Example: 20% profit (0.20) * scaling (0.1) = 2% trail.
        calculated_trail = self.dynamic_trail_min_pct + (profit_percentage * self.dynamic_trail_profit_scaling)

        # Clamp the trail between the configured min and max values.
        final_trail = max(self.dynamic_trail_min_pct, min(calculated_trail, self.dynamic_trail_max_pct))
        
        return final_trail

    def evaluate_buy_signal(self, market_data: dict, open_positions_count: int, difficulty_factor: Decimal = None, params: Dict[str, Decimal] = None) -> tuple[bool, str, str]:
        """
        Evaluates if a buy signal is present, providing detailed reasons for no signal.
        Uses dynamic parameters for buy dip percentage.
        """
        if difficulty_factor is None:
            difficulty_factor = Decimal('0')

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
        
        difficulty_multiplier = Decimal('1') - (difficulty_factor * self.difficulty_adjustment_factor)
        adjusted_bbl = Decimal(str(bbl)) * difficulty_multiplier

        base_buy_dip = params.get('buy_dip_percentage', Decimal('0.02')) if params else Decimal('0.02')
        # Apply difficulty factor to the buy dip percentage
        adjusted_buy_dip_percentage = base_buy_dip + (difficulty_factor * self.difficulty_adjustment_factor)
        price_dip_target = ema_20 * (Decimal('1') - adjusted_buy_dip_percentage)

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
                # DOWNTREND: Use the same dip-buying logic as uptrend.
                if current_price <= price_dip_target:
                    return True, "downtrend", f"Aggressive first entry (dip buy at {adjusted_buy_dip_percentage:.2%})"
                else:
                    reason = f"Buy target: ${price_dip_target:,.2f}. Price is too high."
        else:
            # Logic for when there are existing open positions
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
                # DOWNTREND: Use the same dip-buying logic as uptrend.
                if current_price <= price_dip_target:
                    return True, "downtrend", f"Downtrend dip buy signal on existing position at {adjusted_buy_dip_percentage:.2%}"
                else:
                    reason = f"Buy target: ${price_dip_target:,.2f}. Price is too high."
        
        return False, "unknown", reason or "No signal"

    def calculate_sell_target_price(self, purchase_price: Decimal, quantity: "Decimal | None" = None, params: "Dict[str, Decimal] | None" = None) -> Decimal:
        purchase_price = Decimal(purchase_price)
        if params is None:
            params = {}
        sell_rise_percentage = params.get('sell_rise_percentage', Decimal('0.01'))
        one = Decimal('1')
        numerator = purchase_price * (one + self.commission_rate)
        denominator = one - self.commission_rate
        if denominator == 0:
            return Decimal('inf')
        break_even_price = numerator / denominator
        sell_target_price = break_even_price * (one + sell_rise_percentage)
        return sell_target_price

    def calculate_break_even_price(self, purchase_price: Decimal) -> Decimal:
        purchase_price = Decimal(purchase_price)
        one = Decimal('1')
        numerator = purchase_price * (one + self.commission_rate)
        denominator = one - self.commission_rate
        if denominator == 0:
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
        Calculates the net realized profit or loss for a transaction.
        It correctly prorates the original buy commission for partial sells.
        """
        if any(v is None for v in [buy_price, sell_price, quantity_sold, buy_commission_usd, sell_commission_usd, buy_quantity]):
            logger.warning("Cannot calculate PnL with missing values.")
            return Decimal('0.0')
        try:
            buy_price = Decimal(buy_price)
            sell_price = Decimal(sell_price)
            quantity_sold = Decimal(quantity_sold)
            buy_commission_usd = Decimal(buy_commission_usd)
            sell_commission_usd = Decimal(sell_commission_usd)
            buy_quantity = Decimal(buy_quantity)

            # Prorate the buy commission for the quantity being sold.
            # This is crucial for partial sell scenarios.
            if buy_quantity > 0:
                prorated_buy_commission = (buy_commission_usd * quantity_sold) / buy_quantity
            else:
                # Avoid division by zero if buy_quantity is invalid, though this shouldn't happen.
                prorated_buy_commission = Decimal('0')

            gross_pnl = (sell_price - buy_price) * quantity_sold
            net_pnl = gross_pnl - prorated_buy_commission - sell_commission_usd
            return net_pnl
        except (TypeError, InvalidOperation) as e:
            logger.error(f"Error calculating realized PnL: {e}", exc_info=True)
            return Decimal('0.0')

    def calculate_net_unrealized_pnl(self, entry_price: Decimal, current_price: Decimal, total_quantity: Decimal, buy_commission_usd: Decimal) -> Decimal:
        try:
            entry_price = Decimal(entry_price)
            current_price = Decimal(current_price)
            total_quantity = Decimal(total_quantity)
            buy_commission_usd = Decimal(buy_commission_usd) if buy_commission_usd is not None else Decimal('0')
            gross_pnl = (current_price - entry_price) * total_quantity
            estimated_sell_value = current_price * total_quantity
            estimated_sell_commission = estimated_sell_value * self.commission_rate
            net_pnl = gross_pnl - buy_commission_usd - estimated_sell_commission
            return net_pnl
        except (TypeError, InvalidOperation) as e:
            logger.error(f"Error calculating unrealized PnL: {e}", exc_info=True)
            return Decimal('0.0')

    def evaluate_smart_trailing_stop(
        self,
        position: Dict[str, any],
        net_unrealized_pnl: Decimal,
        params: Dict[str, Decimal] = None
    ) -> Tuple[str, str, Optional[Decimal]]:
        is_active = position.get('is_smart_trailing_active', False)
        decision = "HOLD"
        reason = "No action required."
        new_trail_percentage = None

        if params is None:
            params = {}

        activation_profit_target = params.get('target_profit', self.trailing_stop_profit)

        if not is_active:
            if net_unrealized_pnl >= activation_profit_target:
                decision = "ACTIVATE"
                reason = f"Trailing stop activated. PnL (${net_unrealized_pnl:.2f}) reached activation target (${activation_profit_target:.2f})."
            return decision, reason, new_trail_percentage

        # --- From here, the trailing stop is active ---

        stored_highest_profit = Decimal(str(position.get('smart_trailing_highest_profit', '0')))
        current_trail_pct = Decimal(str(position.get('current_trail_percentage') or self.fixed_trail_percentage))

        # The true peak is the highest value seen so far. This ensures the peak never decreases.
        highest_profit = max(stored_highest_profit, net_unrealized_pnl)

        # If PnL drops below zero, deactivate.
        if net_unrealized_pnl < 0:
            decision = "DEACTIVATE"
            reason = f"Trailing stop deactivated. Position became unprofitable (PnL: {net_unrealized_pnl:.2f})."
            return decision, reason, new_trail_percentage

        # --- Sell Trigger Logic (runs every time) ---
        trail_percentage_to_use = current_trail_pct

        # Check for a new peak first. If a new peak is found, we might update the dynamic trail.
        # The decision to "UPDATE_PEAK" will be made, but we don't return early.
        if highest_profit > stored_highest_profit:
            # Use a threshold to prevent tiny, frequent DB updates.
            if stored_highest_profit <= 0 or (highest_profit - stored_highest_profit) / stored_highest_profit > Decimal('0.005'):
                decision = "UPDATE_PEAK"
                reason = f"New profit peak for trailing stop: {highest_profit:.2f}."
                if self.use_dynamic_trailing_stop:
                    calculated_trail = self._calculate_dynamic_trail_percentage(
                        highest_profit_pnl=highest_profit,
                        entry_price=Decimal(str(position['price'])),
                        total_quantity=Decimal(str(position['quantity']))
                    )
                    if calculated_trail > current_trail_pct:
                        new_trail_percentage = calculated_trail
                        trail_percentage_to_use = new_trail_percentage # Use the new trail for this cycle's sell calc
                        reason += f" Trail updated to {new_trail_percentage:.2%}"

        # Now, calculate the sell trigger based on the absolute latest peak.
        stop_profit_level = highest_profit * (Decimal('1') - trail_percentage_to_use)

        if net_unrealized_pnl <= stop_profit_level:
            decision = "SELL" # A sell decision overrides an update decision.
            reason = (
                f"Trailing stop sell triggered. "
                f"PnL (${net_unrealized_pnl:,.2f}) <= Target (${stop_profit_level:,.2f}). "
                f"Peak: ${highest_profit:.2f}, Trail: {trail_percentage_to_use:.2%}"
            )
        elif decision != "UPDATE_PEAK": # Don't overwrite the "UPDATE_PEAK" reason.
            reason = (
                f"Monitoring active trail. "
                f"PnL: ${net_unrealized_pnl:,.2f}, "
                f"Peak: ${highest_profit:.2f}, "
                f"Stop Target: ${stop_profit_level:,.2f}, "
                f"Trail: {trail_percentage_to_use:.2%}"
            )
        
        return decision, reason, new_trail_percentage
