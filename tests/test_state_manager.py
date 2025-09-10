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
    realized_pnl_usd = 10.0
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
    state_manager.close_forced_position(trade_id, sell_result, realized_pnl_usd)

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
    assert logged_data['realized_pnl_usd'] == realized_pnl_usd

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

class TestSyncLogic:
    @pytest.fixture
    def mock_trader(self):
        return Mock()

    @pytest.fixture
    def mock_strategy_rules(self):
        mock = Mock()
        # Simple PnL calculation for testing
        def simple_pnl_calc(buy_price, sell_price, quantity_sold, buy_commission_usd, sell_commission_usd, buy_quantity):
            return (sell_price - buy_price) * quantity_sold - buy_commission_usd - sell_commission_usd
        mock.calculate_realized_pnl.side_effect = simple_pnl_calc
        return mock

    def test_sync_creates_sell_record_with_pnl_and_fills(self, state_manager, mock_trader, mock_strategy_rules):
        """
        Tests that sync_holdings_with_binance correctly creates a sell record
        for a trade closed on the exchange, calculates its PnL, and stores the fills.
        """
        # Arrange
        from decimal import Decimal

        buy_trade_from_db = Mock()
        buy_trade_from_db.binance_trade_id = 12345
        buy_trade_from_db.trade_id = "internal-buy-id"
        buy_trade_from_db.price = Decimal('100.0')
        buy_trade_from_db.quantity = Decimal('1.0')
        buy_trade_from_db.commission_usd = Decimal('1.0')
        buy_trade_from_db.run_id = "test_bot"
        buy_trade_from_db.strategy_name = "default"
        buy_trade_from_db.symbol = "BTCUSDT"
        buy_trade_from_db.exchange = "binance"

        # Set up the mock to return a list of trade objects
        state_manager.db_manager.get_all_trades_in_range.return_value = [buy_trade_from_db]
        state_manager.db_manager.get_trade_by_binance_trade_id.return_value = None

        binance_buy_trade = {
            'id': 12345, 'isBuyer': True, 'qty': '1.0', 'price': '100.0',
            'commission': '0.001', 'commissionAsset': 'BTC', 'time': 1672531200000, 'orderId': 'order-1'
        }
        binance_sell_trade = {
            'id': 54321, 'isBuyer': False, 'qty': '1.0', 'price': '110.0',
            'commission': '0.11', 'commissionAsset': 'USDT', 'time': 1672534800000, 'orderId': 'order-2',
            'fills': [{'price': '110.0', 'qty': '1.0'}]
        }

        mock_trader.get_all_my_trades.return_value = [binance_buy_trade, binance_sell_trade]
        mock_trader.get_all_prices.return_value = {'BTCUSDT': '100.0'} # Mock price for commission calculation

        # Act
        state_manager.sync_holdings_with_binance(
            account_manager=Mock(),
            strategy_rules=mock_strategy_rules,
            trader=mock_trader
        )

        # Assert
        state_manager.trade_logger.log_trade.assert_called_once()
        call_args = state_manager.trade_logger.log_trade.call_args[0][0]

        assert call_args['order_type'] == 'sell'
        assert call_args['status'] == 'CLOSED'
        assert call_args['linked_trade_id'] == "internal-buy-id"
        assert call_args['sell_price'] == Decimal('110.0')

        # Expected PnL = (110 - 100) * 1.0 - 1.0 (buy_comm) - 0.11 (sell_comm) = 8.89
        assert call_args['realized_pnl_usd'] == Decimal('8.89')

        assert 'fills' in call_args['decision_context']
        assert call_args['decision_context']['fills'] == binance_sell_trade

        state_manager.db_manager.update_trade_status_and_quantity.assert_called_once_with(
            "internal-buy-id", "CLOSED", 0.0
        )
