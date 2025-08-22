from decimal import Decimal, getcontext
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from enum import Enum, auto
from typing import Dict

# Set precision for Decimal calculations
getcontext().prec = 28

class OperatingMode(Enum):
    """Defines the strategic operating modes for the bot."""
    PRESERVATION = auto()
    ACCUMULATION = auto()
    AGGRESSIVE = auto()
    CORRECTION_ENTRY = auto()

class CapitalManager:
    """
    Manages capital allocation, determining buy amounts and strategy based on market conditions.
    """
    def __init__(self, config: ConfigManager, strategy_rules: StrategyRules):
        self.config = config
        self.strategy_rules = strategy_rules
        self.min_trade_size = Decimal(config.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))
        self.aggressive_buy_multiplier = Decimal(config.get('STRATEGY_RULES', 'aggressive_buy_multiplier', '2.0'))
        self.correction_entry_multiplier = Decimal(config.get('STRATEGY_RULES', 'correction_entry_multiplier', '2.5'))
        self.max_open_positions = int(config.get('STRATEGY_RULES', 'max_open_positions', '20'))
        self.use_dynamic_capital = config.getboolean('STRATEGY_RULES', 'use_dynamic_capital', fallback=False)
        self.use_percentage_sizing = config.getboolean('STRATEGY_RULES', 'use_percentage_based_sizing', fallback=False)
        self.order_size_percentage = Decimal(config.get('STRATEGY_RULES', 'order_size_free_cash_percentage', '0.1'))


    def get_buy_order_details(self, market_data: dict, open_positions: list, portfolio_value: Decimal, free_cash: Decimal, params: Dict[str, Decimal]) -> tuple[Decimal, str, str]:
        """
        Determines the operating mode and calculates the appropriate buy amount based on that mode,
        using dynamic parameters.
        """
        num_open_positions = len(open_positions)
        difficulty_factor = 0

        if not self.use_dynamic_capital and num_open_positions >= self.max_open_positions:
            return Decimal('0'), OperatingMode.PRESERVATION.name, f"Max open positions ({self.max_open_positions}) reached."

        difficulty_factor = 0
        if self.use_dynamic_capital:
            difficulty_factor = num_open_positions // 5

        should_buy, regime, reason = self.strategy_rules.evaluate_buy_signal(
            market_data, num_open_positions, difficulty_factor, params=params
        )

        if not should_buy:
            mode = OperatingMode.PRESERVATION
        elif regime == "uptrend" and num_open_positions < (self.max_open_positions / 4):
            mode = OperatingMode.AGGRESSIVE
        elif regime == "downtrend" and num_open_positions == 0:
            mode = OperatingMode.CORRECTION_ENTRY
        else:
            mode = OperatingMode.ACCUMULATION

        buy_amount = Decimal('0')
        # Determine the base buy amount
        if self.use_percentage_sizing:
            base_buy_amount = free_cash * self.order_size_percentage
            reason = f"Sizing based on {self.order_size_percentage:.2%} of free cash"
        else:
            base_buy_amount = params.get('order_size_usd', Decimal('20.0'))
            reason = "Using fixed order size from params"


        if mode == OperatingMode.ACCUMULATION:
            buy_amount = base_buy_amount
        elif mode == OperatingMode.AGGRESSIVE:
            buy_amount = base_buy_amount * self.aggressive_buy_multiplier
        elif mode == OperatingMode.CORRECTION_ENTRY:
            buy_amount = base_buy_amount * self.correction_entry_multiplier

        # 3. Validate the calculated buy amount
        if buy_amount > 0:
            if buy_amount > free_cash:
                reason = f"Insufficient funds for {mode.name} buy. Needed ${buy_amount:,.2f}, have ${free_cash:,.2f}."
                buy_amount = Decimal('0')
            elif buy_amount < self.min_trade_size:
                reason = f"{mode.name} buy amount ${buy_amount:,.2f} is below min size."
                buy_amount = Decimal('0')

        # Return final decision
        if buy_amount > 0:
            final_amount = buy_amount.quantize(Decimal("0.01"))
            return final_amount, mode.name, reason
        else:
            # If buy_amount is 0, the mode should reflect that we are not acting.
            final_mode = OperatingMode.PRESERVATION.name
            return Decimal('0'), final_mode, reason
