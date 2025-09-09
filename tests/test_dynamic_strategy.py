import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.config_manager import ConfigManager

# Default position data for tests
DEFAULT_POSITION = {
    'trade_id': 'test_trade_123',
    'price': '100',
    'quantity': '1',
    'commission_usd': '0.1',
    'is_smart_trailing_active': False,
    'smart_trailing_highest_profit': None,
    'current_trail_percentage': None
}

@pytest.fixture
def mock_config_manager_dynamic_trail():
    """Provides a mock ConfigManager with dynamic trailing stop enabled."""
    mock = MagicMock(spec=ConfigManager)
    config_values = {
        ('STRATEGY_RULES', 'commission_rate'): '0.001',
        ('STRATEGY_RULES', 'trailing_stop_profit'): '10.0', # PnL in USD
        ('STRATEGY_RULES', 'use_dynamic_trailing_stop'): 'true',
        ('STRATEGY_RULES', 'dynamic_trail_min_pct'): '0.01', # 1%
        ('STRATEGY_RULES', 'dynamic_trail_max_pct'): '0.05', # 5%
        ('STRATEGY_RULES', 'dynamic_trail_profit_scaling'): '0.1',
        ('STRATEGY_RULES', 'dynamic_trail_percentage'): '0.02', # Legacy key for fixed trail
        ('STRATEGY_RULES', 'sell_factor'): '1.0',
        ('STRATEGY_RULES', 'max_capital_per_trade_percent'): '0.02',
        ('STRATEGY_RULES', 'base_usd_per_trade'): '100.0',
        ('STRATEGY_RULES', 'use_reversal_buy_strategy'): False,
    }

    def get_side_effect(section, key, fallback=None):
        return config_values.get((section, key), fallback)

    def getboolean_side_effect(section, key, fallback=None):
        val = str(config_values.get((section, key), fallback)).lower()
        return val in ('true', '1', 't')

    mock.get.side_effect = get_side_effect
    mock.getboolean.side_effect = getboolean_side_effect
    return mock

@pytest.fixture
def strategy_rules(mock_config_manager_dynamic_trail):
    """Provides a StrategyRules instance with the mock config."""
    return StrategyRules(mock_config_manager_dynamic_trail)

def test_activation(strategy_rules):
    """Test that the trailing stop activates when profit target is met."""
    position = DEFAULT_POSITION.copy()
    
    # PnL is below target
    decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('9.0'))
    assert decision == "HOLD"

    # PnL meets target
    decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('10.0'))
    assert decision == "ACTIVATE"
    assert "activated" in reason

def test_deactivation_when_unprofitable(strategy_rules):
    """Test that an active trail deactivates if the position becomes unprofitable."""
    position = {**DEFAULT_POSITION, 'is_smart_trailing_active': True, 'smart_trailing_highest_profit': '15.0'}
    
    decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('-1.0'))
    assert decision == "DEACTIVATE"
    assert "unprofitable" in reason

def test_peak_profit_update(strategy_rules):
    """Test that a new peak profit is correctly identified."""
    position = {**DEFAULT_POSITION, 'is_smart_trailing_active': True, 'smart_trailing_highest_profit': '12.0'}

    decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('15.0'))
    assert decision == "UPDATE_PEAK"
    assert "New profit peak" in reason

def test_dynamic_trail_calculation_and_update(strategy_rules):
    """Test that the dynamic trail percentage is calculated and updated correctly."""
    position = {
        **DEFAULT_POSITION, 
        'is_smart_trailing_active': True, 
        'smart_trailing_highest_profit': '10.0', # 10% profit on a $100 trade
        'current_trail_percentage': '0.01' # Initial trail
    }

    # New peak profit is 20 USD (20% of 100)
    # Expected new trail = min_pct + (profit_pct * scaling) = 0.01 + (0.20 * 0.1) = 0.01 + 0.02 = 0.03 (3%)
    decision, reason, new_trail = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('20.0'))
    
    assert decision == "UPDATE_PEAK"
    assert new_trail is not None
    assert float(new_trail) == pytest.approx(0.03)
    assert "Trail updated to 3.00%" in reason

def test_trail_does_not_shrink(strategy_rules):
    """Test that the trail percentage does not decrease if a new peak profit results in a smaller trail (should not happen with current formula, but good to test)."""
    position = {
        **DEFAULT_POSITION,
        'is_smart_trailing_active': True,
        'smart_trailing_highest_profit': '30.0', # 30% profit
        'current_trail_percentage': '0.04' # Current trail is 4%
    }
    
    # We manually set a higher current trail to simulate a scenario.
    # A new peak of 31 should result in a calculated trail of 0.01 + (0.31 * 0.1) = 0.041
    decision, reason, new_trail = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('31.0'))
    
    assert decision == "UPDATE_PEAK"
    assert new_trail is not None
    assert float(new_trail) > float(position['current_trail_percentage'])

    # Now, let's test if profit drops, the trail stored in the position is used, not recalculated lower.
    # The stored trail is 4.1%. The stop loss target should be based on this.
    # Stop level = 31 * (1 - 0.041) = 29.729
    position['smart_trailing_highest_profit'] = '31.0'
    position['current_trail_percentage'] = str(new_trail)

    decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('30.0'))
    assert decision == "HOLD" # Price is above stop level
    assert "Stop Target: $29.73" in reason # Check the calculation uses the correct trail

def test_sell_trigger(strategy_rules):
    """Test that a sell is triggered when the PnL drops to the stop level."""
    position = {
        **DEFAULT_POSITION,
        'is_smart_trailing_active': True,
        'smart_trailing_highest_profit': '20.0', # 20 USD profit
        'current_trail_percentage': '0.03' # 3% trail
    }

    # Stop profit level = 20.0 * (1 - 0.03) = 19.4
    # The activation target is 10.0, so the final trigger is max(19.4, 10.0) = 19.4
    
    # PnL is above the stop level
    decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('19.5'))
    assert decision == "HOLD"

    # PnL hits the stop level
    decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('19.4'))
    assert decision == "SELL"
    assert "sell triggered" in reason

    # PnL drops below the stop level
    decision, reason, _ = strategy_rules.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('19.3'))
    assert decision == "SELL"

def test_fallback_to_fixed_trail(mock_config_manager_dynamic_trail, strategy_rules):
    """Test that the system uses the fixed percentage if dynamic is disabled."""
    # Disable dynamic trailing
    mock_config_manager_dynamic_trail.getboolean.side_effect = lambda section, key, fallback: False
    
    # Re-initialize strategy rules with the modified config
    strategy_rules_fixed = StrategyRules(mock_config_manager_dynamic_trail)
    strategy_rules_fixed.fixed_trail_percentage = Decimal('0.02') # Manually set for clarity

    position = {
        **DEFAULT_POSITION,
        'is_smart_trailing_active': True,
        'smart_trailing_highest_profit': '20.0'
    }

    # Stop profit level = 20.0 * (1 - 0.02) = 19.6
    decision, reason, new_trail = strategy_rules_fixed.evaluate_smart_trailing_stop(position, net_unrealized_pnl=Decimal('19.5'))
    
    assert decision == "SELL"
    assert new_trail is None # No new trail should be calculated
    assert "Trail: 2.00%" in reason
