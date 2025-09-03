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

def test_adopt_position_calculates_correct_average_price(mock_binance_client, mock_db_manager, mock_strategy_rules):
    """
    Tests that when sync_positions detects a discrepancy, it correctly adopts the position
    and calculates the weighted average price from the FIFO-reconstructed inventory.
    """
    # Arrange
    # Mock the exchange balance to be 1.5 BTC
    mock_binance_client.get_asset_balance.return_value = {'asset': 'BTC', 'free': '1.5', 'locked': '0.0'}

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

    # 2. It should have called log_trade to create the new adopted position
    mock_db_manager.log_trade.assert_called_once()

    # 3. Check the details of the created TradePoint
    call_args = mock_db_manager.log_trade.call_args
    created_trade_point: TradePoint = call_args[0][0]

    assert created_trade_point.run_id == 'adopted'
    assert created_trade_point.status == 'OPEN'
    assert created_trade_point.quantity == 1.5

    # Expected average price calculation:
    # Inventory after FIFO:
    # - 0.5 BTC from trade 1 (price 50000)
    # - 1.0 BTC from trade 2 (price 51000)
    # Total Cost = (0.5 * 50000) + (1.0 * 51000) = 25000 + 51000 = 76000
    # Total Qty = 1.5
    # Avg Price = 76000 / 1.5 = 50666.666...
    expected_avg_price = (Decimal('0.5') * Decimal('50000') + Decimal('1.0') * Decimal('51000')) / Decimal('1.5')

    assert created_trade_point.price == pytest.approx(float(expected_avg_price))
