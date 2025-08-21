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
    def get_section_side_effect(section_name):
        if section_name == 'STRATEGY_RULES':
            return {
                'max_capital_per_trade_percent': '0.02',
                'base_usd_per_trade': '100.0',
                'commission_rate': '0.001',
                'sell_factor': '0.9',
                'target_profit': '0.05',
                'max_open_positions': '20'
            }
        if section_name == 'BACKTEST':
            return {
                'initial_balance': '10000',
                'commission_fee': '0.001'
            }
        if section_name == 'APP':
            return {
                'symbol': 'BTCUSDT',
                'strategy_name': 'test_strategy'
            }
        return {}
    mock.get_section.side_effect = get_section_side_effect
    mock.get.side_effect = lambda section, key, **kwargs: get_section_side_effect(section).get(key, kwargs.get('fallback'))
    return mock

@pytest.fixture
def mock_db_manager():
    """Provides a mock PostgresManager."""
    mock = MagicMock(spec=PostgresManager)
    
    # Create a simple DataFrame for price data
    price_data = {
        'timestamp': pd.to_datetime(['2023-01-01 12:00:00', '2023-01-01 12:01:00', '2023-01-01 12:02:00']),
        'open': [100, 101, 110],
        'high': [101, 110, 111],
        'low': [99, 100, 109],
        'close': [101, 110, 105], # Buy at 101, sell at 110
        'volume': [10, 12, 15]
    }
    df = pd.DataFrame(price_data).set_index('timestamp')
    
    mock.get_price_data.return_value = df
    mock.get_trades_by_run_id.return_value = []
    return mock

@patch('jules_bot.backtesting.engine.Backtester._generate_and_save_summary')
@patch('jules_bot.backtesting.engine.add_all_features')
def test_backtester_pnl_calculation(mock_add_all_features, mock_summary, mock_config_manager, mock_db_manager):
    """
    Tests that the backtester correctly calculates P&L using the StrategyRules method.
    """
    # Arrange
    # The mock feature data needs all columns the backtester expects
    feature_data = mock_db_manager.get_price_data.return_value.copy()
    feature_data['ema_100'] = 100
    feature_data['ema_20'] = 100
    feature_data['bbl_20_2_0'] = 98
    mock_add_all_features.return_value = feature_data

    # We need to patch the global config_manager used by the Backtester
    with patch('jules_bot.backtesting.engine.config_manager', mock_config_manager), \
         patch('jules_bot.core_logic.strategy_rules.StrategyRules.evaluate_buy_signal') as mock_buy_signal, \
         patch('jules_bot.core_logic.strategy_rules.StrategyRules.calculate_sell_target_price') as mock_sell_target:

        # Mock to buy only on the first call
        mock_buy_signal.side_effect = [(True, 'uptrend', 'test_buy_signal')] + [(False, '', '')] * (len(feature_data) - 1)

        # Sell if price is >= 110 (the close of the second candle)
        mock_sell_target.return_value = Decimal("110.0")

        backtester = Backtester(db_manager=mock_db_manager, start_date="2023-01-01", end_date="2023-01-01")

        trade_logger_mock = backtester.trade_logger = MagicMock()

        # Act
        backtester.run()

        # Assert
        update_calls = [c for c in trade_logger_mock.method_calls if c[0] == 'update_trade']
        assert len(update_calls) == 1, "Expected one sell trade to be updated"
        
        sell_trade_data = update_calls[0][1][0]
        realized_pnl = sell_trade_data.get('realized_pnl_usd')

        # Manually calculate the expected PnL using Decimal
        buy_price = Decimal("101.0")
        sell_price = Decimal("110.0")

        buy_amount_usdt = Decimal("100.0")
        quantity_bought = buy_amount_usdt / buy_price

        sell_factor = Decimal("0.9")
        quantity_sold = quantity_bought * sell_factor

        commission_rate = Decimal("0.001")
        one = Decimal("1")

        expected_pnl = (sell_price * (one - commission_rate) - buy_price * (one + commission_rate)) * quantity_sold
        
        assert realized_pnl == pytest.approx(expected_pnl)
