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

def test_evaluate_buy_signal_with_difficulty_factor(mock_config_manager):
    """
    Tests that the buy signal becomes stricter with a higher difficulty factor.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)
    # This data ensures the logic enters the 'downtrend' path (close < ema_100)
    market_data = {
        'close': 100.1, 'high': 101, 'ema_100': 110, 'ema_20': 105,
        'bbl_20_2_0': 100.0
    }

    # --- Scenario 1: Difficulty 0, price is NOT below BBL -> No Signal ---
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=0)
    assert not should_buy

    # --- Scenario 2: Difficulty 0, price IS below BBL -> Signal ---
    market_data['close'] = 99.9
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=0)
    assert should_buy

    # --- Scenario 3: Difficulty 1 (0.5% stricter), price is NOT below adjusted BBL -> No Signal ---
    # Adjusted BBL = 100.0 * (1 - 0.005) = 99.5
    market_data['close'] = 99.6
    strategy_rules.difficulty_adjustment_factor = Decimal('0.005')
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=1)
    assert not should_buy

    # --- Scenario 4: Difficulty 1 (0.5% stricter), price IS below adjusted BBL -> Signal ---
    market_data['close'] = 99.4
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=1)
    assert should_buy

    # --- Scenario 5: Difficulty 2 (1% stricter), price is NOT below adjusted BBL -> No Signal ---
    # Adjusted BBL = 100.0 * (1 - 0.01) = 99.0
    market_data['close'] = 99.1
    strategy_rules.difficulty_adjustment_factor = Decimal('0.005')
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=2)
    assert not should_buy
