import pytest
import sys
import os
from unittest.mock import Mock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.core_logic.state_manager import StateManager
from jules_bot.utils.config_manager import config_manager

@pytest.fixture
def mock_db_manager():
    """Provides a mock PostgresManager instance."""
    return Mock()

@pytest.fixture
def state_manager(mock_db_manager):
    """
    Provides a StateManager instance with a mocked PostgresManager.
    This fixture ensures that the real PostgresManager is not used during tests.
    """
    mock_feature_calculator = Mock()
    # We use patch to mock the TradeLogger that StateManager instantiates.
    with patch('jules_bot.core_logic.state_manager.TradeLogger') as MockTradeLogger:
        # Provide the mocked db_manager directly to the constructor.
        sm = StateManager(mode="test", bot_id="test_bot", db_manager=mock_db_manager, feature_calculator=mock_feature_calculator)
        
        # For tests that assert log_trade, we need to ensure the mock is correctly configured.
        # The StateManager passes its db_manager to TradeLogger, so the mock setup is simpler.
        # We can mock the instance of TradeLogger created inside StateManager.
        sm.trade_logger = MockTradeLogger()
        
        # The tests are written to assert on db_manager.log_trade.
        # To avoid rewriting them all, we'll redirect the call from the mock trade_logger
        # to the mock_db_manager. This is a test-specific workaround.
        def redirect_log(*args, **kwargs):
            mock_db_manager.log_trade(*args, **kwargs)

        sm.trade_logger.log_trade.side_effect = redirect_log
        yield sm

from jules_bot.core.schemas import TradePoint

def test_create_new_position_logs_trade(state_manager, mock_db_manager):
    """
    Verify that `create_new_position` calls `log_trade` with a TradePoint object.
    """
    # Arrange
    buy_result = {
        'price': 100.0,
        'quantity': 1.0,
        'usd_value': 100.0,
        'trade_id': 'test-trade-123',
        'symbol': 'BTCUSDT',
        'order_type': 'buy',
        'mode': 'test',
        'strategy_name': 'test_strategy',
        'exchange': 'test_exchange',
        'commission': 0.1,
        'commission_asset': 'BTC',
        'exchange_order_id': 'order-1'
    }

    # Act
    state_manager.create_new_position(buy_result, sell_target_price=101.0)

    # Assert
    # The new implementation uses TradeLogger, which is mocked.
    # The fixture redirects the call to the mock_db_manager for compatibility.
    mock_db_manager.log_trade.assert_called_once()
    call_args = mock_db_manager.log_trade.call_args[0]
    assert len(call_args) == 1
    logged_data = call_args[0]

    # StateManager now passes a dict to TradeLogger, not a TradePoint object.
    assert isinstance(logged_data, dict)
    assert logged_data['trade_id'] == 'test-trade-123'
    assert logged_data['price'] == 100.0
    assert logged_data['order_type'] == 'buy'


def test_close_position_logs_trade(state_manager, mock_db_manager):
    """
    Verify that `close_position` calls `log_trade` with a TradePoint object.
    """
    # Arrange
    trade_id = "test-trade-123"
    exit_data = {
        'price': 110.0,
        'quantity': 1.0,
        'usd_value': 110.0,
        'symbol': 'BTCUSDT',
        'order_type': 'sell',
        'realized_pnl': 10.0
    }

    # Act
    state_manager.close_position(trade_id, exit_data)

    # Assert
    mock_db_manager.log_trade.assert_called_once()
    call_args = mock_db_manager.log_trade.call_args[0]
    assert len(call_args) == 1
    logged_data = call_args[0]

    assert isinstance(logged_data, dict)
    assert logged_data['trade_id'] == trade_id
    assert logged_data['price'] == 110.0
    assert logged_data['order_type'] == 'sell'
    assert logged_data['realized_pnl'] == 10.0

def test_get_last_purchase_price_with_open_positions(state_manager):
    """
    Test that `get_last_purchase_price` returns the price of the most recent trade
    when there are open positions.
    """
    # Arrange: Mock the return value of get_open_positions to return mock objects
    # with attributes, to simulate SQLAlchemy model objects.
    trade1 = Mock()
    trade1.timestamp = '2023-01-01T12:00:00Z'
    trade1.price = 100.0

    trade2 = Mock()
    trade2.timestamp = '2023-01-01T13:00:00Z'
    trade2.price = 105.0

    trade3 = Mock()
    trade3.timestamp = '2023-01-01T11:00:00Z'
    trade3.price = 99.0

    state_manager.get_open_positions = Mock(return_value=[trade1, trade2, trade3])

    # Act
    last_price = state_manager.get_last_purchase_price()

    # Assert
    assert last_price == 105.0

def test_get_last_purchase_price_with_no_open_positions(state_manager):
    """
    Test that `get_last_purchase_price` returns infinity when there are no open positions
    to prevent accidental buy triggers.
    """
    # Arrange: Mock get_open_positions to return an empty list
    state_manager.get_open_positions = Mock(return_value=[])

    # Act
    last_price = state_manager.get_last_purchase_price()

    # Assert
    assert last_price == float('inf')
