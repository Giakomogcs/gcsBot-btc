import unittest
from unittest.mock import MagicMock, patch
from decimal import Decimal
import pandas as pd

from jules_bot.services.status_service import StatusService
from jules_bot.database.models import Trade

@patch('jules_bot.services.status_service.ExchangeManager')
class TestStatusService(unittest.TestCase):
    def setUp(self):
        # Mock dependencies
        self.db_manager = MagicMock()
        self.config_manager = MagicMock()
        self.feature_calculator = MagicMock()

        # Instantiate the service with mocked dependencies
        self.status_service = StatusService(
            db_manager=self.db_manager,
            config_manager=self.config_manager,
            feature_calculator=self.feature_calculator
        )

    def test_get_extended_status_with_open_positions(self, MockExchangeManager):
        """
        Test the get_extended_status method with live data integration.
        """
        # 1. Arrange: Mock ExchangeManager instance and its methods
        mock_exchange_instance = MockExchangeManager.return_value
        mock_exchange_instance.get_account_balance.return_value = [
            {'asset': 'BTC', 'free': '1.0', 'locked': '0.5', 'usd_value': '52000.0'}
        ]

        # Arrange: Mock DB results
        trade1 = Trade(trade_id="trade-still-open", price=50000, quantity=0.1, sell_target_price=55000, exchange_order_id="trade-still-open")
        self.db_manager.get_open_positions.return_value = [trade1]
        self.db_manager.get_all_trades_in_range.return_value = [trade1]

        # Arrange: Mock market data
        mock_market_data = pd.Series({'close': 52000.0, 'ema_20': 51000.0, 'bbl_20_2_0': 50000, 'high': 52100, 'ema_100': 50500})
        self.feature_calculator.get_current_candle_with_features.return_value = mock_market_data

        # Arrange: Mock strategy evaluation
        self.status_service.strategy.evaluate_buy_signal = MagicMock(return_value=(False, 'uptrend', 'Price > EMA20'))

        # 2. Act: Call the method under test
        result = self.status_service.get_extended_status("test", "test_bot")

        # 3. Assert: Verify results
        # Assert that ExchangeManager was called correctly
        MockExchangeManager.assert_called_with(mode='test')
        mock_exchange_instance.get_account_balance.assert_called_once()

        # Assert reconciliation logic: only one trade should be in the status
        self.assertEqual(len(result["open_positions_status"]), 1)
        self.assertEqual(result["open_positions_status"][0]['trade_id'], 'trade-still-open')

        # Assert wallet balance is live data
        self.assertEqual(len(result["wallet_balances"]), 1)
        self.assertEqual(result["wallet_balances"][0]['asset'], 'BTC')

        # Assert other calculations are still correct
        self.assertAlmostEqual(result["open_positions_status"][0]["unrealized_pnl"], (52000 - 50000) * 0.1)
        self.assertIn("buy_signal_status", result)

if __name__ == '__main__':
    unittest.main()
