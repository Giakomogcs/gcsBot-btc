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
            {'asset': 'BTC', 'free': '1.0', 'locked': '0.5', 'usd_value': '75000'}
        ]

        # Arrange: Mock DB results
        trade1 = Trade(trade_id="trade-still-open", price=50000, quantity=0.1, sell_target_price=55000)
        trade2 = Trade(trade_id="another-open-trade", price=48000, quantity=0.2, sell_target_price=50000)
        self.db_manager.get_open_positions.return_value = [trade1, trade2]
        self.db_manager.get_all_trades_in_range.return_value = [trade1, trade2]

        # Arrange: Mock market data from feature calculator
        mock_market_data = pd.Series({
            'close': 52000.0,
            'ema_20': 51000.0,
            'bbl_20_2_0': 50000,
            'high': 52100,
            'ema_100': 50500
        })
        self.feature_calculator.get_current_candle_with_features.return_value = mock_market_data

        # Arrange: Mock strategy evaluation
        self.status_service.strategy.evaluate_buy_signal = MagicMock(return_value=(False, 'uptrend', 'Price > EMA20'))

        # 2. Act: Call the method under test
        result = self.status_service.get_extended_status("test", "test_bot")

        # 3. Assert: Verify results
        # Assert that ExchangeManager was called correctly
        MockExchangeManager.assert_called_with(mode='test')
        mock_exchange_instance.get_account_balance.assert_called_once()

        # Assert that DB manager was called
        self.db_manager.get_open_positions.assert_called_with("test", None)

        # Assert correct number of positions are in the status
        self.assertEqual(len(result["open_positions_status"]), 2)
        self.assertEqual(result["open_positions_status"][0]['trade_id'], 'trade-still-open')

        # Assert wallet balance is present
        self.assertEqual(len(result["wallet_balances"]), 1)
        self.assertEqual(result["wallet_balances"][0]['asset'], 'BTC')

        # Assert PnL calculation is correct for the first position
        expected_pnl = (52000 - 50000) * 0.1
        self.assertAlmostEqual(result["open_positions_status"][0]["unrealized_pnl"], expected_pnl)

        # Assert that the new fields are present
        self.assertIn("price_to_target", result["open_positions_status"][0])
        self.assertIn("usd_to_target", result["open_positions_status"][0])

        self.assertIn("buy_signal_status", result)
        self.assertIn("btc_purchase_target", result["buy_signal_status"])

if __name__ == '__main__':
    unittest.main()
