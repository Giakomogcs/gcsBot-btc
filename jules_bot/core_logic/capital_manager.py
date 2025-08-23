from decimal import Decimal, getcontext, InvalidOperation
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.utils.logger import logger
from jules_bot.core_logic.strategy_rules import StrategyRules
from enum import Enum, auto
from typing import Dict
import math

# Set precision for Decimal calculations
getcontext().prec = 28

class OperatingMode(Enum):
    """Defines the strategic operating modes for the bot."""
    PRESERVATION = auto()
    ACCUMULATION = auto()
    AGGRESSIVE = auto()
    CORRECTION_ENTRY = auto()
    MONITORING = auto()

class CapitalManager:
    """
    Manages capital allocation, determining buy amounts and strategy based on market conditions.
    """
    def __init__(self, config_manager: ConfigManager, strategy_rules: StrategyRules):
        self.config_manager = config_manager
        self.strategy_rules = strategy_rules

        # Load parameters using the safe getter
        self.min_trade_size = self._safe_get_decimal('TRADING_STRATEGY', 'min_trade_size_usdt', '10.0')
        self.max_trade_size = self._safe_get_decimal('TRADING_STRATEGY', 'max_trade_size_usdt', '10000.0')
        self.aggressive_buy_multiplier = self._safe_get_decimal('STRATEGY_RULES', 'aggressive_buy_multiplier', '2.0')
        self.correction_entry_multiplier = self._safe_get_decimal('STRATEGY_RULES', 'correction_entry_multiplier', '2.5')
        self.order_size_percentage = self._safe_get_decimal('STRATEGY_RULES', 'order_size_free_cash_percentage', '0.004')
        self.min_order_percentage = self._safe_get_decimal('STRATEGY_RULES', 'min_order_percentage', '0.004')
        self.max_order_percentage = self._safe_get_decimal('STRATEGY_RULES', 'max_order_percentage', '0.02')
        self.log_scaling_factor = self._safe_get_decimal('STRATEGY_RULES', 'log_scaling_factor', '0.002')

        # Load integer and boolean parameters
        try:
            max_pos_str = self.config_manager.get('STRATEGY_RULES', 'max_open_positions', fallback='20')
            self.max_open_positions = int(max_pos_str)
        except (ValueError, TypeError) as e:
            logger.critical(f"Invalid value for 'max_open_positions' in 'STRATEGY_RULES'. Using fallback '20'. Error: {e}")
            self.max_open_positions = 20

        self.use_dynamic_capital = self.config_manager.getboolean('STRATEGY_RULES', 'use_dynamic_capital', fallback=False)
        self.use_percentage_sizing = self.config_manager.getboolean('STRATEGY_RULES', 'use_percentage_based_sizing', fallback=False)
        self.use_formula_sizing = self.config_manager.getboolean('STRATEGY_RULES', 'use_formula_sizing', fallback=False)

    def _safe_get_decimal(self, section: str, key: str, fallback: str) -> Decimal:
        """Safely gets a parameter from config and converts it to Decimal."""
        value_str = self.config_manager.get(section, key, fallback=fallback)
        if value_str is None:
            logger.warning(f"Config value for '{key}' in section '{section}' is missing. Using fallback '{fallback}'.")
            return Decimal(fallback)
        try:
            return Decimal(value_str)
        except (InvalidOperation, TypeError) as e:
            logger.critical(
                f"Invalid config value for '{key}' in section '{section}'. Could not convert to Decimal. "
                f"Value was: '{value_str}'. Using fallback '{fallback}'. Error: {e}"
            )
            return Decimal(fallback)

    def _calculate_base_buy_amount(self, free_cash: Decimal, portfolio_value: Decimal, params: Dict[str, Decimal]) -> tuple[Decimal, str]:
        """
        Calculates the base buy amount based on the configured sizing strategy.
        It can use a simple percentage, a dynamic formula, or a fixed amount.
        """
        if self.use_formula_sizing:
            if portfolio_value > 1:
                # Ensure portfolio_value is positive for log10
                log_val = Decimal(math.log10(float(portfolio_value / 100))) if portfolio_value > 100 else 0
                percentage = self.min_order_percentage + log_val * self.log_scaling_factor
                percentage = max(self.min_order_percentage, min(percentage, self.max_order_percentage))
            else:
                percentage = self.min_order_percentage
            reason = f"Formula sizing: {percentage:.4%} of free cash"
            base_buy_amount = free_cash * percentage

        elif self.use_percentage_sizing:
            percentage = self.order_size_percentage
            reason = f"Simple sizing: {percentage:.2%} of free cash"
            base_buy_amount = free_cash * percentage
        else:
            # Safely get 'order_size_usd' from dynamic params
            base_buy_amount = params.get('order_size_usd', self.strategy_rules.base_usd_per_trade)
            reason = "Using fixed order size from params"
            return base_buy_amount, reason

        return max(base_buy_amount, self.min_trade_size), reason

    def get_buy_order_details(self, market_data: dict, open_positions: list, portfolio_value: Decimal, free_cash: Decimal, params: Dict[str, Decimal], force_buy_signal: bool = False, forced_reason: str = None) -> tuple[Decimal, str, str, str]:
        """
        Determines the operating mode and calculates the appropriate buy amount based on that mode.
        Can be forced to assume a buy signal is present.
        Returns the buy amount, operating mode, reason, and the raw signal regime.
        """
        num_open_positions = len(open_positions)

        if not self.use_dynamic_capital and num_open_positions >= self.max_open_positions:
            return Decimal('0'), OperatingMode.PRESERVATION.name, f"Max open positions ({self.max_open_positions}) reached.", "PRESERVATION"

        difficulty_factor = num_open_positions // 5 if self.use_dynamic_capital else 0

        if force_buy_signal:
            should_buy, regime, reason = True, "uptrend", forced_reason or "Buy signal forced by reversal."
        else:
            should_buy, regime, reason = self.strategy_rules.evaluate_buy_signal(
                market_data, num_open_positions, difficulty_factor, params=params
            )

        if regime == "START_MONITORING":
            return Decimal('0'), OperatingMode.MONITORING.name, reason, regime

        if not should_buy:
            return Decimal('0'), OperatingMode.PRESERVATION.name, reason, "PRESERVATION"

        # Determine operating mode based on signal
        if regime == "uptrend" and num_open_positions < (self.max_open_positions / 4):
            mode = OperatingMode.AGGRESSIVE
        elif regime == "downtrend" and num_open_positions == 0:
            mode = OperatingMode.CORRECTION_ENTRY
        else:
            mode = OperatingMode.ACCUMULATION

        buy_amount = Decimal('0')
        base_buy_amount, reason = self._calculate_base_buy_amount(free_cash, portfolio_value, params)

        if mode == OperatingMode.ACCUMULATION:
            buy_amount = base_buy_amount
        elif mode == OperatingMode.AGGRESSIVE:
            buy_amount = base_buy_amount * self.aggressive_buy_multiplier
        elif mode == OperatingMode.CORRECTION_ENTRY:
            buy_amount = base_buy_amount * self.correction_entry_multiplier

        if buy_amount > self.max_trade_size:
            buy_amount = self.max_trade_size
            reason += f", Capped at max trade size"

        if buy_amount > free_cash:
            buy_amount = free_cash
            reason += f", Capped at free cash"

        if buy_amount < self.min_trade_size:
            return Decimal('0'), OperatingMode.PRESERVATION.name, f"Amount ${buy_amount:,.2f} is below min trade size.", regime

        final_amount = buy_amount.quantize(Decimal("0.01"))
        return final_amount, mode.name, reason, regime
