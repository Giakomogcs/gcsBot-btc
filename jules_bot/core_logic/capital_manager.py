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
        self.working_capital_percentage = self._safe_get_decimal('STRATEGY_RULES', 'working_capital_percentage', '0.5') # Default to 50%

        try:
            consecutive_buys_str = self.config_manager.get('STRATEGY_RULES', 'consecutive_buys_threshold', fallback='5')
            self.consecutive_buys_threshold = int(consecutive_buys_str)
        except (ValueError, TypeError) as e:
            logger.critical(f"Invalid value for 'consecutive_buys_threshold'. Using fallback '5'. Error: {e}")
            self.consecutive_buys_threshold = 5

        try:
            reset_hours_str = self.config_manager.get('STRATEGY_RULES', 'difficulty_reset_timeout_hours', fallback='2')
            self.difficulty_reset_timeout_hours = int(reset_hours_str)
        except (ValueError, TypeError) as e:
            logger.critical(f"Invalid value for 'difficulty_reset_timeout_hours'. Using fallback '2'. Error: {e}")
            self.difficulty_reset_timeout_hours = 2

        self.base_difficulty_percentage = self._safe_get_decimal('STRATEGY_RULES', 'base_difficulty_percentage', '0.005')
        self.per_buy_difficulty_increment = self._safe_get_decimal('STRATEGY_RULES', 'per_buy_difficulty_increment', '0.001')

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

    def get_buy_order_details(self, market_data: dict, market_regime: int, open_positions: list, portfolio_value: Decimal, free_cash: Decimal, params: Dict[str, Decimal], trade_history: list = None, force_buy_signal: bool = False, forced_reason: str = None) -> tuple[Decimal, str, str, str, Decimal]:
        """
        Determina o modo de operação e calcula o valor de compra apropriado com base nesse modo.
        Pode ser forçado a assumir que um sinal de compra está presente.
        Retorna o valor da compra, modo de operação, razão, o regime de sinal bruto e o fator de dificuldade usado.
        """
        num_open_positions = len(open_positions)
        difficulty_factor = self._calculate_difficulty_factor(open_positions)

        if not self.use_dynamic_capital and num_open_positions >= self.max_open_positions:
            return Decimal('0'), OperatingMode.PRESERVATION.name, f"Máximo de posições abertas ({self.max_open_positions}) atingido.", "PRESERVATION", difficulty_factor

        if force_buy_signal:
            # Força um sinal de compra, mas ainda respeita a lógica de alocação de capital do regime
            should_buy, signal_type, reason = True, "uptrend", forced_reason or "Sinal de compra forçado por reversão."
        else:
            # A avaliação agora depende do market_regime fornecido
            should_buy, signal_type, reason = self.strategy_rules.evaluate_buy_signal(
                market_data, market_regime, num_open_positions, difficulty_factor, params=params
            )

        if signal_type == "START_MONITORING":
            return Decimal('0'), OperatingMode.MONITORING.name, reason, signal_type, difficulty_factor

        if not should_buy:
            return Decimal('0'), OperatingMode.PRESERVATION.name, reason, "PRESERVATION", difficulty_factor

        # --- Determinar o modo de operação com base no REGIME DE MERCADO ---
        # "RANGING": 0, "UPTREND": 1, "HIGH_VOLATILITY": 2, "DOWNTREND": 3
        if market_regime == 1 and num_open_positions < (self.max_open_positions / 4): # UPTREND
            mode = OperatingMode.AGGRESSIVE
        elif market_regime == 3 and num_open_positions == 0: # DOWNTREND
            mode = OperatingMode.CORRECTION_ENTRY
        else: # RANGING ou outras condições
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
            return Decimal('0'), OperatingMode.PRESERVATION.name, f"Insufficient funds to place order of ${buy_amount:,.2f}", signal_type, difficulty_factor

        if buy_amount < self.min_trade_size:
            return Decimal('0'), OperatingMode.PRESERVATION.name, f"Amount ${buy_amount:,.2f} is below min trade size.", signal_type, difficulty_factor

        final_amount = buy_amount.quantize(Decimal("0.01"))
        return final_amount, mode.name, reason, signal_type, difficulty_factor

    def _calculate_difficulty_factor(self, open_positions: list) -> Decimal:
        """
        Calculates a progressive difficulty factor based on the number of open positions.
        This directly models the user's requirement that difficulty should increase
        as the number of unanswered 'buy' trades grows.

        - After a threshold of open positions, a base difficulty is applied.
        - For each subsequent open position, the difficulty increases.
        """
        if not self.use_dynamic_capital:
            return Decimal('0')

        # The number of "consecutive buys" is now simply the number of open positions.
        consecutive_buys = len(open_positions)

        if consecutive_buys < self.consecutive_buys_threshold:
            logger.info(f"No difficulty applied. Open positions ({consecutive_buys}) is below threshold ({self.consecutive_buys_threshold}).")
            return Decimal('0')

        # --- Difficulty Calculation ---
        # The first buy at or over the threshold triggers the base difficulty.
        # Each buy after that adds an increment.
        # Example: Threshold = 5.
        # 5 buys -> additional_buys = 0. Difficulty = base.
        # 6 buys -> additional_buys = 1. Difficulty = base + 1 * increment.

        buys_over_threshold = consecutive_buys - self.consecutive_buys_threshold

        base_difficulty = self.base_difficulty_percentage
        additional_difficulty = Decimal(buys_over_threshold) * self.per_buy_difficulty_increment
        total_difficulty = base_difficulty + additional_difficulty

        logger.info(
            f"Difficulty applied: {total_difficulty:.4%}. "
            f"Streak: {consecutive_buys} buys. "
            f"Threshold: {self.consecutive_buys_threshold}. "
            f"Base: {base_difficulty:.2%}. "
            f"Increment: {self.per_buy_difficulty_increment:.2%} x {buys_over_threshold} buys over threshold."
        )

        return total_difficulty

    def get_capital_allocation(self, open_positions: list, free_usdt_balance: Decimal, total_btc_balance: Decimal, current_btc_price: Decimal) -> dict:
        """
        Calculates a clearer breakdown of capital allocation based on live data.
        """
        # BTC in open positions is the sum of quantities from all open trades
        btc_in_open_positions = sum(Decimal(pos.quantity) for pos in open_positions)

        # Used Capital is the current market value of the BTC in those open positions
        used_capital_usd = btc_in_open_positions * current_btc_price

        # Free Capital is the available USDT in the wallet
        free_capital_usd = free_usdt_balance

        # Working Capital is the total capital actively managed by the bot
        working_capital_total_usd = used_capital_usd + free_capital_usd

        # Strategic Reserve is the value of any BTC held that is NOT in an open position
        strategic_reserve_btc = total_btc_balance - btc_in_open_positions
        strategic_reserve_usd = strategic_reserve_btc * current_btc_price

        return {
            "working_capital_total": working_capital_total_usd,
            "working_capital_used": used_capital_usd,
            "working_capital_free": free_capital_usd,
            "strategic_reserve": strategic_reserve_usd
        }
