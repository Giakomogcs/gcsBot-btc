import pytest
from unittest.mock import MagicMock, patch, call, ANY
from decimal import Decimal
import datetime
import uuid

from jules_bot.bot.synchronization_manager import SynchronizationManager
from jules_bot.database.models import Trade

# Reusable mock trade data from Binance API
MOCK_BINANCE_BUY = {
    'id': 1001, 'orderId': 2001, 'isBuyer': True, 'price': '50000.0',
    'qty': '1.0', 'commission': '0.001', 'commissionAsset': 'BTC',
    'time': int(datetime.datetime.now().timestamp() * 1000)
}
MOCK_BINANCE_SELL = {
    'id': 1002, 'orderId': 2002, 'isBuyer': False, 'price': '52000.0',
    'qty': '0.5', 'commission': '5.2', 'commissionAsset': 'USDT',
    'time': int((datetime.datetime.now() + datetime.timedelta(hours=1)).timestamp() * 1000)
}

@pytest.fixture
def sync_manager(mock_db_manager):
    mock_binance_client = MagicMock()
    mock_strategy_rules = MagicMock()
    
    manager = SynchronizationManager(
        binance_client=mock_binance_client,
        db_manager=mock_db_manager,
        symbol="BTCUSDT",
        strategy_rules=mock_strategy_rules,
        environment="test"
    )
    # Mock the price ticker call
    manager.client.get_all_tickers.return_value = [{'symbol': 'BTCUSDT', 'price': '52000.0'}]
    return manager

def create_mock_db_trade(binance_id, quantity, remaining_quantity, status='OPEN', order_type='buy'):
    """Helper function to create a mock Trade object as if it came from the DB."""
    trade = MagicMock(spec=Trade)
    trade.trade_id = f"local_{uuid.uuid4()}"
    trade.binance_trade_id = binance_id
    trade.quantity = Decimal(quantity)
    trade.remaining_quantity = Decimal(remaining_quantity)
    trade.status = status
    trade.order_type = order_type
    trade.price = Decimal('50000')
    trade.commission_usd = Decimal('50') # 0.1% of 50k
    trade.timestamp = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    return trade

def test_run_full_sync_no_new_trades(sync_manager, mock_db_manager):
    # Arrange: Local DB and Binance are perfectly in sync.
    mock_db_trade = create_mock_db_trade(MOCK_BINANCE_BUY['id'], '1.0', '1.0')
    sync_manager.db.get_all_trades_for_sync.return_value = [mock_db_trade]
    sync_manager.client.get_my_trades.return_value = [MOCK_BINANCE_BUY]

    # Act
    sync_manager.run_full_sync()

    # Assert: No new positions or reconciliation should be triggered.
    sync_manager.db.update_trade.assert_not_called()

def test_run_full_sync_adopts_new_buy(sync_manager, mock_db_manager):
    # Arrange: Binance has a new buy trade that the local DB does not have.
    sync_manager.db.get_all_trades_for_sync.return_value = [] # Empty local DB
    sync_manager.client.get_my_trades.return_value = [MOCK_BINANCE_BUY]
    
    with patch.object(sync_manager.trade_logger, 'log_trade') as mock_log_trade:
        # Act
        sync_manager.run_full_sync()
        
        # Assert: A new position should be created
        mock_log_trade.assert_called_once()
        call_args = mock_log_trade.call_args[0][0]
        assert call_args['order_type'] == 'buy'
        assert call_args['status'] == 'OPEN'
        assert call_args['binance_trade_id'] == MOCK_BINANCE_BUY['id']

@patch('jules_bot.bot.synchronization_manager.SynchronizationManager._reconcile_external_sell')
def test_run_full_sync_triggers_reconciliation_for_external_sell(mock_reconcile_method, sync_manager, mock_db_manager):
    # Arrange: DB has an open buy, Binance has a new sell.
    mock_db_buy = create_mock_db_trade(MOCK_BINANCE_BUY['id'], '1.0', '1.0')
    sync_manager.db.get_all_trades_for_sync.return_value = [mock_db_buy]
    sync_manager.client.get_my_trades.return_value = [MOCK_BINANCE_BUY, MOCK_BINANCE_SELL]

    # Act
    sync_manager.run_full_sync()

    # Assert: The reconciliation method for external sells should be called.
    mock_reconcile_method.assert_called_once_with(MOCK_BINANCE_SELL, ANY)

def test_reconcile_external_sell_partial_sell(sync_manager, mock_db_manager):
    # Arrange: One open buy of 1.0 BTC, external sell of 0.5 BTC.
    mock_db_buy = create_mock_db_trade(MOCK_BINANCE_BUY['id'], '1.0', '1.0')
    sync_manager.db.get_open_positions.return_value = [mock_db_buy]
    
    sync_manager.strategy_rules.calculate_realized_pnl.return_value = Decimal('1000')
    
    with patch.object(sync_manager.trade_logger, 'log_trade') as mock_log_trade:
        # Act
        sync_manager._reconcile_external_sell(MOCK_BINANCE_SELL, {'BTCUSDT': '52000'})

        # Assert
        mock_log_trade.assert_called_once()
        sell_call_args = mock_log_trade.call_args[0][0]
        assert sell_call_args['order_type'] == 'sell'
        assert sell_call_args['linked_trade_id'] == mock_db_buy.trade_id
        assert sell_call_args['quantity'] == Decimal(MOCK_BINANCE_SELL['qty'])
        assert sell_call_args['realized_pnl_usd'] == Decimal('1000')

        sync_manager.db.update_trade.assert_called_once()
        update_call_args = sync_manager.db.update_trade.call_args[0]
        assert update_call_args[0] == mock_db_buy.trade_id
        update_payload = update_call_args[1]
        assert 'status' not in update_payload
        assert update_payload['remaining_quantity'] == Decimal('0.5')

def test_reconcile_external_sell_full_sell(sync_manager, mock_db_manager):
    # Arrange: One open buy of 0.5 BTC, external sell of 0.5 BTC.
    mock_db_buy = create_mock_db_trade(MOCK_BINANCE_BUY['id'], '0.5', '0.5')
    sync_manager.db.get_open_positions.return_value = [mock_db_buy]
    sync_manager.strategy_rules.calculate_realized_pnl.return_value = Decimal('1000')
    
    with patch.object(sync_manager.trade_logger, 'log_trade'):
        # Act
        sync_manager._reconcile_external_sell(MOCK_BINANCE_SELL, {'BTCUSDT': '52000'})

        # Assert: The original buy trade is updated and marked as CLOSED.
        sync_manager.db.update_trade.assert_called_once()
        update_call_args = sync_manager.db.update_trade.call_args[0]
        assert update_call_args[0] == mock_db_buy.trade_id
        update_payload = update_call_args[1]
        assert update_payload['status'] == 'CLOSED'
        assert update_payload['remaining_quantity'] <= Decimal('1e-8')

@patch('jules_bot.bot.synchronization_manager.logger.warning')
def test_final_balance_sanity_check_logs_warning_on_discrepancy(mock_logger, sync_manager, mock_db_manager):
    # Arrange: Local state has 1 BTC, but exchange has 1.5 BTC (e.g., a deposit).
    mock_db_buy = create_mock_db_trade(MOCK_BINANCE_BUY['id'], '1.0', '1.0')
    sync_manager.db.get_open_positions.return_value = [mock_db_buy]
    sync_manager.client.get_account.return_value = {'balances': [{'asset': 'BTC', 'free': '1.5', 'locked': '0.0'}]}
    
    # Act
    sync_manager._final_balance_sanity_check()
    
    # Assert
    mock_logger.assert_called_once()
    assert "FINAL SANITY CHECK FAILED" in mock_logger.call_args[0][0]
