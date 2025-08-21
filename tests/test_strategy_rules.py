import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.config_manager import ConfigManager

@pytest.fixture
def mock_config_manager_static():
    """Provides a mock ConfigManager for testing STATIC trade size mode."""
    mock = MagicMock(spec=ConfigManager)
    def get_section_side_effect(section_name):
        if section_name == 'STRATEGY_RULES':
            return {
                'trade_size_mode': 'STATIC',
                'static_trade_size_usd': '50.0',
                'commission_rate': '0.001',
                'sell_factor': '0.9',
                'target_profit': '0.005',
            }
        return {}
    mock.get_section.side_effect = get_section_side_effect
    return mock

@pytest.fixture
def mock_config_manager_dynamic():
    """Provides a mock ConfigManager for testing DYNAMIC trade size mode."""
    mock = MagicMock(spec=ConfigManager)
    def get_section_side_effect(section_name):
        if section_name == 'STRATEGY_RULES':
            return {
                'trade_size_mode': 'DYNAMIC',
                'dynamic_trade_size_percentage': '0.02', # 2%
                'max_trade_size_usd': '100.0',
                'commission_rate': '0.001',
                'sell_factor': '0.9',
                'target_profit': '0.005',
            }
        return {}
    mock.get_section.side_effect = get_section_side_effect
    return mock

def test_get_next_buy_amount_static_mode(mock_config_manager_static):
    """Test that the buy amount is the static amount in STATIC mode."""
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager_static)
    available_balance = Decimal("10000.0")

    # Act
    buy_amount = strategy_rules.get_next_buy_amount(available_balance)

    # Assert
    assert buy_amount == Decimal("50.0")

def test_get_next_buy_amount_dynamic_mode_capped_by_max(mock_config_manager_dynamic):
    """Test that the buy amount is capped by max_trade_size_usd in DYNAMIC mode."""
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager_dynamic)
    # 2% of $10,000 is $200, which is > max_trade_size_usd ($100)
    available_balance = Decimal("10000.0")

    # Act
    buy_amount = strategy_rules.get_next_buy_amount(available_balance)

    # Assert
    assert buy_amount == Decimal("100.0")

def test_get_next_buy_amount_dynamic_mode_capped_by_percentage(mock_config_manager_dynamic):
    """Test that the buy amount is based on percentage when it's less than max."""
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager_dynamic)
    # 2% of $1,000 is $20, which is < max_trade_size_usd ($100)
    available_balance = Decimal("1000.0")

    # Act
    buy_amount = strategy_rules.get_next_buy_amount(available_balance)

    # Assert
    assert buy_amount == Decimal("20.0")

def test_calculate_realized_pnl(mock_config_manager_static):
    """
    Tests the realized PnL calculation under different scenarios.
    This test is independent of the buy amount logic.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager_static)

    # --- Scenario 1: Profitable Trade ---
    buy_price_profit = Decimal("100.0")
    sell_price_profit = Decimal("110.0")
    quantity_sold = Decimal("1.0")
    # Expected: (110 * (1 - 0.001)) - (100 * (1 + 0.001)) = 109.89 - 100.1 = 9.79
    expected_pnl_profit = Decimal("9.79")

    # Act
    realized_pnl_profit = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_profit,
        sell_price=sell_price_profit,
        quantity_sold=quantity_sold
    )

    # Assert
    assert realized_pnl_profit == pytest.approx(expected_pnl_profit)

    # --- Scenario 2: Losing Trade ---
    buy_price_loss = Decimal("100.0")
    sell_price_loss = Decimal("90.0")
    # Expected: (90 * (1 - 0.001)) - (100 * (1 + 0.001)) = 89.91 - 100.1 = -10.19
    expected_pnl_loss = Decimal("-10.19")

    # Act
    realized_pnl_loss = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_loss,
        sell_price=sell_price_loss,
        quantity_sold=quantity_sold
    )

    # Assert
    assert realized_pnl_loss == pytest.approx(expected_pnl_loss)
