import unittest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from jules_bot.core_logic.capital_manager import CapitalManager, OperatingMode
from jules_bot.core_logic.strategy_rules import StrategyRules

class TestCapitalManager(unittest.TestCase):
    def setUp(self):
        self.mock_config_manager = MagicMock()
        self.mock_strategy_rules = MagicMock(spec=StrategyRules)

        # Configure mock config values
        self.config_values = {
            ('TRADING_STRATEGY', 'min_trade_size_usdt'): '10.0',
            ('STRATEGY_RULES', 'base_usd_per_trade'): '20.0',
            ('STRATEGY_RULES', 'aggressive_buy_multiplier'): '2.0',
            ('STRATEGY_RULES', 'correction_entry_multiplier'): '2.5',
            ('STRATEGY_RULES', 'max_open_positions'): '10',
            ('STRATEGY_RULES', 'use_percentage_based_sizing'): False,
            ('STRATEGY_RULES', 'order_size_free_cash_percentage'): '0.1',
            'use_dynamic_difficulty': False # Default to off
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
        return self.config_values.get((section, key), fallback)

    def test_hard_limit_when_dynamic_difficulty_is_off(self):
        """Should hit the hard max positions limit when dynamic difficulty is off."""
        self.config_values[('STRATEGY_RULES', 'use_dynamic_capital')] = False
        self.capital_manager = CapitalManager(self.mock_config_manager, self.mock_strategy_rules)

        amount, mode, reason, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[MagicMock()] * 10, # 10 open positions, which is the max
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(amount, Decimal('0'))
        self.assertEqual(mode, OperatingMode.PRESERVATION.name)
        self.assertIn("Max open positions (10) reached", reason)

    def test_scaling_difficulty_when_dynamic_difficulty_is_on(self):
        """Should calculate a scaling difficulty factor when dynamic difficulty is on."""
        self.config_values[('STRATEGY_RULES', 'use_dynamic_capital')] = True
        self.capital_manager = CapitalManager(self.mock_config_manager, self.mock_strategy_rules)
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (False, "unknown", "No signal")

        # Test with 12 open positions, expecting a difficulty factor of 2 (12 // 5)
        self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[MagicMock()] * 12,
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 12, 2, params=self.params)

    def test_preservation_mode_when_no_buy_signal(self):
        """Should not buy if there is no buy signal."""
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (False, "unknown", "No signal")

        amount, mode, reason, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[],
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(amount, Decimal('0'))
        self.assertEqual(mode, OperatingMode.PRESERVATION.name)
        # self.assertEqual(reason, "No signal")
        # Verify it was called with difficulty 0
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 0, 0, params=self.params)

    def test_accumulation_mode_logic(self):
        """Should return base trade size in ACCUMULATION mode."""
        self.config_values[('STRATEGY_RULES', 'use_dynamic_capital')] = True
        self.capital_manager = CapitalManager(self.mock_config_manager, self.mock_strategy_rules)
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "A standard buy signal")

        amount, mode, reason, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[MagicMock()] * 5, # 5 positions should trigger difficulty 1
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(mode, OperatingMode.ACCUMULATION.name)
        self.assertEqual(amount, Decimal('20.00'))
        # Verify it was called with difficulty 1
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 5, 1, params=self.params)

    def test_aggressive_mode_logic(self):
        """Should return multiplied trade size in AGGRESSIVE mode."""
        self.config_values[('STRATEGY_RULES', 'use_dynamic_capital')] = True
        self.capital_manager = CapitalManager(self.mock_config_manager, self.mock_strategy_rules)
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "Strong uptrend signal")

        amount, mode, reason, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[MagicMock()] * 2, # 2 is less than 10/4=2.5, difficulty 0
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(mode, OperatingMode.AGGRESSIVE.name)
        self.assertEqual(amount, Decimal('40.00')) # 20 * 2.0
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 2, 0, params=self.params)

    def test_correction_entry_mode_logic(self):
        """Should return larger trade size for a correction entry."""
        self.config_values[('STRATEGY_RULES', 'use_dynamic_capital')] = True
        self.capital_manager = CapitalManager(self.mock_config_manager, self.mock_strategy_rules)
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "downtrend", "Potential bottom signal")

        amount, mode, reason, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[], # 0 open positions, difficulty 0
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(mode, OperatingMode.CORRECTION_ENTRY.name)
        self.assertEqual(amount, Decimal('50.00')) # 20 * 2.5
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 0, 0, params=self.params)

    def test_insufficient_funds_logic(self):
        """Should not buy if free cash is less than the calculated amount."""
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "A valid signal")

        amount, mode, reason, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[],
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('15.0'), # Less than base_usd_per_trade
            params=self.params
        )

        self.assertEqual(amount, Decimal('0'))
        self.assertEqual(mode, OperatingMode.PRESERVATION.name)
        self.assertIn("Insufficient funds", reason)

    def test_below_minimum_trade_size_logic(self):
        """Should not buy if calculated amount is below min_trade_size."""
        self.capital_manager.min_trade_size = Decimal('25.0')
        self.params['order_size_usd'] = Decimal('20.0')
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "accumulation", "A valid signal")

        amount, mode, reason, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            open_positions=[MagicMock()],
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(amount, Decimal('0'))
        self.assertEqual(mode, OperatingMode.PRESERVATION.name)
        self.assertIn("below min trade size", reason)
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 1, 0, params=self.params)

if __name__ == '__main__':
    unittest.main()
