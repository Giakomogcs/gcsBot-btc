import pytest
from unittest.mock import Mock, patch, call
from decimal import Decimal
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.bot.synchronization_manager import SynchronizationManager
from jules_bot.utils.config_manager import config_manager

@pytest.fixture
def mock_db_manager():
    """Provides a mock PostgresManager instance."""
    return Mock()

@pytest.fixture
def mock_binance_client():
    """Provides a mock Binance client."""
    return Mock()

@pytest.fixture
def mock_strategy_rules():
    mock = Mock()
    mock.calculate_sell_target_price.return_value = Decimal("101.0")
    return mock

@pytest.fixture
def sync_manager(mock_binance_client, mock_db_manager, mock_strategy_rules):
    """Provides a SynchronizationManager instance with mocks."""
    if not config_manager.bot_name:
        config_manager.initialize(bot_name="test_bot")

    with patch('jules_bot.bot.synchronization_manager.TradeLogger') as MockTradeLogger:
        manager = SynchronizationManager(
            binance_client=mock_binance_client,
            db_manager=mock_db_manager,
            symbol="BTCUSDT",
            strategy_rules=mock_strategy_rules,
            environment="test"
        )
        manager.trade_logger = MockTradeLogger()
        yield manager

class TestSyncTwoPass:
    def test_full_sync_with_new_buy_and_sell(self, sync_manager, mock_db_manager, mock_binance_client):
        """
        Tests the full two-pass sync logic.
        - Pass 1 (Mirroring): A new buy and a new sell from Binance should be added to the local DB.
        - Pass 2 (Reconciliation): The local sell should be linked to the local buy, and the buy's status should be updated.
        """
        # --- Arrange ---
        # State: DB is empty. Binance has one buy and one sell.
        binance_buy_trade = {
            'id': 101, 'isBuyer': True, 'qty': '1.0', 'price': '100.0',
            'commission': '0.0', 'commissionAsset': 'USDT', 'time': 1000, 'orderId': 'order-1'
        }
        binance_sell_trade = {
            'id': 102, 'isBuyer': False, 'qty': '1.0', 'price': '110.0',
            'commission': '0.0', 'commissionAsset': 'USDT', 'time': 2000, 'orderId': 'order-2'
        }
        mock_binance_client.get_my_trades.return_value = [binance_buy_trade, binance_sell_trade]
        mock_binance_client.get_all_tickers.return_value = []

        # --- Mocking for Pass 1 (Mirroring) ---
        # Initially, the DB is empty.
        mock_db_manager.get_all_trades_for_sync.return_value = []

        # --- Mocking for Pass 2 (Reconciliation) ---
        # After Pass 1, the DB should contain the mirrored trades.
        # We need to create mock trade objects that the reconciliation pass will find.
        mirrored_buy = Mock()
        mirrored_buy.binance_trade_id = 101
        mirrored_buy.trade_id = "sync_id_buy"
        mirrored_buy.quantity = Decimal('1.0')
        mirrored_buy.status = 'OPEN' # It was created as OPEN

        mirrored_sell = Mock()
        mirrored_sell.binance_trade_id = 102
        mirrored_sell.trade_id = "sync_id_sell"
        mirrored_sell.linked_trade_id = None # Initially unlinked

        # Set up the mock to return different values on consecutive calls
        mock_db_manager.get_all_trades_for_sync.side_effect = [
            [], # First call in _mirror_binance_trades returns empty
            [mirrored_buy, mirrored_sell] # Second call in _reconcile_local_state returns the mirrored trades
        ]

        # --- Act ---
        sync_manager.run_full_sync()

        # --- Assert ---
        # Assert Pass 1 (Mirroring)
        assert sync_manager.trade_logger.log_trade.call_count == 2

        # Check that the buy was adopted correctly
        call_args_buy = sync_manager.trade_logger.log_trade.call_args_list[0].args[0]
        assert call_args_buy['binance_trade_id'] == 101
        assert call_args_buy['order_type'] == 'buy'
        assert call_args_buy['status'] == 'OPEN' # Adopted as OPEN

        # Check that the sell was created as unlinked
        call_args_sell = sync_manager.trade_logger.log_trade.call_args_list[1].args[0]
        assert call_args_sell['binance_trade_id'] == 102
        assert call_args_sell['order_type'] == 'sell'
        assert call_args_sell['linked_trade_id'] is None

        # Assert Pass 2 (Reconciliation)
        # Check that the sell was linked to the buy
        mock_db_manager.update_trade.assert_called_once_with("sync_id_sell", {'linked_trade_id': 'sync_id_buy'})

        # Check that the buy was closed
        mock_db_manager.update_trade_status_and_quantity.assert_called_once_with(
            "sync_id_buy", "CLOSED", pytest.approx(Decimal('0.0'))
        )
