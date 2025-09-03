import unittest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from datetime import datetime, timedelta
from jules_bot.core_logic.capital_manager import CapitalManager, OperatingMode
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.database.models import Trade

class TestCapitalManager(unittest.TestCase):
    def setUp(self):
        self.mock_config_manager = MagicMock()
        self.mock_strategy_rules = MagicMock(spec=StrategyRules)

        # Configure mock config values
        self.config_values = {
            ('TRADING_STRATEGY', 'min_trade_size_usdt'): '10.0',
            ('TRADING_STRATEGY', 'max_trade_size_usdt'): '10000.0',
            ('STRATEGY_RULES', 'base_usd_per_trade'): '20.0',
            ('STRATEGY_RULES', 'aggressive_buy_multiplier'): '2.0',
            ('STRATEGY_RULES', 'correction_entry_multiplier'): '2.5',
            ('STRATEGY_RULES', 'max_open_positions'): '10',
            ('STRATEGY_RULES', 'use_percentage_based_sizing'): False,
            ('STRATEGY_RULES', 'order_size_free_cash_percentage'): '0.1',
            ('STRATEGY_RULES', 'use_dynamic_capital'): True,
            ('STRATEGY_RULES', 'consecutive_buys_threshold'): '5',
            ('STRATEGY_RULES', 'difficulty_reset_timeout_hours'): '2',
        }
        self.mock_config_manager.get.side_effect = self.get_config_value
        self.mock_config_manager.getboolean.side_effect = self.get_config_boolean_value
        self.mock_strategy_rules.base_usd_per_trade = Decimal('20.0')

        self.params = {
            'order_size_usd': Decimal('20.0'),
            'buy_dip_percentage': Decimal('0.02'),
            'sell_rise_percentage': Decimal('0.02')
        }

        self.capital_manager = CapitalManager(
            config_manager=self.mock_config_manager,
            strategy_rules=self.mock_strategy_rules
        )

    def get_config_value(self, section, key, fallback=None):
        return self.config_values.get((section, key), fallback)

    def get_config_boolean_value(self, section, key, fallback=None):
        val = self.config_values.get((section, key), fallback)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ('true', '1', 't')

    def test_preservation_mode_when_no_buy_signal(self):
        """Should not buy if there is no buy signal."""
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (False, "unknown", "No signal")

        self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[],
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params,
            trade_history=[]
        )

        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with(
            market_data={},
            open_positions_count=0,
            params=self.params,
            difficulty_dip_adjustment=Decimal('0')
        )

    def test_aggressive_mode_logic(self):
        """Should return multiplied trade size in AGGRESSIVE mode."""
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "Strong uptrend signal")

        amount, mode, _, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[MagicMock()] * 2, # 2 is less than 10/4=2.5
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params,
            trade_history=[]
        )

        self.assertEqual(mode, OperatingMode.AGGRESSIVE.name)
        self.assertEqual(amount, Decimal('40.00')) # 20 * 2.0


class TestDifficultyAdjustment(unittest.TestCase):
    def setUp(self):
        self.mock_config_manager = MagicMock()
        self.mock_strategy_rules = MagicMock(spec=StrategyRules)

        self.config_values = {
            ('STRATEGY_RULES', 'use_dynamic_capital'): True,
            ('STRATEGY_RULES', 'consecutive_buys_threshold'): '5',
            ('STRATEGY_RULES', 'difficulty_reset_timeout_hours'): '2',
        }
        self.mock_config_manager.get.side_effect = self.get_config_value
        self.mock_config_manager.getboolean.return_value = True

        self.capital_manager = CapitalManager(
            config_manager=self.mock_config_manager,
            strategy_rules=self.mock_strategy_rules
        )
        self.params = {'buy_dip_percentage': Decimal('0.02')}

    def get_config_value(self, section, key, fallback=None):
        return self.config_values.get((section, key), fallback)

    def create_mock_trade(self, order_type, minutes_ago):
        trade = MagicMock(spec=Trade)
        trade.order_type = order_type
        trade.timestamp = datetime.now() - timedelta(minutes=minutes_ago)
        return trade

    def test_no_adjustment_below_threshold(self):
        """Should pass an adjustment of 0 when streak is less than the threshold."""
        trade_history = [self.create_mock_trade('buy', i) for i in range(4)] # 4 buys
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "signal")

        self.capital_manager.get_buy_order_details(
            market_data={}, open_positions=[], portfolio_value=Decimal(1000),
            free_cash=Decimal(100), params=self.params, trade_history=trade_history
        )

        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with(
            market_data=unittest.mock.ANY, open_positions_count=unittest.mock.ANY,
            params=unittest.mock.ANY, difficulty_dip_adjustment=Decimal('0')
        )

    def test_base_adjustment_at_threshold(self):
        """Should pass the base 0.5% adjustment at a streak of 5."""
        trade_history = [self.create_mock_trade('buy', i) for i in range(5)] # 5 buys
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "signal")

        self.capital_manager.get_buy_order_details(
            market_data={}, open_positions=[], portfolio_value=Decimal(1000),
            free_cash=Decimal(100), params=self.params, trade_history=trade_history
        )

        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with(
            market_data=unittest.mock.ANY, open_positions_count=unittest.mock.ANY,
            params=unittest.mock.ANY, difficulty_dip_adjustment=Decimal('0.005')
        )

    def test_incremental_adjustment_above_threshold(self):
        """Should pass an incremented adjustment for streaks > 5."""
        # Test for 7 consecutive buys
        trade_history = [self.create_mock_trade('buy', i) for i in range(7)] # 7 buys
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "signal")

        self.capital_manager.get_buy_order_details(
            market_data={}, open_positions=[], portfolio_value=Decimal(1000),
            free_cash=Decimal(100), params=self.params, trade_history=trade_history
        )

        # Expected: 0.005 (base) + (7 - 5) * 0.001 = 0.007
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with(
            market_data=unittest.mock.ANY, open_positions_count=unittest.mock.ANY,
            params=unittest.mock.ANY, difficulty_dip_adjustment=Decimal('0.007')
        )

if __name__ == '__main__':
    unittest.main()
