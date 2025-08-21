import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.config_manager import ConfigManager

@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager for testing."""
    mock = MagicMock(spec=ConfigManager)

    # Mocking the get_section method to return the expected dictionary.
    def get_section_side_effect(section_name):
        if section_name == 'STRATEGY_RULES':
            return {
                'max_capital_per_trade_percent': '0.02', # 2%
                'base_usd_per_trade': '100.0', # This was missing
                'commission_rate': '0.001',
                'target_profit': '0.005',
                'max_open_positions': '20'
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

def test_calculate_net_unrealized_pnl(mock_config_manager):
    """
    Tests the unrealized PnL calculation. It should be based on the full quantity.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)
    entry_price = Decimal("100.0")
    current_price = Decimal("120.0")
    total_quantity = Decimal("2.0")

    # Act
    # This should internally call calculate_realized_pnl with the full quantity.
    # Expected PNL = ( (120 * (1 - 0.001)) - (100 * (1 + 0.001)) ) * 2
    # Expected PNL = ( (120 * 0.999) - (100 * 1.001) ) * 2
    # Expected PNL = ( 119.88 - 100.1 ) * 2
    # Expected PNL = 19.78 * 2 = 39.56
    unrealized_pnl = strategy_rules.calculate_net_unrealized_pnl(entry_price, current_price, total_quantity)

    # Assert
    assert float(unrealized_pnl) == pytest.approx(39.56)

def test_calculate_realized_pnl(mock_config_manager):
    """
    Tests the realized PnL calculation under different scenarios.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)

    # --- Scenario 1: Profitable Trade ---
    buy_price_profit = Decimal("100.0")
    sell_price_profit = Decimal("110.0")
    quantity_sold = Decimal("1.0")
    expected_pnl_profit = Decimal("9.79")

    # Act
    realized_pnl_profit = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_profit,
        sell_price=sell_price_profit,
        quantity_sold=quantity_sold
    )

    # Assert
    assert float(realized_pnl_profit) == pytest.approx(float(expected_pnl_profit))

    # --- Scenario 2: Losing Trade ---
    buy_price_loss = Decimal("100.0")
    sell_price_loss = Decimal("90.0")
    expected_pnl_loss = Decimal("-10.19")

    # Act
    realized_pnl_loss = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_loss,
        sell_price=sell_price_loss,
        quantity_sold=quantity_sold
    )

    # Assert
    assert float(realized_pnl_loss) == pytest.approx(float(expected_pnl_loss))

    # --- Scenario 3: Break-even Trade (considering commissions) ---
    buy_price_breakeven = Decimal("100.0")
    sell_price_breakeven = Decimal("100.2002002")

    # Act
    realized_pnl_breakeven = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_breakeven,
        sell_price=sell_price_breakeven,
        quantity_sold=quantity_sold
    )

    # Assert
    assert float(realized_pnl_breakeven) == pytest.approx(0.0, abs=1e-6)

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
