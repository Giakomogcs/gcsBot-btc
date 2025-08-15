import pytest
from unittest.mock import MagicMock
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.config_manager import ConfigManager

@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager for testing DCOM rules."""
    mock = MagicMock(spec=ConfigManager)

    def get_section_side_effect(section_name):
        if section_name == 'STRATEGY_RULES':
            return {
                # Sell logic
                'commission_rate': '0.001',
                'sell_factor': '0.9',
                'target_profit': '0.002',
                # DCOM
                'working_capital_percent': '0.60',
                'ema_anchor_period': '200',
                'aggressive_spacing_percent': '0.02',
                'conservative_spacing_percent': '0.04',
                'initial_order_size_usd': '10.00',
                'order_progression_factor': '1.5'
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
    commission_rate = 0.001 # 0.1%

    # --- Scenario 1: Profitable Trade ---
    buy_price_profit = 100.0
    sell_price_profit = 110.0
    quantity_sold = 1.0

    # Calculation according to the formula:
    # Net Sales Revenue = (110 * (1 - 0.001)) = 109.89
    # Proportional Purchase Cost = (100 * (1 + 0.001)) = 100.10
    # Realized Profit = (109.89 - 100.10) * 1.0 = 9.79
    expected_pnl_profit = 9.79

    # Act
    realized_pnl_profit = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_profit,
        sell_price=sell_price_profit,
        quantity_sold=quantity_sold
    )

    # Assert
    assert realized_pnl_profit == pytest.approx(expected_pnl_profit)

    # --- Scenario 2: Losing Trade ---
    buy_price_loss = 100.0
    sell_price_loss = 90.0

    # Calculation:
    # Net Sales Revenue = (90 * (1 - 0.001)) = 89.91
    # Proportional Purchase Cost = (100 * (1 + 0.001)) = 100.10
    # Realized Loss = (89.91 - 100.10) * 1.0 = -10.19
    expected_pnl_loss = -10.19

    # Act
    realized_pnl_loss = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_loss,
        sell_price=sell_price_loss,
        quantity_sold=quantity_sold
    )

    # Assert
    assert realized_pnl_loss == pytest.approx(expected_pnl_loss)

    # --- Scenario 3: Break-even Trade (considering commissions) ---
    buy_price_breakeven = 100.0
    # P_sell * (1 - 0.001) = 100 * (1 + 0.001) => P_sell = 100.1 / 0.999 = 100.2002
    sell_price_breakeven = 100.2002002

    # Act
    realized_pnl_breakeven = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_breakeven,
        sell_price=sell_price_breakeven,
        quantity_sold=quantity_sold
    )

    # Assert
    assert realized_pnl_breakeven == pytest.approx(0.0, abs=1e-6)

# --- DCOM: get_next_buy_amount Tests ---

def test_dcom_get_next_buy_amount_initial_buy(mock_config_manager):
    """Test initial buy amount calculation with no open positions."""
    strategy_rules = StrategyRules(mock_config_manager)
    # Total Equity = 1000 (cash) + 0 (positions) = 1000
    # WC = 1000 * 0.6 = 600
    # Remaining BP = 600 - 0 = 600
    # Next order size = 10 * 1.5^0 = 10
    # Since 10 <= 600, it should return 10.
    amount = strategy_rules.get_next_buy_amount(cash_balance=1000, open_positions_value=0, num_open_positions=0)
    assert amount == 10.0

def test_dcom_get_next_buy_amount_progressive_sizing(mock_config_manager):
    """Test progressive order sizing with a few open positions."""
    strategy_rules = StrategyRules(mock_config_manager)
    # Total Equity = 850 (cash) + 150 (positions) = 1000
    # WC = 1000 * 0.6 = 600
    # Remaining BP = 600 - 150 = 450
    # Next order size = 10 * 1.5^2 = 22.5
    # Since 22.5 <= 450, it should return 22.5.
    amount = strategy_rules.get_next_buy_amount(cash_balance=850, open_positions_value=150, num_open_positions=2)
    assert amount == 22.5

def test_dcom_get_next_buy_amount_insufficient_power(mock_config_manager):
    """Test that buy amount is 0 when remaining buying power is insufficient."""
    strategy_rules = StrategyRules(mock_config_manager)
    # Total Equity = 400 (cash) + 580 (positions) = 980
    # WC = 980 * 0.6 = 588
    # Remaining BP = 588 - 580 = 8
    # Next order size = 10 * 1.5^3 = 33.75
    # Since 33.75 > 8, it should return 0.
    amount = strategy_rules.get_next_buy_amount(cash_balance=400, open_positions_value=580, num_open_positions=3)
    assert amount == 0

# --- DCOM: evaluate_buy_signal Tests ---

def test_dcom_evaluate_buy_no_positions(mock_config_manager):
    """Test that buy signal is always true when there are no open positions."""
    strategy_rules = StrategyRules(mock_config_manager)
    market_data = {'close': 50000, 'ema_200': 51000} # Conservative mode
    should_buy, mode, reason = strategy_rules.evaluate_buy_signal(market_data, open_positions=[], last_buy_price=None)
    assert should_buy is True
    assert reason == "Ready for initial position"

def test_dcom_evaluate_buy_aggressive_mode_pass(mock_config_manager):
    """Test buy signal in Aggressive mode when price drops enough."""
    strategy_rules = StrategyRules(mock_config_manager)
    # Aggressive mode: price > ema_200
    # Spacing needed: 2%
    market_data = {'close': 52000, 'ema_200': 50000}
    last_buy_price = 53100 # 52000 is a 2.07% drop from 53100
    should_buy, mode, reason = strategy_rules.evaluate_buy_signal(market_data, open_positions=[{}], last_buy_price=last_buy_price)
    assert should_buy is True
    assert mode == "Aggressive"
    assert "Price dropped >2.0%" in reason

def test_dcom_evaluate_buy_conservative_mode_fail(mock_config_manager):
    """Test buy signal in Conservative mode when price has not dropped enough."""
    strategy_rules = StrategyRules(mock_config_manager)
    # Conservative mode: price < ema_200
    # Spacing needed: 4%
    market_data = {'close': 48000, 'ema_200': 50000}
    last_buy_price = 49000 # 48000 is only a 2% drop from 49000
    should_buy, mode, reason = strategy_rules.evaluate_buy_signal(market_data, open_positions=[{}], last_buy_price=last_buy_price)
    assert should_buy is False
    assert mode == "Conservative"
    assert "Price has not dropped >4.0%" in reason
