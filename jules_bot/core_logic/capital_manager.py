from decimal import Decimal, getcontext
from jules_bot.utils.config_manager import ConfigManager
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
    def __init__(self, config: ConfigManager, strategy_rules: StrategyRules):
        self.config = config
        self.strategy_rules = strategy_rules
        self.min_trade_size = Decimal(config.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))
        self.max_trade_size = Decimal(config.get('TRADING_STRATEGY', 'max_trade_size_usdt', fallback='10000.0'))
        self.aggressive_buy_multiplier = Decimal(config.get('STRATEGY_RULES', 'aggressive_buy_multiplier', '2.0'))
        self.correction_entry_multiplier = Decimal(config.get('STRATEGY_RULES', 'correction_entry_multiplier', '2.5'))
        self.max_open_positions = int(config.get('STRATEGY_RULES', 'max_open_positions', '20'))
        self.use_dynamic_capital = config.getboolean('STRATEGY_RULES', 'use_dynamic_capital', fallback=False)

        # Sizing strategy flags
        self.use_percentage_sizing = config.getboolean('STRATEGY_RULES', 'use_percentage_based_sizing', fallback=False)
        self.use_formula_sizing = config.getboolean('STRATEGY_RULES', 'use_formula_sizing', fallback=False)

        # Parameters for different sizing strategies
        self.order_size_percentage = Decimal(config.get('STRATEGY_RULES', 'order_size_free_cash_percentage', '0.004'))
        self.min_order_percentage = Decimal(config.get('STRATEGY_RULES', 'min_order_percentage', '0.004'))
        self.max_order_percentage = Decimal(config.get('STRATEGY_RULES', 'max_order_percentage', '0.02'))
        self.log_scaling_factor = Decimal(config.get('STRATEGY_RULES', 'log_scaling_factor', '0.002'))

    def _calculate_base_buy_amount(self, free_cash: Decimal, portfolio_value: Decimal, params: Dict[str, Decimal]) -> tuple[Decimal, str]:
        """
        Calculates the base buy amount based on the configured sizing strategy.
        It can use a simple percentage, a dynamic formula, or a fixed amount.
        """
        if self.use_formula_sizing:
            if portfolio_value > 1:
                log_val = Decimal(math.log10(float(portfolio_value / 100)))
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
            base_buy_amount = params.get('order_size_usd', Decimal('20.0'))
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
        difficulty_factor = 0

        if not self.use_dynamic_capital and num_open_positions >= self.max_open_positions:
            return Decimal('0'), OperatingMode.PRESERVATION.name, f"Max open positions ({self.max_open_positions}) reached.", "PRESERVATION"

        difficulty_factor = 0
        if self.use_dynamic_capital:
            difficulty_factor = num_open_positions // 5

        if force_buy_signal:
            should_buy, regime, reason = True, "uptrend", forced_reason or "Buy signal forced by reversal."
        else:
            should_buy, regime, reason = self.strategy_rules.evaluate_buy_signal(
                market_data, num_open_positions, difficulty_factor, params=params
            )

        if regime == "START_MONITORING":
            return Decimal('0'), OperatingMode.MONITORING.name, reason, regime

        if not should_buy:
            mode = OperatingMode.PRESERVATION
        elif regime == "uptrend" and num_open_positions < (self.max_open_positions / 4):
            mode = OperatingMode.AGGRESSIVE
        elif regime == "downtrend" and num_open_positions == 0:
            mode = OperatingMode.CORRECTION_ENTRY
        else:
            mode = OperatingMode.ACCUMULATION

        buy_amount = Decimal('0')
        if should_buy:
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
                buy_amount = Decimal('0')
                reason = f"Amount below min trade size"

        if buy_amount > 0:
            final_amount = buy_amount.quantize(Decimal("0.01"))
            return final_amount, mode.name, reason, regime
        else:
            final_mode = OperatingMode.PRESERVATION.name
            return Decimal('0'), final_mode, reason, regime
