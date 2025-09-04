import unittest
from unittest.mock import MagicMock, patch
from decimal import Decimal
import time
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

        amount, mode, reason, _, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            market_regime=1, # UPTREND
            open_positions=[MagicMock()] * 10, # 10 open positions, which is the max
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(amount, Decimal('0'))
        self.assertEqual(mode, OperatingMode.PRESERVATION.name)
        self.assertIn("Máximo de posições abertas (10) atingido", reason)

    def test_preservation_mode_when_no_buy_signal(self):
        """Should not buy if there is no buy signal."""
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (False, "NO_TRADE", "No signal")

        amount, mode, reason, _, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            market_regime=1, # UPTREND
            open_positions=[],
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(amount, Decimal('0'))
        self.assertEqual(mode, OperatingMode.PRESERVATION.name)
        self.assertEqual(reason, "No signal")
        # Verify it was called with the correct signature
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 1, 0, Decimal('0'), params=self.params)

    def test_accumulation_mode_logic(self):
        """Should return base trade size in ACCUMULATION mode."""
        self.config_values[('STRATEGY_RULES', 'use_dynamic_capital')] = True
        self.capital_manager = CapitalManager(self.mock_config_manager, self.mock_strategy_rules)
        # Regime is UPTREND (1), but open positions are > max/4, so it should be ACCUMULATION not AGGRESSIVE
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "A standard buy signal")

        amount, mode, reason, _, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            market_regime=1, # UPTREND
            open_positions=[MagicMock()] * 6, # More than max_open_positions / 4
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params,
            trade_history=[]
        )

        self.assertEqual(mode, OperatingMode.ACCUMULATION.name)
        self.assertEqual(amount, Decimal('20.00'))
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 1, 6, ANY, params=self.params)


    def test_aggressive_mode_logic(self):
        """Should return multiplied trade size in AGGRESSIVE mode."""
        self.config_values[('STRATEGY_RULES', 'use_dynamic_capital')] = True
        self.capital_manager = CapitalManager(self.mock_config_manager, self.mock_strategy_rules)
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "Strong uptrend signal")

        amount, mode, reason, _, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            market_regime=1, # UPTREND
            open_positions=[MagicMock()] * 2, # 2 is less than 10/4=2.5
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(mode, OperatingMode.AGGRESSIVE.name)
        self.assertEqual(amount, Decimal('40.00')) # 20 * 2.0
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 1, 2, ANY, params=self.params)

    def test_correction_entry_mode_logic(self):
        """Should return larger trade size for a correction entry."""
        self.config_values[('STRATEGY_RULES', 'use_dynamic_capital')] = True
        self.capital_manager = CapitalManager(self.mock_config_manager, self.mock_strategy_rules)
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "downtrend", "Potential bottom signal")

        amount, mode, reason, _, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            market_regime=3, # DOWNTREND
            open_positions=[], # 0 open positions
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(mode, OperatingMode.CORRECTION_ENTRY.name)
        self.assertEqual(amount, Decimal('50.00')) # 20 * 2.5
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 3, 0, ANY, params=self.params)

    def test_insufficient_funds_logic(self):
        """Should not buy if free cash is less than the calculated amount."""
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "uptrend", "A valid signal")

        amount, mode, reason, _, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            market_regime=1, # UPTREND
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
        self.mock_strategy_rules.evaluate_buy_signal.return_value = (True, "ranging", "A valid signal")

        amount, mode, reason, _, _ = self.capital_manager.get_buy_order_details(
            market_data={},
            market_regime=0, # RANGING
            open_positions=[MagicMock()],
            portfolio_value=Decimal('1000'),
            free_cash=Decimal('100'),
            params=self.params
        )

        self.assertEqual(amount, Decimal('0'))
        self.assertEqual(mode, OperatingMode.PRESERVATION.name)
        self.assertIn("below min trade size", reason)
        self.mock_strategy_rules.evaluate_buy_signal.assert_called_with({}, 0, 1, ANY, params=self.params)

if __name__ == '__main__':
    unittest.main()

from unittest.mock import ANY

class TestConsecutiveBuyDifficulty(unittest.TestCase):
    def setUp(self):
        self.mock_config_manager = MagicMock()
        self.mock_strategy_rules = MagicMock(spec=StrategyRules)

        self.config_values = {
            ('STRATEGY_RULES', 'use_dynamic_capital'): True,
            ('STRATEGY_RULES', 'consecutive_buys_threshold'): '5',
            ('STRATEGY_RULES', 'difficulty_reset_timeout_hours'): '2',
            ('STRATEGY_RULES', 'base_difficulty_percentage'): '0.005', # 0.5%
            ('STRATEGY_RULES', 'per_buy_difficulty_increment'): '0.001' # 0.1%
        }
        self.mock_config_manager.get.side_effect = self.get_config_value
        self.mock_config_manager.getboolean.side_effect = self.get_config_boolean_value

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

    def test_no_difficulty_below_threshold(self):
        """Should have zero difficulty factor with fewer than threshold open positions."""
        open_positions = [MagicMock()] * 4 # 4 positions < 5 threshold
        difficulty = self.capital_manager._calculate_difficulty_factor(open_positions)
        self.assertEqual(difficulty, Decimal('0'))

    def test_base_difficulty_at_threshold(self):
        """Should have base difficulty factor with exactly threshold open positions."""
        open_positions = [MagicMock()] * 5 # 5 positions == 5 threshold
        difficulty = self.capital_manager._calculate_difficulty_factor(open_positions)
        # buys_over_threshold = 5 - 5 = 0. Difficulty = base + 0 * increment
        self.assertEqual(difficulty, Decimal('0.005'))

    def test_difficulty_increments_above_threshold(self):
        """Should have increased difficulty factor for each position over threshold."""
        open_positions = [MagicMock()] * 7 # 7 positions > 5 threshold
        difficulty = self.capital_manager._calculate_difficulty_factor(open_positions)
        # buys_over_threshold = 7 - 5 = 2. Difficulty = base + 2 * increment
        # 0.005 + 2 * 0.001 = 0.007
        self.assertEqual(difficulty, Decimal('0.007'))
