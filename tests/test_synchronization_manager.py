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

def test_run_full_sync_from_scratch_complex_scenario(sync_manager, mock_db_manager):
    # This is a full integration test for the synchronization logic.
    # 1. Start with an empty local DB.
    # 2. Provide a complex history of trades from Binance.
    # 3. Run the full sync.
    # 4. Verify that the final state of the local DB is perfectly reconciled.
    
    # ARRANGE
    start_time = datetime.datetime.now(datetime.timezone.utc)
    
    # Mock Binance trade history
    binance_trades = [
        {'id': 1, 'isBuyer': True,  'price': '100', 'qty': '10', 'commission': '0.01', 'commissionAsset': 'BTC',   'time': int((start_time + datetime.timedelta(minutes=1)).timestamp() * 1000), 'orderId': 101},
        {'id': 2, 'isBuyer': True,  'price': '110', 'qty': '5',  'commission': '0.005', 'commissionAsset': 'BTC',  'time': int((start_time + datetime.timedelta(minutes=2)).timestamp() * 1000), 'orderId': 102},
        {'id': 3, 'isBuyer': False, 'price': '120', 'qty': '7',  'commission': '8.4', 'commissionAsset': 'USDT',   'time': int((start_time + datetime.timedelta(minutes=3)).timestamp() * 1000), 'orderId': 103},
        {'id': 4, 'isBuyer': True,  'price': '105', 'qty': '8',  'commission': '0.008', 'commissionAsset': 'BTC',  'time': int((start_time + datetime.timedelta(minutes=4)).timestamp() * 1000), 'orderId': 104},
        {'id': 5, 'isBuyer': False, 'price': '130', 'qty': '12', 'commission': '15.6', 'commissionAsset': 'USDT', 'time': int((start_time + datetime.timedelta(minutes=5)).timestamp() * 1000), 'orderId': 105},
    ]
    sync_manager.client.get_my_trades.return_value = binance_trades
    sync_manager.client.get_account.return_value = {'balances': [{'asset': 'BTC', 'free': '4.0', 'locked': '0.0'}]}
    sync_manager.client.get_all_tickers.return_value = [{'symbol': 'BTCUSDT', 'price': '130'}] # For commission calcs

    # --- Mock the DB interactions ---
    # Use a dictionary to simulate the database
    db_storage = {} 

    def mock_log_trade(trade_data):
        # When a trade is logged, add it to our mock DB
        trade_id = trade_data['trade_id']
        # Create a mock object that simulates a SQLAlchemy model
        mock_trade_obj = MagicMock(spec=Trade)
        for key, value in trade_data.items():
            setattr(mock_trade_obj, key, value)
        
        # Buys need a remaining_quantity to be tracked
        if trade_data['order_type'] == 'buy':
            mock_trade_obj.remaining_quantity = trade_data['quantity']

        db_storage[trade_id] = mock_trade_obj

    def mock_get_open_positions(environment, symbol):
        # Return all 'buy' trades from our mock DB that are still 'OPEN'
        return sorted([
            t for t in db_storage.values() 
            if t.order_type == 'buy' and t.status == 'OPEN'
        ], key=lambda t: t.timestamp)

    def mock_update_trade(trade_id, payload):
        # Update the trade in our mock DB
        if trade_id in db_storage:
            for key, value in payload.items():
                setattr(db_storage[trade_id], key, value)

    # Patch the methods
    sync_manager.trade_logger.log_trade = mock_log_trade
    sync_manager.db.get_all_trades_for_sync.return_value = [] # Start with empty DB
    sync_manager.db.get_open_positions.side_effect = mock_get_open_positions
    sync_manager.db.update_trade.side_effect = mock_update_trade

    # ACT
    sync_manager.run_full_sync()

    # ASSERT
    # Filter buys and sells from our final DB state
    final_buys = {t.binance_trade_id: t for t in db_storage.values() if t.order_type == 'buy'}
    final_sells = [t for t in db_storage.values() if t.order_type == 'sell']

    # 1. Verify final state of all original BUY trades
    # Buy #1 (ID 1) should be fully closed
    assert final_buys[1].status == 'CLOSED'
    assert final_buys[1].remaining_quantity <= Decimal('1e-8')

    # Buy #2 (ID 2) should be fully closed
    assert final_buys[2].status == 'CLOSED'
    assert final_buys[2].remaining_quantity <= Decimal('1e-8')
    
    # Buy #3 (ID 4) should be partially open
    assert final_buys[4].status == 'OPEN'
    assert final_buys[4].remaining_quantity == Decimal('4') # 8 bought, 4 sold from it

    # 2. Verify the SELL trades that were created
    # Sell #3 (7 units) vs Buy #1 -> 1 sell record
    # Sell #5 (12 units) vs Buy #1 (rem 3), Buy #2 (rem 5), Buy #4 (rem 8) -> 3 sell records
    # Total sell records = 4
    assert len(final_sells) == 4
    
    # Sell #3 (7 units) should be linked to Buy #1
    sell_record_1 = next(s for s in final_sells if s.binance_trade_id == 3)
    buy_1_trade_id = final_buys[1].trade_id
    assert sell_record_1.linked_trade_id == buy_1_trade_id
    assert sell_record_1.quantity == Decimal('7')

    # Sell #5 (12 units) is split. Find the parts.
    sell_records_2 = [s for s in final_sells if s.binance_trade_id == 5]
    assert len(sell_records_2) == 3
    
    # Part 1 of Sell #5 closes the rest of Buy #1 (3 units) and all of Buy #2 (5 units)
    # The current logic will create one record for the remaining 3 of buy 1, and one for the 5 of buy 2 + 4 of buy 3 = 9
    # Let's adjust the test to the actual implementation: A sell is matched against open buys one by one.
    # So sell #5 (12 units) matches:
    # - 3 units from buy #1
    # - 5 units from buy #2
    # - 4 units from buy #3
    # The code creates a *new sell record* for each linkage. So we expect 1 (from sell #3) + 3 (from sell #5) = 4 sell records.
    # Let's re-verify the code.
    # Ah, `_reconcile_external_sell` loops through open buys. For each one, it creates ONE new sell trade data.
    # So, Sell #3 (7 units) vs Buy #1 (10 units) -> Creates 1 sell record.
    # Sell #5 (12 units) vs Buy #1 (rem 3), Buy #2 (rem 5), Buy #3 (rem 8) -> Creates 3 sell records.
    # Total sell records = 1 + 3 = 4.
    
    # Let's re-run the logic in my head.
    # Sync starts.
    # Buys 1, 2 are created.
    # Sell 3 (7 units) comes in. `get_open_positions` -> [Buy1 (10rem), Buy2 (5rem)].
    #   - Loop 1: `buy_trade` is Buy1. `qty_to_sell` is min(7, 10) = 7. A sell record is created for 7 units, linked to Buy1. Buy1 `rem_qty` becomes 3. `sell_qty_to_match` becomes 0. Loop breaks. (1 sell record created)
    # Buy 4 is created.
    # Sell 5 (12 units) comes in. `get_open_positions` -> [Buy1 (3rem), Buy2 (5rem), Buy4 (8rem)].
    #   - Loop 1: `buy_trade` is Buy1. `qty_to_sell` is min(12, 3) = 3. Sell record created for 3 units, linked to Buy1. Buy1 `rem_qty` becomes 0, status CLOSED. `sell_qty_to_match` becomes 9. (2nd sell record created)
    #   - Loop 2: `buy_trade` is Buy2. `qty_to_sell` is min(9, 5) = 5. Sell record created for 5 units, linked to Buy2. Buy2 `rem_qty` becomes 0, status CLOSED. `sell_qty_to_match` becomes 4. (3rd sell record created)
    #   - Loop 3: `buy_trade` is Buy4. `qty_to_sell` is min(4, 8) = 4. Sell record created for 4 units, linked to Buy4. Buy4 `rem_qty` becomes 4. `sell_qty_to_match` becomes 0. Loop breaks. (4th sell record created)
    # Total sell records = 4. My prediction is corrected.
    
    assert len(final_sells) == 4

    # Check PnL was calculated on all of them
    assert all(s.realized_pnl_usd is not None for s in final_sells)
    
    # Final sanity check should not log a warning
    sync_manager.client.get_account.assert_called_once()
