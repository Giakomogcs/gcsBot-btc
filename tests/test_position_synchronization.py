import pytest
import pandas as pd
import uuid
from unittest.mock import Mock, patch, call
from datetime import datetime, timezone

# Add project root to path for imports
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from gcs_bot.core.position_manager import PositionManager

# --- Fixtures ---

@pytest.fixture
def mock_config():
    """Provides a mock config object with all necessary attributes for PositionManager."""
    config = Mock()
    # Values needed for PositionManager.__init__
    config.trading_strategy.triple_barrier.profit_mult = 2.0
    config.trading_strategy.triple_barrier.stop_mult = 1.0
    config.trading_strategy.dca_grid_spacing_percent = 5.0
    config.trading_strategy.partial_sell_percent = 90.0
    config.trading_strategy.consecutive_green_candles_for_entry = 3
    config.position_management.max_total_capital_allocation_percent = 80.0

    # Values for other methods that might be called, set to safe defaults
    config.dynamic_sizing.enabled = False
    config.backtest.commission_rate = 0.001
    config.trailing_profit.activation_percentage = 2.0
    config.trailing_profit.trailing_percentage = 0.5
    config.trading_strategy.minimum_profit_for_take_profit = 0.01

    return config

@pytest.fixture
def mock_db_manager():
    """Provides a mock database manager."""
    return Mock()

@pytest.fixture
def mock_logger():
    """Provides a mock logger."""
    return Mock()

@pytest.fixture
def mock_account_manager():
    """Provides a mock account manager."""
    return Mock()

@pytest.fixture
def position_manager(mock_config, mock_db_manager, mock_logger, mock_account_manager):
    """Provides a PositionManager instance with mocked dependencies."""
    return PositionManager(
        config=mock_config,
        db_manager=mock_db_manager,
        logger=mock_logger,
        account_manager=mock_account_manager
    )

# --- Test Cases ---

def test_synchronize_with_exchange_adopts_orphaned_trade(position_manager, mock_db_manager):
    """
    Tests that synchronize_with_exchange correctly identifies an orphaned trade
    from the exchange and creates a corresponding local position.
    """
    # --- Arrange ---

    # 1. Simulate no open positions in the local database
    mock_db_manager.get_open_positions.return_value = pd.DataFrame()

    # 2. Simulate a recent BUY trade from the exchange that is not in our DB
    exchange_trade_time = datetime.now(timezone.utc)
    recent_exchange_trades = pd.DataFrame({
        'id': [12345],
        'time': [int(exchange_trade_time.timestamp() * 1000)],
        'price': ['50000.0'],
        'qty': ['0.001'],
        'isBuyer': [True]
    })

    # 3. Simulate historical candle data with ATR values
    historical_data = pd.DataFrame({
        'atr_14': [100.0, 150.0, 200.0]
    }, index=pd.to_datetime([
        exchange_trade_time - pd.Timedelta(minutes=2),
        exchange_trade_time - pd.Timedelta(minutes=1),
        exchange_trade_time
    ], utc=True))

    # --- Act ---
    position_manager.synchronize_with_exchange(recent_exchange_trades, historical_data)

    # --- Assert ---

    # 1. Check that write_trade was called exactly once
    mock_db_manager.write_trade.assert_called_once()

    # 2. Inspect the data passed to write_trade
    call_args = mock_db_manager.write_trade.call_args[0]
    trade_data = call_args[0]

    # 3. Validate the reconstructed trade data
    assert trade_data['status'] == "OPEN"
    assert trade_data['entry_price'] == 50000.0
    assert trade_data['quantity_btc'] == 0.001

    # Check that profit/stop loss were calculated correctly using the ATR at the time of the trade
    # The `asof` method should pick the candle at or before the trade time.
    # Let's check the ATR value that should have been used.
    # The candle used by `asof` should be the one at `exchange_trade_time`.
    candle_used = historical_data.asof(pd.to_datetime(recent_exchange_trades['time'].iloc[0], unit='ms', utc=True))
    expected_atr = candle_used['atr_14']

    expected_profit_target = 50000.0 + (expected_atr * position_manager.profit_target_mult)
    expected_stop_loss = 50000.0 - (expected_atr * position_manager.stop_loss_mult)

    assert trade_data['profit_target_price'] == pytest.approx(expected_profit_target)
    assert trade_data['stop_loss_price'] == pytest.approx(expected_stop_loss)

    # 4. Validate the decision_data to ensure it's marked as a synced trade
    assert trade_data['decision_data']['reason'] == "SYNC_FROM_EXCHANGE"
    assert trade_data['decision_data']['binance_trade_id'] == 12345

def test_synchronize_with_exchange_ignores_existing_trade(position_manager, mock_db_manager):
    """
    Tests that synchronize_with_exchange does not re-create a position for a trade
    that already exists in the local database.
    """
    # --- Arrange ---

    # 1. Simulate an existing open position in the local database
    existing_trade_id = 12345
    open_positions = pd.DataFrame({
        'decision_data': [{'binance_trade_id': existing_trade_id}]
    })
    mock_db_manager.get_open_positions.return_value = open_positions

    # 2. Simulate the same trade appearing in the recent trades from the exchange
    exchange_trade_time = datetime.now(timezone.utc)
    recent_exchange_trades = pd.DataFrame({
        'id': [existing_trade_id],
        'time': [int(exchange_trade_time.timestamp() * 1000)],
        'price': ['50000.0'],
        'qty': ['0.001'],
        'isBuyer': [True]
    })

    # 3. Historical data (not strictly needed for this test's assertions but required by the function)
    historical_data = pd.DataFrame({'atr_14': [200.0]}, index=[exchange_trade_time])

    # --- Act ---
    position_manager.synchronize_with_exchange(recent_exchange_trades, historical_data)

    # --- Assert ---

    # Check that write_trade was NOT called, because the trade already exists
    mock_db_manager.write_trade.assert_not_called()
