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
                'max_open_positions': '20',
                'bbl_buy_tolerance_percent': '0.5' # 0.5% tolerance
            }
        return {}

    mock.get_section.side_effect = get_section_side_effect
    return mock

def test_evaluate_buy_signal_downtrend_with_tolerance(mock_config_manager):
    """
    Tests that a buy signal is generated in a downtrend when the price
    is within the bbl_buy_tolerance_percent.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)

    # --- Scenario 1: Price is just inside the tolerance (should trigger buy) ---
    market_data_inside_tolerance = {
        'close': 99.6,      # Current price is 0.4% above BBL
        'high': 100.0,
        'ema_100': 105.0,   # Price is below EMA100 (downtrend)
        'ema_20': 102.0,
        'bbl_20_2_0': 99.20318725 # Lower Bollinger Band
    }

    # Act
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data_inside_tolerance, 0)

    # Assert
    assert should_buy is True

    # --- Scenario 2: Price is just outside the tolerance (should NOT trigger buy) ---
    market_data_outside_tolerance = {
        'close': 99.8,      # Current price is 0.6% above BBL
        'high': 100.0,
        'ema_100': 105.0,   # Price is below EMA100 (downtrend)
        'ema_20': 102.0,
        'bbl_20_2_0': 99.20318725 # Lower Bollinger Band
    }

    # Act
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data_outside_tolerance, 0)

    # Assert
    assert should_buy is False

    # --- Scenario 3: Price is exactly at the BBL (should trigger buy) ---
    market_data_at_bbl = {
        'close': 99.20318725,
        'high': 100.0,
        'ema_100': 105.0,
        'ema_20': 102.0,
        'bbl_20_2_0': 99.20318725
    }

    # Act
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data_at_bbl, 0)

    # Assert
    assert should_buy is True

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
