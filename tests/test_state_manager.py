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
    # Mock the environment variables required by ConfigManager
    mock_env = {
        "INFLUXDB_URL": "http://test.url",
        "INFLUXDB_TOKEN": "test_token",
        "INFLUXDB_ORG": "test_org"
    }
    with patch.dict(os.environ, mock_env):
        # We use patch to temporarily replace the DatabaseManager class during instantiation
        with patch('jules_bot.core_logic.state_manager.DatabaseManager', return_value=mock_db_manager):
            sm = StateManager(bucket_name="test_bucket", bot_id="test_bot")
            sm.db_manager = mock_db_manager # Ensure the instance has the mock
            return sm

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
    mock_db_manager.log_trade.assert_called_once()
    call_args = mock_db_manager.log_trade.call_args[0]
    assert len(call_args) == 1
    logged_point = call_args[0]

    assert isinstance(logged_point, TradePoint)
    assert logged_point.trade_id == 'test-trade-123'
    assert logged_point.price == 100.0
    assert logged_point.order_type == 'buy'


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
        'realized_pnl_usd': 10.0
    }

    # Act
    state_manager.close_position(trade_id, exit_data)

    # Assert
    mock_db_manager.log_trade.assert_called_once()
    call_args = mock_db_manager.log_trade.call_args[0]
    assert len(call_args) == 1
    logged_point = call_args[0]

    assert isinstance(logged_point, TradePoint)
    assert logged_point.trade_id == trade_id
    assert logged_point.price == 110.0
    assert logged_point.order_type == 'sell'
    assert logged_point.realized_pnl_usd == 10.0

def test_get_last_purchase_price_with_open_positions(state_manager):
    """
    Test that `get_last_purchase_price` returns the price of the most recent trade
    when there are open positions.
    """
    # Arrange: Mock the return value of get_open_positions
    state_manager.get_open_positions = Mock(return_value=[
        {'_time': '2023-01-01T12:00:00Z', 'price': 100.0},
        {'_time': '2023-01-01T13:00:00Z', 'price': 105.0}, # Most recent
        {'_time': '2023-01-01T11:00:00Z', 'price': 99.0}
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
