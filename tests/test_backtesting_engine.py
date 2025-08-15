import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
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

@patch('jules_bot.backtesting.engine.add_all_features')
def test_backtester_pnl_calculation(mock_add_all_features, mock_config_manager, mock_db_manager):
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
        mock_sell_target.return_value = 110.0

        backtester = Backtester(db_manager=mock_db_manager, start_date="2023-01-01", end_date="2023-01-01")
        
        # We need to access the trade_logger to check the recorded PnL
        trade_logger_mock = backtester.trade_logger = MagicMock()

        # Act
        backtester.run()

        # Assert
        # The backtester should have called update_trade on the logger for the sell transaction.
        # We need to find that call and inspect the `realized_pnl_usd`.
        
        update_calls = [c for c in trade_logger_mock.method_calls if c[0] == 'update_trade']
        assert len(update_calls) == 1, "Expected one sell trade to be updated"
        
        sell_trade_data = update_calls[0][1][0]
        realized_pnl = sell_trade_data.get('realized_pnl_usd')

        # Manually calculate the expected PnL
        # From the data, buy price is 101 (close of first candle).
        # Sell price is 110 (close of second candle).
        # Commission is 0.1% (0.001)
        # Buy amount is $100 (base_usd_per_trade)
        # Quantity bought = 100 / 101 = 0.990099
        # Commission on buy = 100 * 0.001 = 0.1
        # Net cost of buy = 100.1
        # Quantity sold = 0.990099 * 0.9 = 0.891089
        
        # Let's use the formula from StrategyRules to be sure
        # realized_pnl = (sell_price * (1 - commission) - buy_price * (1 + commission)) * quantity_sold
        buy_price = 101.0  # From mock trader execute_buy
        sell_price = 110.0 # From mock trader execute_sell
        
        # MockTrader logic: buy_amount_usdt / price
        # buy_amount_usdt is min(10000 * 0.02, 100) = 100
        # quantity_bought = 100 / 101 = 0.9900990099
        quantity_bought = 100 / 101
        
        # sell_quantity = quantity_bought * sell_factor
        sell_factor = 0.9
        quantity_sold = quantity_bought * sell_factor

        commission_rate = 0.001
        expected_pnl = (sell_price * (1 - commission_rate) - buy_price * (1 + commission_rate)) * quantity_sold
        # expected_pnl = (110 * 0.999 - 101 * 1.001) * (0.990099 * 0.9)
        # expected_pnl = (109.89 - 101.101) * 0.891089
        # expected_pnl = 8.789 * 0.891089 = 7.832
        
        assert realized_pnl == pytest.approx(expected_pnl)
