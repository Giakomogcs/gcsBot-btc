import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from decimal import Decimal
from jules_bot.backtesting.engine import Backtester
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager

@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager for testing."""
    mock = MagicMock(spec=ConfigManager)
    
    config_data = {
        'STRATEGY_RULES': {
            'max_capital_per_trade_percent': '0.02',
            'base_usd_per_trade': '100.0',
            'commission_rate': '0.001',
            'sell_factor': '0.9',
            'target_profit': '0.05',
            'max_open_positions': '20',
            'trailing_stop_profit': '0.015'
        },
        'BACKTEST': {
            'initial_balance': '10000',
            'commission_fee': '0.001'
        },
        'APP': {
            'symbol': 'BTCUSDT',
            'strategy_name': 'test_strategy'
        },
        'REGIME_0': {
            'buy_dip_percentage': '0.01',
            'sell_rise_percentage': '0.01',
            'order_size_usd': '100.0'
        }
    }

    def get_section_side_effect(section_name):
        return config_data.get(section_name, {})

    def mock_get_side_effect(section, key, fallback=None):
        return config_data.get(section, {}).get(key, fallback)

    mock.get_section.side_effect = get_section_side_effect
    mock.get.side_effect = mock_get_side_effect
    
    return mock

@pytest.fixture
def mock_db_manager():
    """Provides a mock PostgresManager."""
    mock = MagicMock(spec=PostgresManager)
    
    price_data = {
        'timestamp': pd.to_datetime(['2023-01-01 12:00:00', '2023-01-01 12:01:00', '2023-01-01 12:02:00']),
        'open': [100, 101, 110], 'high': [101, 110, 111],
        'low': [99, 100, 109], 'close': [101, 110, 105],
        'volume': [10, 12, 15]
    }
    df = pd.DataFrame(price_data).set_index('timestamp')
    
    mock.get_price_data.return_value = df
    mock.get_trades_by_run_id.return_value = []
    return mock

@patch('jules_bot.backtesting.engine.Backtester._generate_and_save_summary')
def test_backtester_pnl_calculation(mock_summary, mock_config_manager, mock_db_manager):
    """
    Tests that the backtester correctly calculates P&L by preparing the data ahead of time.
    """
    # Arrange
    prepared_data = mock_db_manager.get_price_data.return_value.copy()
    prepared_data['ema_100'] = 100
    prepared_data['ema_20'] = 100
    prepared_data['bbl_20_2_0'] = 98
    prepared_data['atr_14'] = 0.1
    prepared_data['macd_diff_12_26_9'] = 0.1
    prepared_data['market_regime'] = 0

    with patch('jules_bot.backtesting.engine.config_manager', mock_config_manager), \
         patch('jules_bot.backtesting.engine.CapitalManager') as mock_capital_manager, \
         patch('jules_bot.core_logic.strategy_rules.StrategyRules.calculate_sell_target_price') as mock_sell_target:

        mock_capital_manager.return_value.get_buy_order_details.side_effect = [
                (Decimal('100.0'), 'TEST_MODE', 'test buy reason', 'uptrend', Decimal('0.0'))
            ] + [(Decimal('0'), 'HOLD', 'no signal', 'no_signal', Decimal('0.0'))] * (len(prepared_data) - 1)
        
        mock_capital_manager.return_value.difficulty_reset_timeout_hours = 2
        mock_sell_target.return_value = Decimal("110.0")

        backtester = Backtester(db_manager=mock_db_manager, data=prepared_data, config_manager=mock_config_manager)
        trade_logger_mock = backtester.trade_logger = MagicMock()

        # Act
        backtester.run()

        # Assert
        update_calls = [c for c in trade_logger_mock.method_calls if c[0] == 'update_trade']
        assert len(update_calls) == 1, "Expected one sell trade to be updated"
        
        sell_trade_data = update_calls[0][1][0]
        realized_pnl_usd = sell_trade_data.get('realized_pnl_usd')

        buy_price = Decimal("101.0")
        sell_price = Decimal("110.0")
        buy_amount_usdt = Decimal("100.0")
        commission_rate = Decimal("0.001")
        quantity_bought = buy_amount_usdt / buy_price
        buy_commission_usd = buy_amount_usdt * commission_rate
        sell_factor = Decimal("0.9")
        quantity_sold = quantity_bought * sell_factor
        sell_value_gross = quantity_sold * sell_price
        sell_commission_usd = sell_value_gross * commission_rate
        gross_pnl = (sell_price - buy_price) * quantity_sold
        buy_commission_prorated = (quantity_sold / quantity_bought) * buy_commission_usd if quantity_bought > 0 else Decimal('0')
        expected_pnl = gross_pnl - buy_commission_prorated - sell_commission_usd

        assert float(realized_pnl_usd) == pytest.approx(float(expected_pnl), rel=1e-9)
