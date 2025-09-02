import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from jules_bot.core_logic.capital_manager import CapitalManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.database.models import Trade

@pytest.fixture
def mock_config_manager():
    """Fixture for a mocked ConfigManager."""
    manager = MagicMock()
    manager.get.side_effect = lambda section, key, **kwargs: {
        ("STRATEGY_RULES", "working_capital_percentage"): "0.80", # 80% for easy math
    }.get((section, key), kwargs.get("fallback", "1")) # Default fallback for other values
    manager.getboolean.return_value = True
    return manager

@pytest.fixture
def mock_strategy_rules(mock_config_manager):
    """Fixture for a StrategyRules instance with a mocked config."""
    return StrategyRules(mock_config_manager)

@pytest.fixture
def capital_manager(mock_config_manager, mock_strategy_rules):
    """Fixture for a CapitalManager instance with mocked components."""
    # Patch _safe_get_decimal to avoid dependency on real config values during instantiation
    with MagicMock() as mock_safe_get:
        mock_safe_get.return_value = Decimal('10.0')
        CapitalManager._safe_get_decimal = mock_safe_get
        cm = CapitalManager(config_manager=mock_config_manager, strategy_rules=mock_strategy_rules)
        # Restore original method after instantiation
        del CapitalManager._safe_get_decimal
        return cm

def create_mock_position(usd_value):
    """Helper to create a mock trade object."""
    pos = Trade()
    pos.usd_value = Decimal(str(usd_value))
    return pos

def test_capital_allocation_logic(capital_manager):
    """
    Tests the get_capital_allocation function with a correct set of inputs.
    """
    # 1. Setup
    # Total portfolio value is $10,000
    portfolio_value = Decimal('10000')

    # We have three open positions with a total cost basis of $4,000
    open_positions = [
        create_mock_position('1000'),
        create_mock_position('2500'),
        create_mock_position('500')
    ]

    # Working capital percentage is mocked to be 80%
    capital_manager.working_capital_percentage = Decimal('0.80')

    # 2. Execute
    allocation = capital_manager.get_capital_allocation(portfolio_value, open_positions)

    # 3. Assert
    # Total working capital should be 80% of 10,000 = 8,000
    assert allocation['working_capital_total'] == Decimal('8000')

    # Used capital is the sum of the positions' cost basis = 1000 + 2500 + 500 = 4,000
    assert allocation['working_capital_used'] == Decimal('4000')

    # Free capital is working_capital_total - used_capital = 8000 - 4000 = 4,000
    assert allocation['working_capital_free'] == Decimal('4000')

    # Strategic reserve is the rest of the portfolio = 10000 - 8000 = 2,000
    assert allocation['strategic_reserve'] == Decimal('2000')

def test_capital_allocation_no_free_capital(capital_manager):
    """
    Tests that free capital is correctly calculated as 0 if used capital
    exceeds the working capital.
    """
    # 1. Setup
    portfolio_value = Decimal('10000')
    # Used capital ($9,000) is more than the working capital (80% of 10k = $8,000)
    open_positions = [
        create_mock_position('5000'),
        create_mock_position('4000')
    ]
    capital_manager.working_capital_percentage = Decimal('0.80')

    # 2. Execute
    allocation = capital_manager.get_capital_allocation(portfolio_value, open_positions)

    # 3. Assert
    assert allocation['working_capital_total'] == Decimal('8000')
    assert allocation['working_capital_used'] == Decimal('9000')
    # Free capital should be clamped to 0, not negative
    assert allocation['working_capital_free'] == Decimal('0')
    assert allocation['strategic_reserve'] == Decimal('2000')

def test_pnl_aggregation_logic(mock_strategy_rules):
    """
    Tests that the aggregation of realized and unrealized PnL is correct,
    simulating the logic from the StatusService.
    """
    # 1. Setup
    strategy = mock_strategy_rules
    strategy.commission_rate = Decimal('0.001') # 0.1%

    # Mock realized PnL from past trades
    mock_history = [
        MagicMock(order_type='sell', realized_pnl_usd=Decimal('10.50')),
        MagicMock(order_type='buy', realized_pnl_usd=None),
        MagicMock(order_type='sell', realized_pnl_usd=Decimal('-2.00')),
        MagicMock(order_type='sell', realized_pnl_usd=Decimal('5.50')),
    ]
    total_realized_pnl = sum(
        t.realized_pnl_usd for t in mock_history if t.order_type == 'sell'
    )
    # Expected realized PnL = 10.50 - 2.00 + 5.50 = 14.00
    assert total_realized_pnl == Decimal('14.00')

    # Mock open positions to calculate unrealized PnL
    # Position 1: In profit
    p1_unrealized = strategy.calculate_net_unrealized_pnl(
        entry_price=Decimal('100'),
        current_price=Decimal('120'),
        total_quantity=Decimal('1'),
        buy_commission_usd=Decimal('0.10')
    )
    # Gross: (120-100)*1 = 20. Estimated Sell Comm: 120*1*0.001 = 0.12.
    # Net = 20 - 0.10 (buy comm) - 0.12 (sell comm) = 19.78
    assert p1_unrealized == Decimal('19.78')

    # Position 2: In loss
    p2_unrealized = strategy.calculate_net_unrealized_pnl(
        entry_price=Decimal('200'),
        current_price=Decimal('180'),
        total_quantity=Decimal('2'),
        buy_commission_usd=Decimal('0.40')
    )
    # Gross: (180-200)*2 = -40. Estimated Sell Comm: 180*2*0.001 = 0.36
    # Net = -40 - 0.40 (buy comm) - 0.36 (sell comm) = -40.76
    assert p2_unrealized == Decimal('-40.76')

    mock_positions_status = [
        {'unrealized_pnl': p1_unrealized},
        {'unrealized_pnl': p2_unrealized}
    ]
    total_unrealized_pnl = sum(p['unrealized_pnl'] for p in mock_positions_status)
    # Expected unrealized PnL = 19.78 - 40.76 = -20.98
    assert total_unrealized_pnl == Decimal('-20.98')

    # 2. Execute final aggregation
    net_total_pnl = total_realized_pnl + total_unrealized_pnl

    # 3. Assert
    # Expected total PnL = 14.00 - 20.98 = -6.98
    assert net_total_pnl == Decimal('-6.98')
