import pytest
from unittest.mock import MagicMock
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.config_manager import ConfigManager

@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager for testing."""
    mock = MagicMock(spec=ConfigManager)

    # Mocking the get_section method to return different dictionaries
    # based on the section name requested.
    def get_section_side_effect(section_name):
        if section_name == 'STRATEGY_RULES':
            return {
                'max_capital_per_trade_percent': '0.02', # 2%
                'commission_rate': '0.001',
                'sell_factor': '0.9',
                'target_profit': '0.005',
                'max_open_positions': '20'
            }
        if section_name == 'TRADING_STRATEGY':
            return {
                'usd_per_trade': '100.0'
            }
        return {}

    mock.get_section.side_effect = get_section_side_effect
    return mock

def test_get_next_buy_amount_when_balance_is_high(mock_config_manager):
    """
    Test that the buy amount is capped by usd_per_trade when the
    available balance is high enough.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)
    # Available balance is $10,000. 2% of this is $200.
    # Since $100 (usd_per_trade) < $200, it should return $100.
    available_balance = 10000.0

    # Act
    buy_amount = strategy_rules.get_next_buy_amount(available_balance)

    # Assert
    assert buy_amount == 100.0

def test_get_next_buy_amount_when_balance_is_low(mock_config_manager):
    """
    Test that the buy amount is capped by the percentage of available
    balance when the balance is low.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)
    # Available balance is $1,000. 2% of this is $20.
    # Since $20 < $100 (usd_per_trade), it should return $20.
    available_balance = 1000.0

    # Act
    buy_amount = strategy_rules.get_next_buy_amount(available_balance)

    # Assert
    assert buy_amount == 20.0

def test_get_next_buy_amount_at_breakeven_point(mock_config_manager):
    """
    Test that the buy amount is correct when the two potential values are equal.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)
    # Available balance is $5,000. 2% of this is $100.
    # Since $100 (from balance) == $100 (usd_per_trade), it should return $100.
    available_balance = 5000.0

    # Act
    buy_amount = strategy_rules.get_next_buy_amount(available_balance)

    # Assert
    assert buy_amount == 100.0
