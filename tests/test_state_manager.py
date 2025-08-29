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
    Provides a StateManager instance with a mocked PostgresManager and a mocked TradeLogger.
    """
    mock_feature_calculator = Mock()
    with patch('jules_bot.core_logic.state_manager.TradeLogger') as MockTradeLogger:
        sm = StateManager(mode="test", bot_id="test_bot", db_manager=mock_db_manager, feature_calculator=mock_feature_calculator)
        # Replace the instance of TradeLogger with our mock
        sm.trade_logger = MockTradeLogger()
        yield sm


def test_create_new_position_logs_trade(state_manager):
    """
    Verify that `create_new_position` calls `log_trade` with a dictionary.
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
    state_manager.trade_logger.log_trade.assert_called_once()
    call_args = state_manager.trade_logger.log_trade.call_args[0]
    assert len(call_args) == 1
    logged_data = call_args[0]

    assert isinstance(logged_data, dict)
    assert logged_data['trade_id'] == 'test-trade-123'
    assert logged_data['price'] == 100.0
    assert logged_data['order_type'] == 'buy'
    assert logged_data['status'] == 'OPEN'


def test_close_forced_position_logs_trade(state_manager):
    """
    Verify that `close_forced_position` calls `log_trade` with the correct sell data.
    """
    # Arrange
    trade_id = "test-buy-trade-123"
    realized_pnl = 10.0
    sell_result = {
        'price': 110.0,
        'quantity': 1.0,
        'usd_value': 110.0,
        'symbol': 'BTCUSDT',
        'order_type': 'sell',
        'timestamp': 1672531200000, # 2023-01-01
        'exchange_order_id': 'order-2',
        'commission': 0.1,
        'commission_asset': 'USDT',
        'binance_trade_id': 54321
    }

    # Mock the original trade that is fetched from the DB
    mock_original_trade = Mock()
    mock_original_trade.strategy_name = 'default'
    mock_original_trade.symbol = 'BTCUSDT'
    mock_original_trade.exchange = 'binance'
    mock_original_trade.price = 100.0 # Original buy price
    state_manager.db_manager.get_trade_by_trade_id.return_value = mock_original_trade

    # Act
    state_manager.close_forced_position(trade_id, sell_result, realized_pnl)

    # Assert
    state_manager.trade_logger.log_trade.assert_called_once()
    call_args = state_manager.trade_logger.log_trade.call_args[0]
    assert len(call_args) == 1
    logged_data = call_args[0]

    assert isinstance(logged_data, dict)
    assert logged_data['linked_trade_id'] == trade_id
    assert logged_data['price'] == 100.0 # Should be the original buy price
    assert logged_data['sell_price'] == 110.0 # The actual sell price
    assert logged_data['order_type'] == 'sell'
    assert logged_data['status'] == 'CLOSED'
    assert logged_data['realized_pnl_usd'] == realized_pnl

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
