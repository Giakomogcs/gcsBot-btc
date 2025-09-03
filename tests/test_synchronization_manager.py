import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from jules_bot.bot.synchronization_manager import SynchronizationManager
from jules_bot.core.schemas import TradePoint

@pytest.fixture
def mock_binance_client():
    client = MagicMock()
    # Trade history:
    # 1. BUY 1 BTC @ 50000 (id=1)
    # 2. BUY 1 BTC @ 51000 (id=2)
    # 3. SELL 0.5 BTC @ 52000 (id=3)
    # Expected final inventory: 0.5 BTC from trade 1, 1 BTC from trade 2. Total 1.5 BTC.
    trade_history = [
        {'id': 1, 'symbol': 'BTCUSDT', 'isBuyer': True, 'price': '50000.00', 'qty': '1.0', 'commission': '0.001', 'commissionAsset': 'BTC', 'time': 1672531200000, 'orderId': '1'},
        {'id': 2, 'symbol': 'BTCUSDT', 'isBuyer': True, 'price': '51000.00', 'qty': '1.0', 'commission': '0.001', 'commissionAsset': 'BTC', 'time': 1672534800000, 'orderId': '2'},
        {'id': 3, 'symbol': 'BTCUSDT', 'isBuyer': False, 'price': '52000.00', 'qty': '0.5', 'commission': '26.0', 'commissionAsset': 'USDT', 'time': 1672538400000, 'orderId': '3'},
    ]
    client.get_my_trades.return_value = trade_history
    return client

@pytest.fixture
def mock_db_manager():
    db = MagicMock()
    db.get_total_open_quantity.return_value = Decimal('0') # Assume no local positions initially
    db.get_open_buy_trades_sorted.return_value = []
    return db

@pytest.fixture
def mock_strategy_rules():
    return MagicMock()

def test_adopt_position_creates_independent_trades(mock_binance_client, mock_db_manager, mock_strategy_rules):
    """
    Tests that sync_positions adopts each open buy trade as an independent
    position in the local database.
    """
    # Arrange
    mock_binance_client.get_asset_balance.return_value = {'asset': 'BTC', 'free': '1.5', 'locked': '0.0'}
    # Prevent get_trade_by_binance_trade_id from finding existing trades
    mock_db_manager.get_trade_by_binance_trade_id.return_value = None

    sync_manager = SynchronizationManager(
        binance_client=mock_binance_client,
        db_manager=mock_db_manager,
        symbol='BTCUSDT',
        strategy_rules=mock_strategy_rules,
        environment='test'
    )

    # Act
    sync_manager.sync_positions()

    # Assert
    # 1. It should have checked for local positions to close them.
    mock_db_manager.get_open_buy_trades_sorted.assert_called_once_with('BTCUSDT')

    # 2. It should have called log_trade twice, once for each open position.
    assert mock_db_manager.log_trade.call_count == 2

    # 3. Check the details of the created TradePoints
    calls = mock_db_manager.log_trade.call_args_list

    # The inventory after FIFO is a partial buy from trade 1 and the full buy from trade 2.
    # The calls might not be in a guaranteed order, so we check the contents.

    trade1_found = False
    trade2_found = False

    for call in calls:
        created_trade: TradePoint = call[0][0]
        assert created_trade.run_id == 'adopted'
        assert created_trade.status == 'OPEN'

        if created_trade.binance_trade_id == 1:
            trade1_found = True
            assert created_trade.price == 50000.00
            assert created_trade.quantity == 0.5 # 1.0 original - 0.5 sell
        elif created_trade.binance_trade_id == 2:
            trade2_found = True
            assert created_trade.price == 51000.00
            assert created_trade.quantity == 1.0

    assert trade1_found and trade2_found, "Both adopted trades were not found in log_trade calls."
