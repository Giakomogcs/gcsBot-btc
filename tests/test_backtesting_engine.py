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
    # Add the columns required by the new SituationalAwareness model
    feature_data['atr_14'] = 0.1
    feature_data['macd_diff_12_26_9'] = 0.1
    mock_add_all_features.return_value = feature_data

    # We need to patch the global config_manager and the CapitalManager used by the Backtester
    with patch('jules_bot.backtesting.engine.config_manager', mock_config_manager), \
         patch('jules_bot.backtesting.engine.CapitalManager') as mock_capital_manager, \
         patch('jules_bot.core_logic.strategy_rules.StrategyRules.calculate_sell_target_price') as mock_sell_target:

        # Configure the mock CapitalManager to return a buy decision only on the first cycle
        # The method now returns 5 values, so we update the mock.
        mock_capital_manager.return_value.get_buy_order_details.side_effect = [
            (Decimal('100.0'), 'TEST_MODE', 'test buy reason', 'uptrend', Decimal('0'))
        ] + [(Decimal('0'), 'HOLD', 'no signal', 'no_trade', Decimal('0'))] * (len(feature_data) - 1)

        # Sell if price is >= 110 (the close of the second candle)
        mock_sell_target.return_value = Decimal("110.0")

        backtester = Backtester(db_manager=mock_db_manager, start_date="2023-01-01", end_date="2023-01-01")
        
        trade_logger_mock = backtester.trade_logger = MagicMock()

        # Act
        backtester.run()

        # Assert
        log_trade_calls = [c for c in trade_logger_mock.method_calls if c[0] == 'log_trade']
        
        # We expect two calls: one for the initial buy, one for the sell.
        assert len(log_trade_calls) == 2, "Expected a buy and a sell trade to be logged"

        # The sell trade is the second one logged.
        sell_trade_data = log_trade_calls[1][0][0] # The argument is the trade dict itself
        assert sell_trade_data['order_type'] == 'sell'
        realized_pnl_usd = sell_trade_data.get('realized_pnl_usd')

        # Manually calculate the expected PnL using the same logic as the application
        buy_price = Decimal("101.0")
        sell_price = Decimal("110.0")
        buy_amount_usdt = Decimal("100.0")
        commission_rate = Decimal("0.001")

        # Buy side
        quantity_bought = buy_amount_usdt / buy_price
        buy_commission_usd = buy_amount_usdt * commission_rate

        # Sell side
        sell_factor = Decimal("0.9")
        quantity_sold = quantity_bought * sell_factor
        sell_value_gross = quantity_sold * sell_price
        sell_commission_usd = sell_value_gross * commission_rate

        # PnL Calculation (mirroring the logic in StrategyRules.calculate_realized_pnl)
        gross_pnl = (sell_price - buy_price) * quantity_sold
        buy_commission_prorated = (quantity_sold / quantity_bought) * buy_commission_usd if quantity_bought > 0 else Decimal('0')
        expected_pnl = gross_pnl - buy_commission_prorated - sell_commission_usd

        assert float(realized_pnl_usd) == pytest.approx(float(expected_pnl), rel=1e-9)
