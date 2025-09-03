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
                'sell_factor': '0.9',
                'target_profit': '0.005',
                'max_open_positions': '20'
            }
        return {}

    mock.get_section.side_effect = get_section_side_effect
    return mock

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
        quantity_sold=quantity_sold,
        buy_commission_usd=Decimal('0.1'),
        sell_commission_usd=Decimal('0.11'),
        buy_quantity=quantity_sold
    )

    # Assert
    assert float(realized_pnl_profit) == pytest.approx(float(expected_pnl_profit))

    # --- Scenario 2: Losing Trade ---
    buy_price_loss = Decimal("100.0")
    sell_price_loss = Decimal("90.0")
    expected_pnl_loss = Decimal("-10.19") # Corrected expected PnL

    # Act
    realized_pnl_loss = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_loss,
        sell_price=sell_price_loss,
        quantity_sold=quantity_sold,
        buy_commission_usd=Decimal('0.1'),
        sell_commission_usd=Decimal('0.09'),
        buy_quantity=quantity_sold
    )

    # Assert
    assert float(realized_pnl_loss) == pytest.approx(float(expected_pnl_loss))

    # --- Scenario 3: Break-even Trade (considering commissions) ---
    buy_price_breakeven = Decimal("100.0")
    sell_price_breakeven = Decimal("100.2002002")
    expected_pnl_breakeven = Decimal("-0.0002002") # Adjusted for new commission logic

    # Act
    realized_pnl_breakeven = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_breakeven,
        sell_price=sell_price_breakeven,
        quantity_sold=quantity_sold,
        buy_commission_usd=Decimal('0.1'),
        sell_commission_usd=Decimal('0.1002002'),
        buy_quantity=quantity_sold
    )

    # Assert
    assert float(realized_pnl_breakeven) == pytest.approx(0.0, abs=1e-6)

# This test is obsolete as the difficulty logic has been refactored and moved
# to the CapitalManager. The new logic is tested in test_capital_manager.py.
