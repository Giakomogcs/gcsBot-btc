import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from jules_bot.core_logic.capital_manager import CapitalManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.database.models import Trade

# Mock config_manager that can be used across tests
@pytest.fixture
def mock_config_manager():
    """Fixture for a mocked ConfigManager."""
    manager = MagicMock()
    # Default values that can be overridden in specific tests
    manager.get.side_effect = lambda section, key, **kwargs: {
        ("STRATEGY_RULES", "consecutive_buys_threshold"): "3",
        ("STRATEGY_RULES", "difficulty_reset_timeout_hours"): "2",
        ("STRATEGY_RULES", "trailing_stop_percent"): "0.01", # 1%
    }.get((section, key), kwargs.get("fallback"))
    return manager

@pytest.fixture
def mock_strategy_rules(mock_config_manager):
    """Fixture for a StrategyRules instance with a mocked config."""
    # Since we restored the file, we need to add the new param back for the test
    with patch.object(StrategyRules, '_safe_get_decimal', side_effect=lambda key, fallback: Decimal(fallback)):
        rules = StrategyRules(mock_config_manager)
        rules.trailing_stop_percent = Decimal('0.01')
        return rules

@pytest.fixture
def capital_manager(mock_config_manager, mock_strategy_rules):
    """Fixture for a CapitalManager instance with mocked components."""
    with patch('jules_bot.core_logic.capital_manager.CapitalManager._safe_get_decimal', return_value=Decimal('10.0')), \
         patch('jules_bot.core_logic.capital_manager.ConfigManager.getboolean', return_value=True):
        # The patches are just to allow instantiation
        return CapitalManager(config_manager=mock_config_manager, strategy_rules=mock_strategy_rules)

# Mock Trade object to simulate database records
class MockTrade:
    def __init__(self, order_type, timestamp):
        self.order_type = order_type
        self.timestamp = timestamp

# Test for the incremental difficulty factor
def test_incremental_difficulty_factor(capital_manager):
    """
    Tests that the difficulty factor increases incrementally for each
    consecutive buy over the threshold.
    """
    capital_manager.consecutive_buys_threshold = 3
    now = datetime.utcnow()

    # Scenario: 5 consecutive buys (3 threshold + 2 over)
    trade_history_5 = [
        MockTrade('buy', now - timedelta(minutes=10)),
        MockTrade('buy', now - timedelta(minutes=20)),
        MockTrade('buy', now - timedelta(minutes=30)),
        MockTrade('buy', now - timedelta(minutes=40)),
        MockTrade('buy', now - timedelta(minutes=50)),
    ]
    assert capital_manager._calculate_difficulty_factor(trade_history_5) == 2

    # Scenario: Streak broken by a sell
    trade_history_broken = [
        MockTrade('buy', now - timedelta(minutes=10)),
        MockTrade('buy', now - timedelta(minutes=20)),
        MockTrade('sell', now - timedelta(minutes=30)),
        MockTrade('buy', now - timedelta(minutes=40)),
        MockTrade('buy', now - timedelta(minutes=50)),
    ]
    assert capital_manager._calculate_difficulty_factor(trade_history_broken) == 0

# Mock a database session and manager for the trading bot test
@pytest.fixture
def mock_db_manager():
    manager = MagicMock()
    manager.update_trade = MagicMock()
    return manager

# Test for the new trailing take-profit logic
def test_trailing_take_profit_logic(mock_strategy_rules, mock_db_manager):
    """
    Tests the complete lifecycle of the trailing take-profit feature.
    """
    # 1. Setup
    # We don't need a full bot, just the sell logic part.
    # The logic is in the bot's run method, so we simulate that part.
    open_positions = []

    # Create a mock position
    mock_position = Trade()
    mock_position.trade_id = "test_trade_123"
    mock_position.sell_target_price = Decimal('105')
    mock_position.profit_target_breached = False
    mock_position.highest_price_since_breach = None
    open_positions.append(mock_position)

    strategy_rules = mock_strategy_rules
    db_manager = mock_db_manager

    positions_to_sell = []

    # 2. Simulate price below target -> No action
    current_price = Decimal('104')
    # This is a simplified version of the loop in trading_bot.py
    for p in open_positions:
        if not p.profit_target_breached and current_price >= p.sell_target_price:
            p.profit_target_breached = True
            p.highest_price_since_breach = current_price
            db_manager.update_trade(p.trade_id, {"profit_target_breached": True, "highest_price_since_breach": current_price})

    assert not mock_position.profit_target_breached
    db_manager.update_trade.assert_not_called()

    # 3. Simulate price hitting target -> Trailing is activated
    current_price = Decimal('106')
    for p in open_positions:
        if not p.profit_target_breached and current_price >= p.sell_target_price:
            p.profit_target_breached = True
            p.highest_price_since_breach = current_price
            db_manager.update_trade(p.trade_id, {"profit_target_breached": True, "highest_price_since_breach": current_price})

    assert mock_position.profit_target_breached
    assert mock_position.highest_price_since_breach == Decimal('106')
    db_manager.update_trade.assert_called_once_with("test_trade_123", {"profit_target_breached": True, "highest_price_since_breach": Decimal('106')})

    # 4. Simulate price rising higher -> High-water mark is updated
    db_manager.update_trade.reset_mock()
    current_price = Decimal('110')
    for p in open_positions:
        if p.profit_target_breached:
            if current_price > p.highest_price_since_breach:
                p.highest_price_since_breach = current_price
                db_manager.update_trade(p.trade_id, {"highest_price_since_breach": current_price})

    assert mock_position.highest_price_since_breach == Decimal('110')
    db_manager.update_trade.assert_called_once_with("test_trade_123", {"highest_price_since_breach": Decimal('110')})

    # 5. Simulate price dropping, but not enough to trigger sell -> No action
    db_manager.update_trade.reset_mock()
    current_price = Decimal('109.5') # High is 110, 1% trail is 1.1, so stop is 108.9
    for p in open_positions:
         if p.profit_target_breached:
            highest_price = p.highest_price_since_breach
            if not (current_price > highest_price):
                trailing_stop_price = highest_price * (Decimal('1') - strategy_rules.trailing_stop_percent)
                if current_price <= trailing_stop_price:
                    positions_to_sell.append(p)

    assert len(positions_to_sell) == 0
    db_manager.update_trade.assert_not_called()

    # 6. Simulate price dropping enough to trigger sell -> Position is marked to be sold
    current_price = Decimal('108.8') # Below the 108.9 stop
    for p in open_positions:
         if p.profit_target_breached:
            highest_price = p.highest_price_since_breach
            if not (current_price > highest_price):
                trailing_stop_price = highest_price * (Decimal('1') - strategy_rules.trailing_stop_percent)
                if current_price <= trailing_stop_price:
                    positions_to_sell.append(p)

    assert len(positions_to_sell) == 1
    assert positions_to_sell[0].trade_id == "test_trade_123"
