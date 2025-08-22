import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.utils.config_manager import ConfigManager

@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager for testing."""
    mock = MagicMock(spec=ConfigManager)
    def get_section_side_effect(section_name):
        if section_name == 'STRATEGY_RULES':
            return {
                'commission_rate': '0.001',
                'sell_factor': '1',
            }
        return {}
    mock.get_section.side_effect = get_section_side_effect
    return mock

def test_calculate_sell_target_price_with_dynamic_params(mock_config_manager):
    """
    Tests that the sell target price is calculated correctly using a dynamic target_profit.
    """
    strategy_rules = StrategyRules(mock_config_manager)
    purchase_price = Decimal("100.0")

    # --- Scenario 1: Regime 0 with low target_profit ---
    params_regime_0 = {'target_profit': Decimal('0.005')} # 0.5%
    # Expected: (100 * 1.001 / 0.999) * 1.005 = 100.2002 * 1.005 = 100.7012
    expected_sell_price_0 = Decimal("100.7012")

    sell_target_0 = strategy_rules.calculate_sell_target_price(purchase_price, params=params_regime_0)
    assert float(sell_target_0) == pytest.approx(float(expected_sell_price_0), abs=1e-4)

    # --- Scenario 2: Regime 2 with high target_profit ---
    params_regime_2 = {'target_profit': Decimal('0.02')} # 2%
    # Expected: 100.2002 * 1.02 = 102.2042
    expected_sell_price_2 = Decimal("102.2042")

    sell_target_2 = strategy_rules.calculate_sell_target_price(purchase_price, params=params_regime_2)
    assert float(sell_target_2) == pytest.approx(float(expected_sell_price_2), abs=1e-4)

def test_evaluate_buy_signal_dip_buying(mock_config_manager):
    """
    Tests the new dip-buying logic in evaluate_buy_signal.
    """
    strategy_rules = StrategyRules(mock_config_manager)

    # Base market data for an uptrend pullback scenario
    market_data = {
        'high': 105.0, 'ema_100': 100.0, 'ema_20': 102.0, 'bbl_20_2_0': 98.0,
        'close': 102.5 # Price has not dipped yet
    }

    params = {'buy_dip_percentage': Decimal('0.02')} # 2% dip

    # --- Scenario 1: Price has not dipped enough -> No Signal ---
    # Dip target is 105 * (1 - 0.02) = 102.9. Current price 103.0 is above.
    market_data['close'] = 103.0
    should_buy, _, reason = strategy_rules.evaluate_buy_signal(market_data, 1, params=params)
    assert not should_buy
    assert "Dip buy signal" not in reason

    # --- Scenario 2: Price has dipped below the target -> Signal ---
    # Current price 102.8 is below the 102.9 target
    market_data['close'] = 102.8
    should_buy, _, reason = strategy_rules.evaluate_buy_signal(market_data, 1, params=params)
    assert should_buy
    assert "Dip buy signal" in reason
