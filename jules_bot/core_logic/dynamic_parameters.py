from jules_bot.utils.config_manager import ConfigManager
from decimal import Decimal

class DynamicParameters:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.parameters = {}

    def update_parameters(self, regime: int):
        """
        Loads the strategy parameters for a given market regime.
        """
        section_name = f'REGIME_{regime}'
        if self.config_manager.has_section(section_name):
            regime_config = self.config_manager.get_section(section_name)
            self.parameters = {
                'target_profit': Decimal(regime_config.get('target_profit', '0.01')),
                'buy_dip_percentage': Decimal(regime_config.get('buy_dip_percentage', '0.02')),
                'sell_rise_percentage': Decimal(regime_config.get('sell_rise_percentage', '0.02')),
                'order_size_usd': Decimal(regime_config.get('order_size_usd', '20')),
            }
        else:
            # Fallback to default strategy rules if regime is not defined
            default_rules = self.config_manager.get_section('STRATEGY_RULES')
            self.parameters = {
                'target_profit': Decimal(default_rules.get('target_profit', '0.01')),
                'buy_dip_percentage': Decimal('0.02'), # Default value
                'sell_rise_percentage': Decimal('0.02'), # Default value
                'order_size_usd': Decimal(default_rules.get('base_usd_per_trade', '20.0')),
            }

    def get_param(self, param_name: str):
        """
        Returns the value of a specific parameter.
        """
        return self.parameters.get(param_name)
