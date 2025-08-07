import pytest
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.config_manager import ConfigManager

@pytest.fixture
def config_manager():
    return ConfigManager()

def test_buy_trigger_for_few_positions(config_manager):
    strategy_rules = StrategyRules(config_manager)
    assert strategy_rules.get_next_buy_trigger(open_positions_count=4) == 0.01

def test_buy_trigger_for_many_positions(config_manager):
    strategy_rules = StrategyRules(config_manager)
    assert strategy_rules.get_next_buy_trigger(open_positions_count=15) == 0.02

def test_buy_amount_with_low_allocation(config_manager):
    strategy_rules = StrategyRules(config_manager)
    assert strategy_rules.get_next_buy_amount(capital_allocated_percent=0.2, base_amount=100.0) == 100.0

def test_buy_amount_with_high_allocation(config_manager):
    strategy_rules = StrategyRules(config_manager)
    assert strategy_rules.get_next_buy_amount(capital_allocated_percent=0.6, base_amount=100.0) == 60.0
