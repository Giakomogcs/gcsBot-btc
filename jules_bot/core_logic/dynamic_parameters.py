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

        # Correctly load sell_rise_percentage, falling back to target_profit within the same section.
        # This ensures regime-specific profit targets from config.ini are respected.
        # The fallback value for `sell_rise_percentage` is the value of `target_profit` from the same section.
        sell_rise_fallback = self.config_manager.get(section_name, 'target_profit', fallback='0.01')

        # Load parameters using the safe getter method for robustness
        self.parameters = {
            'buy_dip_percentage': self._safe_get_decimal(section_name, 'buy_dip_percentage', '0.02'),
            'sell_rise_percentage': self._safe_get_decimal(section_name, 'sell_rise_percentage', sell_rise_fallback),
            'order_size_usd': self._safe_get_decimal(section_name, 'order_size_usd', '20.0'),
        }

    def get_param(self, param_name: str, default: Decimal = None) -> Decimal:
        """
        Returns the value of a specific parameter, with an optional default.
        """
        return self.parameters.get(param_name, default)
