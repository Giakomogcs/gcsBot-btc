from decimal import Decimal, getcontext
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from enum import Enum, auto

# Set precision for Decimal calculations
getcontext().prec = 28

class OperatingMode(Enum):
    """Defines the strategic operating modes for the bot."""
    PRESERVATION = auto()      # Halts buying to preserve capital
    ACCUMULATION = auto()      # Standard, small-sized buys
    AGGRESSIVE = auto()        # Larger buys during confirmed uptrends
    CORRECTION_ENTRY = auto()  # A larger initial buy during a market dip

class CapitalManager:
    """
    Manages capital allocation, determining buy amounts and strategy based on market conditions.
    """
    def __init__(self, config: ConfigManager, strategy_rules: StrategyRules, strategy_params: dict):
        self.config = config
        self.strategy_rules = strategy_rules
        self.min_trade_size = Decimal(config.get('TRADING_STRATEGY', 'min_trade_size_usdt', fallback='10.0'))

        # Load dynamic strategy parameters
        self.base_usd_per_trade = Decimal(strategy_params.get('base_usd_per_trade', '20.0'))
        self.aggressive_buy_multiplier = Decimal(strategy_params.get('aggressive_buy_multiplier', '2.0'))
        self.correction_entry_multiplier = Decimal(strategy_params.get('correction_entry_multiplier', '2.5'))
        self.max_open_positions = int(strategy_params.get('max_open_positions', '20'))
        self.use_dynamic_capital = str(strategy_params.get('use_dynamic_capital', 'false')).lower() in ('true', '1', 't', 'y', 'yes', 'on')


    def get_buy_order_details(self, market_data: dict, open_positions: list, portfolio_value: Decimal, free_cash: Decimal) -> (Decimal, str, str):
        """
        Determines the operating mode and calculates the appropriate buy amount based on that mode.
        """
        num_open_positions = len(open_positions)
        difficulty_factor = 0

        # If dynamic capital is not enabled, check for the hard cap on positions.
        if not self.use_dynamic_capital and num_open_positions >= self.max_open_positions:
            return Decimal('0'), OperatingMode.PRESERVATION.name, f"Max open positions ({self.max_open_positions}) reached."

        # If dynamic capital is enabled, calculate a scaling factor.
        difficulty_factor = 0
        if self.use_dynamic_capital:
            difficulty_factor = num_open_positions // 5  # Increases by 1 for every 5 open positions

        should_buy, regime, reason = self.strategy_rules.evaluate_buy_signal(
            market_data, num_open_positions, difficulty_factor
        )

        # 1. Determine the Operating Mode
        if not should_buy:
            mode = OperatingMode.PRESERVATION
        elif regime == "uptrend" and num_open_positions < (self.max_open_positions / 4):
            mode = OperatingMode.AGGRESSIVE
        elif regime == "downtrend" and num_open_positions == 0:
            mode = OperatingMode.CORRECTION_ENTRY
        else:
            mode = OperatingMode.ACCUMULATION

        # 2. Calculate Buy Amount Based on Mode
        buy_amount = Decimal('0')
        if mode == OperatingMode.ACCUMULATION:
            buy_amount = self.base_usd_per_trade
        elif mode == OperatingMode.AGGRESSIVE:
            buy_amount = self.base_usd_per_trade * self.aggressive_buy_multiplier
        elif mode == OperatingMode.CORRECTION_ENTRY:
            buy_amount = self.base_usd_per_trade * self.correction_entry_multiplier

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
