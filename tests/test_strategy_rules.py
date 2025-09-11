import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.config_manager import ConfigManager

@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager for testing."""
    mock = MagicMock(spec=ConfigManager)
    config_values = {
        ('STRATEGY_RULES', 'max_capital_per_trade_percent'): '0.02',
        ('STRATEGY_RULES', 'base_usd_per_trade'): '100.0',
        ('STRATEGY_RULES', 'commission_rate'): '0.001',
        ('STRATEGY_RULES', 'sell_factor'): '0.9',
        ('STRATEGY_RULES', 'target_profit'): '0.005',
        ('STRATEGY_RULES', 'max_open_positions'): '20',
        ('STRATEGY_RULES', 'use_reversal_buy_strategy'): False,
        ('STRATEGY_RULES', 'trailing_stop_profit'): '0.10'
    }

    def get_side_effect(section, key, fallback=None):
        return config_values.get((section, key), fallback)

    def getboolean_side_effect(section, key, fallback=None):
        val = config_values.get((section, key), fallback)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ('true', '1', 't')

    mock.get.side_effect = get_side_effect
    mock.getboolean.side_effect = getboolean_side_effect
    return mock

def test_calculate_realized_pnl(mock_config_manager):
    """
    Tests the realized PnL calculation under different scenarios.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)

    # --- Scenario 1: Profitable Trade ---
    buy_price_profit = Decimal("100.0")
    sell_price_profit = Decimal("110.0")
    quantity_sold = Decimal("1.0")
    expected_pnl_profit = Decimal("9.79")

    # Act
    realized_pnl_profit = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_profit,
        sell_price=sell_price_profit,
        quantity_sold=quantity_sold,
        buy_commission_usd=Decimal('0.1'),
            sell_commission_usd=Decimal('0.11')
    )

    # Assert
    assert float(realized_pnl_profit) == pytest.approx(float(expected_pnl_profit))

    # --- Scenario 2: Losing Trade ---
    buy_price_loss = Decimal("100.0")
    sell_price_loss = Decimal("90.0")
    expected_pnl_loss = Decimal("-10.19") # Corrected expected PnL

    # Act
    realized_pnl_loss = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_loss,
        sell_price=sell_price_loss,
        quantity_sold=quantity_sold,
        buy_commission_usd=Decimal('0.1'),
            sell_commission_usd=Decimal('0.09')
    )

    # Assert
    assert float(realized_pnl_loss) == pytest.approx(float(expected_pnl_loss))

    # --- Scenario 3: Break-even Trade (considering commissions) ---
    buy_price_breakeven = Decimal("100.0")
    sell_price_breakeven = Decimal("100.2002002")

    # Act
    realized_pnl_breakeven = strategy_rules.calculate_realized_pnl(
        buy_price=buy_price_breakeven,
        sell_price=sell_price_breakeven,
        quantity_sold=quantity_sold,
        buy_commission_usd=Decimal('0.1'),
            sell_commission_usd=Decimal('0.1002002')
    )

    # Assert
    assert float(realized_pnl_breakeven) == pytest.approx(0.0, abs=1e-6)

def test_evaluate_buy_signal_with_difficulty_factor(mock_config_manager):
    """
    Tests that the buy signal becomes stricter with a higher difficulty factor.
    """
    # Arrange
    strategy_rules = StrategyRules(mock_config_manager)
    params = {'buy_dip_percentage': Decimal('0.02'), 'sell_rise_percentage': Decimal('0.01'), 'order_size_usd': Decimal('10')}
    # This data ensures the logic enters the 'downtrend' path (close < ema_100)
    market_data = {
        'close': '100.1', 'high': '101', 'ema_100': '110', 'ema_20': '105',
        'bbl_20_2_0': '100.0'
    }

    # --- Scenario 1: No difficulty, price is NOT below BBL -> No Signal ---
    should_buy, _, reason = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=Decimal('0'), params=params)
    assert not should_buy
    assert "Price is too high" in reason

    # --- Scenario 2: No difficulty, price IS below BBL -> Signal ---
    market_data['close'] = '99.9'
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=Decimal('0'), params=params)
    assert should_buy

    # --- Scenario 3: With difficulty, price is NOT below adjusted BBL -> No Signal ---
    # Adjusted BBL = 100.0 * (1 - 0.005) = 99.5
    market_data['close'] = '99.6'
    should_buy, _, reason = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=Decimal('0.005'), params=params)
    assert not should_buy
    assert "Price is too high" in reason

    # --- Scenario 4: With difficulty, price IS below adjusted BBL -> Signal ---
    market_data['close'] = '99.4'
    should_buy, _, _ = strategy_rules.evaluate_buy_signal(market_data, 1, difficulty_factor=Decimal('0.005'), params=params)
    assert should_buy

class TestSmartTrail:
    @pytest.fixture
    def strategy_rules(self, mock_config_manager):
        """Provides StrategyRules with default settings for smart trail."""
        # Ensure the mock returns specific values needed for these tests
        mock_config_manager.getboolean.return_value = True # Enable dynamic trail
        mock_config_manager.get.side_effect = lambda section, key, fallback: {
            'trailing_stop_profit': '0.10',
            'use_dynamic_trailing_stop': 'True',
            'dynamic_trail_min_pct': '0.01',
            'dynamic_trail_max_pct': '0.05',
            'dynamic_trail_profit_scaling': '0.1'
        }.get(key, fallback)

        return StrategyRules(mock_config_manager)

    def test_update_peak_has_threshold(self, strategy_rules):
        """
        Tests that UPDATE_PEAK is not triggered for tiny PnL increases,
        but is triggered for significant ones.
        """
        position = {
            'is_smart_trailing_active': True,
            'smart_trailing_highest_profit': Decimal('0.20'), # 20 cents profit peak
            'current_trail_percentage': Decimal('0.033'), # Assume a trail is set
            'price': '100', # dummy values
            'quantity': '1' # dummy values
        }

        # Scenario 1: Tiny PnL increase (less than 0.5%)
        # 0.2001 is a 0.05% increase, which is below the 0.5% threshold
        small_increase_pnl = Decimal('0.2001')
        decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, small_increase_pnl)

        # The decision should be HOLD, not UPDATE_PEAK
        assert decision == "HOLD"
        assert "Monitoring active trail" in reason

        # Scenario 2: Significant PnL increase (more than 0.5%)
        # 0.21 is a 5% increase
        large_increase_pnl = Decimal('0.21')
        decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, large_increase_pnl)

        assert decision == "UPDATE_PEAK"
        assert "New profit peak" in reason
