from jules_bot.utils.config_manager import ConfigManager
from jules_bot.utils.logger import logger
from decimal import Decimal, InvalidOperation

class DynamicParameters:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.parameters = {}
        # Initialize with fallback parameters to ensure it's never empty
        self.update_parameters(-1)

    def _safe_get_decimal(self, section: str, key: str, fallback: str) -> Decimal:
        """
        Safely gets a parameter from the config and converts it to a Decimal.
        Logs a critical error and uses the fallback if conversion fails.
        """
        value_str = self.config_manager.get(section, key, fallback=fallback)

        # This can happen if allow_no_value=True and a key is present without a value
        if value_str is None or not value_str.strip():
            logger.warning(f"Config value for '{key}' in section '{section}' is missing, empty, or just whitespace. Using fallback '{fallback}'.")
            return Decimal(fallback)

        try:
            return Decimal(value_str)
        except (InvalidOperation, TypeError) as e:
            logger.critical(
                f"Invalid config value for '{key}' in section '{section}'. Could not convert to Decimal. "
                f"Value was: '{value_str}'. Using fallback '{fallback}'. Error: {e}"
            )
            return Decimal(fallback)

    def update_parameters(self, regime: int):
        """
        Loads the strategy parameters for a given market regime.
        If the regime is -1 (undefined) or its config section is missing, it uses fallback values.
        """
        if regime == -1:
            # A safe, non-trading default
            logger.debug("Regime is -1 (undefined). Loading safe, non-trading parameters.")
            self.parameters = {
                'buy_dip_percentage': Decimal('1'),
                'sell_rise_percentage': Decimal('1'),
                'order_size_usd': Decimal('0'),
            }
            return

        section_name = f'REGIME_{regime}'
        # If the specific regime section doesn't exist, fall back to the default strategy rules.
        if not self.config_manager.has_section(section_name):
            logger.warning(f"Config section '{section_name}' not found. Falling back to 'STRATEGY_RULES'.")
            section_name = 'STRATEGY_RULES'

        # --- Load Parameters with Clear Fallbacks ---
        # For each parameter, we first try to get the specific value from the regime section.
        # If that fails, we have a clear order of fallbacks.

        # 1. Buy Dip Percentage
        # Fallback to a very high, "non-trading" value if not defined for the regime.
        # This prevents the bot from buying with an unexpected default value.
        buy_dip_fallback = '1.0' # A 100% dip, effectively disabling buys.
        buy_dip_percentage = self._safe_get_decimal(section_name, 'buy_dip_percentage', buy_dip_fallback)
        if buy_dip_percentage == Decimal(buy_dip_fallback):
            logger.warning(f"'{section_name}' is missing 'buy_dip_percentage'. Using a safe, non-trading fallback of {buy_dip_fallback}.")

        # 2. Sell Rise Percentage
        # Fallback to a default value if not defined for the regime.
        sell_rise_fallback = '0.01'  # 1%
        sell_rise_percentage = self._safe_get_decimal(section_name, 'sell_rise_percentage', sell_rise_fallback)
        if sell_rise_percentage == Decimal(sell_rise_fallback):
            logger.warning(f"'{section_name}' is missing 'sell_rise_percentage'. Using a default of {sell_rise_fallback}.")

        # 3. Order Size
        # Fallback to a default value from the main strategy section if not defined for the regime.
        order_size_fallback = self.config_manager.get('STRATEGY_RULES', 'base_usd_per_trade', '20.0')
        order_size_usd = self._safe_get_decimal(section_name, 'order_size_usd', order_size_fallback)


        self.parameters = {
            'buy_dip_percentage': buy_dip_percentage,
            'sell_rise_percentage': sell_rise_percentage,
            'order_size_usd': order_size_usd,
        }

    def get_param(self, param_name: str, default: Decimal = None) -> Decimal:
        """
        Returns the value of a specific parameter, with an optional default.
        """
        return self.parameters.get(param_name, default)
