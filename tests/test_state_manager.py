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
    """Provides a mock DatabaseManager instance."""
    return Mock()

@pytest.fixture
def state_manager(mock_db_manager):
    """
    Provides a StateManager instance with a mocked DatabaseManager.
    This fixture ensures that the real DatabaseManager is not used during tests.
    """
    # We use patch to temporarily replace the DatabaseManager class during instantiation
    with patch('jules_bot.core_logic.state_manager.DatabaseManager', return_value=mock_db_manager):
        sm = StateManager(bucket_name="test_bucket", bot_id="test_bot")
        sm.db_manager = mock_db_manager # Ensure the instance has the mock
        return sm

def test_create_new_position_logs_trade(state_manager, mock_db_manager):
    """
    Verify that `create_new_position` calls the `log_trade` method on the db_manager.
    """
    # Arrange
    buy_result = {
        'price': 100.0,
        'quantity': 1.0,
        'usd_value': 100.0,
        'trade_id': 'test-trade-123',
        'symbol': 'BTCUSDT',
        'order_type': 'buy'
    }

    # Act
    state_manager.create_new_position(buy_result)

    # Assert
    mock_db_manager.log_trade.assert_called_once_with(buy_result)

def test_close_position_logs_trade(state_manager, mock_db_manager):
    """
    Verify that `close_position` calls the `log_trade` method on the db_manager.
    """
    # Arrange
    trade_id = "test-trade-123"
    exit_data = {
        'price': 110.0,
        'quantity': 1.0,
        'usd_value': 110.0,
        'order_type': 'sell',
        'realized_pnl': 10.0
    }

    expected_log_data = {
        **exit_data,
        'trade_id': trade_id
    }

    # Act
    state_manager.close_position(trade_id, exit_data)

    # Assert
    mock_db_manager.log_trade.assert_called_once_with(expected_log_data)

def test_get_last_purchase_price_with_open_positions(state_manager):
    """
    Test that `get_last_purchase_price` returns the price of the most recent trade
    when there are open positions.
    """
    # Arrange: Mock the return value of get_open_positions
    state_manager.get_open_positions = Mock(return_value=[
        {'time': '2023-01-01T12:00:00Z', 'purchase_price': 100.0},
        {'time': '2023-01-01T13:00:00Z', 'purchase_price': 105.0}, # Most recent
        {'time': '2023-01-01T11:00:00Z', 'purchase_price': 99.0}
    ])

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
