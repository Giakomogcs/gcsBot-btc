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

        # Configure the config_manager mock to return default strategy rules
        self.config_manager.get_section.return_value = {
            'commission_rate': '0.001',
            'target_profit': '0.01',
            'sell_factor': '0.9'
        }
        # Add side effects for individual 'get' calls needed by CapitalManager
        def get_side_effect(section, key, fallback=None):
            if section == 'TRADING_STRATEGY' and key == 'min_trade_size_usdt':
                return '10.0'
            if section == 'STRATEGY_RULES' and key == 'base_usd_per_trade':
                return '20.0'
            if section == 'STRATEGY_RULES' and key == 'aggressive_buy_multiplier':
                return '2.0'
            if section == 'STRATEGY_RULES' and key == 'correction_entry_multiplier':
                return '2.5'
            if section == 'STRATEGY_RULES' and key == 'max_open_positions':
                return '10'
            return fallback

        self.config_manager.get.side_effect = get_side_effect

        # Instantiate the service with mocked dependencies
        self.status_service = StatusService(
            db_manager=self.db_manager,
            config_manager=self.config_manager,
            feature_calculator=self.feature_calculator
        )

    def test_get_extended_status_with_open_positions(self, MockExchangeManager):
        """
        Test the get_extended_status method to ensure it correctly processes and returns data.
        """
        # 1. Arrange: Mock ExchangeManager instance and its methods
        mock_exchange_instance = MockExchangeManager.return_value
        mock_exchange_instance.get_account_balance.return_value = [
            {'asset': 'BTC', 'free': '1.0', 'locked': '0.5'},
            {'asset': 'USDT', 'free': '10000', 'locked': '0'}
        ]

        # Arrange: Mock DB results for open positions
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        trade1 = Trade(trade_id="open-trade-1", price=50000, quantity=0.1, sell_target_price=55000, timestamp=now, usd_value=Decimal("5000.0"))
        trade2 = Trade(trade_id="open-trade-2", price=48000, quantity=0.2, sell_target_price=50000, timestamp=now, usd_value=Decimal("9600.0"))
        self.db_manager.get_open_positions.return_value = [trade1, trade2]
        self.db_manager.get_all_trades_in_range.return_value = [] # Not the focus of this test

        # Arrange: Mock the new get_bot_status call
        mock_status = MagicMock()
        mock_status.market_regime = 2
        mock_status.last_buy_condition = "Test Condition"
        mock_status.operating_mode = "ACCUMULATION"
        mock_status.buy_target = Decimal("51000.00")
        mock_status.buy_progress = Decimal("33.3")
        self.db_manager.get_bot_status.return_value = mock_status

        # Arrange: Mock market data from feature_calculator
        mock_market_data = {'close': 52000.0, 'ema_20': 51000.0, 'bbl_20_2_0': 50000, 'high': 52100, 'ema_100': 50500, 'atr_14': 100, 'macd_diff_12_26_9': 50}
        # The feature calculator returns a pandas Series
        self.feature_calculator.get_current_candle_with_features.return_value = pd.Series(mock_market_data)

        # Mock historical data for SA model training.
        # The rolling window needs enough data points (min_periods=36).
        # We create 40 data points and make the last 'atr_14' value exceptionally high
        # to ensure it's classified as HIGH_VOLATILITY (regime 2).
        atr_values = [50] * 39 + [200]
        macd_values = ([10, -20, 30, 40] * 10)
        historical_data = pd.DataFrame({
            'atr_14': atr_values,
            'macd_diff_12_26_9': macd_values
        })
        self.feature_calculator.get_historical_data_with_features.return_value = historical_data


        # Arrange: Mock strategy evaluation and other helper methods
        self.status_service.capital_manager.get_buy_order_details = MagicMock(return_value=(Decimal('0'), 'ACCUMULATION', 'Test Condition', 'unknown'))

        # 2. Act: Call the method under test
        result = self.status_service.get_extended_status("test", "test_bot")

        # 3. Assert: Verify results
        # Assert that ExchangeManager was called correctly
        MockExchangeManager.assert_called_with(mode='test')
        mock_exchange_instance.get_account_balance.assert_called_once()
        self.feature_calculator.get_current_candle_with_features.assert_called_once()

        # Assert that both open positions are present, as no reconciliation happens here
        self.assertEqual(len(result["open_positions_status"]), 2)
        self.assertEqual(result["open_positions_status"][0]['trade_id'], 'open-trade-1')
        self.assertEqual(result["open_positions_status"][1]['trade_id'], 'open-trade-2')

        # Assert wallet balances are processed correctly
        self.assertEqual(len(result["wallet_balances"]), 2)
        self.assertIn('usd_value', result["wallet_balances"][0])
        self.assertIn('usd_value', result["wallet_balances"][1])

        # Assert PnL and progress calculations are correct for the first trade
        pos1_status = result["open_positions_status"][0]
        # The expected PnL is now 194.80 because the unrealized PnL calculation was fixed
        # to include the full quantity and estimated sell commission, instead of using the sell_factor.
        # (52000 - 50000) * 0.1 - (52000 * 0.1 * 0.001) = 200 - 5.2 = 194.8
        self.assertAlmostEqual(float(pos1_status["unrealized_pnl"]), 194.80, places=2)
        # Progress: (52000 - 50000) / (55000 - 50000) * 100 = 40%
        self.assertAlmostEqual(float(pos1_status["progress_to_sell_target_pct"]), 40.0, places=2)
        self.assertAlmostEqual(float(pos1_status["price_to_target"]), 3000, places=2)
        self.assertAlmostEqual(float(pos1_status["usd_to_target"]), 300, places=2)
        
        # Assert that the buy signal status is included and has the new structure
        self.assertIn("buy_signal_status", result)
        buy_status = result["buy_signal_status"]
        self.assertEqual(buy_status["reason"], "Test Condition")
        self.assertEqual(buy_status["market_regime"], 2) # HIGH_VOLATILITY
        self.assertEqual(buy_status["operating_mode"], "ACCUMULATION")
        # Check for the new keys, ensuring the structure is correct
        self.assertIn("condition_target", buy_status)
        self.assertIn("condition_progress", buy_status)
        self.assertIn("condition_label", buy_status)

if __name__ == '__main__':
    unittest.main()
