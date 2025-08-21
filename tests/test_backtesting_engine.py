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
    # Add SessionLocal attribute to the mock to prevent AttributeError in StateManager
    mock.SessionLocal = MagicMock()
    return mock

@patch('jules_bot.core_logic.state_manager.StateManager.record_partial_sell')
@patch('jules_bot.backtesting.engine.add_all_features')
def test_backtester_pnl_calculation(mock_add_all_features, mock_record_partial_sell, mock_config_manager, mock_db_manager):
    """
    Tests that the backtester correctly calculates P&L and passes it to the StateManager.
    """
    # Arrange
    feature_data = mock_db_manager.get_price_data.return_value.copy()
    feature_data['ema_100'] = 100
    feature_data['ema_20'] = 100
    feature_data['bbl_20_2_0'] = 98
    mock_add_all_features.return_value = feature_data

    # This mock position will be "returned" by the db_manager after the first (buy) loop
    mock_position = MagicMock()
    mock_position.trade_id = "test-trade-id"
    mock_position.price = Decimal("101.0")
    mock_position.quantity = (Decimal("100.0") - (Decimal("100.0") * Decimal("0.001"))) / Decimal("101.0")
    mock_position.sell_target_price = Decimal("110.0")

    # The db_manager will return no positions at first, then the new position
    mock_db_manager.get_open_positions.side_effect = [
        [],  # First call in loop 1
        [],  # Second call in loop 1 (for dynamic capital check)
        [mock_position], # First call in loop 2
        [mock_position], # Second call in loop 2
        [mock_position], # First call in loop 3
        [mock_position], # Second call in loop 3
    ]

    # Patch the global config_manager and other methods
    with patch('jules_bot.backtesting.engine.config_manager', mock_config_manager), \
         patch('jules_bot.core_logic.strategy_rules.StrategyRules.evaluate_buy_signal') as mock_buy_signal, \
         patch('jules_bot.core_logic.strategy_rules.StrategyRules.calculate_sell_target_price') as mock_sell_target, \
         patch('jules_bot.backtesting.engine.Backtester._generate_and_save_summary'): # Patch summary to avoid db calls

        # Mock buy signal to fire once, then no more signals
        mock_buy_signal.side_effect = [(True, 'uptrend', 'test_buy')] + [(False, '', '')] * (len(feature_data) - 1)
        mock_sell_target.return_value = Decimal("110.0") # Sell at the second candle

        # Act
        backtester = Backtester(db_manager=mock_db_manager, start_date="2023-01-01", end_date="2023-01-01")
        backtester.run()

        # Assert
        mock_record_partial_sell.assert_called_once()
        
        # Extract the sell_data from the mock call
        call_args = mock_record_partial_sell.call_args[1]
        sell_data = call_args['sell_data']
        realized_pnl = sell_data.get('realized_pnl_usd')

        # Manually calculate the expected PnL
        buy_price = Decimal("101.0")
        sell_price = Decimal("110.0")
        
        # From the mocked config
        buy_amount_usdt = Decimal("100.0")
        commission_rate = Decimal("0.001")

        # This is the quantity that would have been bought, as calculated by MockTrader
        quantity_bought = (buy_amount_usdt - (buy_amount_usdt * commission_rate)) / buy_price
        
        sell_factor = Decimal("0.9")
        quantity_sold = quantity_bought * sell_factor

        one = Decimal("1")
        # PnL calculation is based on the sell quantity
        expected_pnl = (sell_price * (one - commission_rate) - buy_price * (one + commission_rate)) * quantity_sold

        assert realized_pnl == pytest.approx(expected_pnl)
