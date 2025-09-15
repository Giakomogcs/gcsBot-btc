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
                'target_profit': Decimal('1'),
            }
            return

        section_name = f'REGIME_{regime}'
        
        if not self.config_manager.has_section(section_name):
            logger.warning(f"Config section '{section_name}' not found. Falling back to 'STRATEGY_RULES'.")
            section_name = 'STRATEGY_RULES'

        # --- Load Parameters ---
        # Get the default values from the main STRATEGY_RULES section first.
        default_buy_dip = self.config_manager.get('STRATEGY_RULES', 'buy_dip_percentage', '1.0')
        default_sell_rise = self.config_manager.get('STRATEGY_RULES', 'sell_rise_percentage', '0.01')
        default_order_size = self.config_manager.get('STRATEGY_RULES', 'base_usd_per_trade', '20.0')
        # The default for the trailing stop activation is 'trailing_stop_profit'
        default_target_profit = self.config_manager.get('STRATEGY_RULES', 'trailing_stop_profit', '0.02')

        # Now, load from the current section (which can be a REGIME or STRATEGY_RULES),
        # using the defaults from STRATEGY_RULES as fallbacks.
        buy_dip_percentage = self._safe_get_decimal(section_name, 'buy_dip_percentage', default_buy_dip)
        sell_rise_percentage = self._safe_get_decimal(section_name, 'sell_rise_percentage', default_sell_rise)
        order_size_usd = self._safe_get_decimal(section_name, 'order_size_usd', default_order_size)
        
        # The key is to load the 'target_profit' key from the regime section, but use the default
        # from 'trailing_stop_profit' as the fallback.
        target_profit = self._safe_get_decimal(section_name, 'target_profit', default_target_profit)

        self.parameters = {
            'buy_dip_percentage': buy_dip_percentage,
            'sell_rise_percentage': sell_rise_percentage,
            'order_size_usd': order_size_usd,
            'target_profit': target_profit,
        }

    def get_param(self, param_name: str, default: Decimal = None) -> Decimal:
        """
        Returns the value of a specific parameter, with an optional default.
        """
        return self.parameters.get(param_name, default)
