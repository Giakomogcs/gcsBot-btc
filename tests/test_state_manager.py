import pytest
from unittest.mock import Mock, patch
from jules_bot.core_logic.state_manager import StateManager
from jules_bot.utils.config_manager import config_manager

@pytest.fixture
def mock_db_manager():
    """Provides a mock DatabaseManager instance."""
    return Mock()

@pytest.fixture
def state_manager(mock_db_manager):
    """
    Provides a StateManager instance with a mocked DatabaseManager.
    This fixture ensures that the real DatabaseManager is not used during tests.
    """
    # We use patch to temporarily replace the DatabaseManager class during instantiation
    with patch('jules_bot.core_logic.state_manager.DatabaseManager', return_value=mock_db_manager):
        sm = StateManager(bucket_name="test_bucket", bot_id="test_bot")
        sm.db_manager = mock_db_manager # Ensure the instance has the mock
        return sm

def test_create_new_position_calculation(state_manager, mock_db_manager):
    """
    Verify that `create_new_position` correctly calculates `sell_target_price`
    using the formula and parameters from the config.
    """
    # Arrange
    buy_result = {
        'price': 100.0,
        'qty': 1.0,
        'cummulative_quote_qty': 100.0,
        'order_id': 'test-order-123',
        'symbol': 'BTCUSDT'
    }

    # These values are pulled from the config.ini file
    commission_rate = config_manager.getfloat('STRATEGY_RULES', 'commission_rate')
    sell_factor = config_manager.getfloat('STRATEGY_RULES', 'sell_factor')
    target_profit = config_manager.getfloat('STRATEGY_RULES', 'target_profit')

    # Expected sell price based on the formula
    numerator = buy_result['price'] * (1 + commission_rate)
    denominator = sell_factor * (1 - commission_rate)
    break_even_price = numerator / denominator
    expected_sell_target = break_even_price * (1 + target_profit)

    # Act
    state_manager.create_new_position(buy_result)

    # Assert
    # 1. Ensure that the method to write to the database was called once
    mock_db_manager.write_trade.assert_called_once()

    # 2. Extract the data that was passed to the database write method
    call_args = mock_db_manager.write_trade.call_args[0][0]

    # 3. Verify the calculated sell_target_price is correct (using pytest.approx for float comparison)
    assert 'sell_target_price' in call_args
    assert call_args['sell_target_price'] == pytest.approx(expected_sell_target)

    # 4. Verify that other important data was passed through correctly
    assert call_args['price'] == buy_result['price']
    assert call_args['bot_id'] == "test_bot"

def test_get_last_purchase_price_with_open_positions(state_manager):
    """
    Test that `get_last_purchase_price` returns the price of the most recent trade
    when there are open positions.
    """
    # Arrange: Mock the return value of get_open_positions
    state_manager.get_open_positions = Mock(return_value=[
        {'time': '2023-01-01T12:00:00Z', 'purchase_price': 100.0},
        {'time': '2023-01-01T13:00:00Z', 'purchase_price': 105.0}, # Most recent
        {'time': '2023-01-01T11:00:00Z', 'purchase_price': 99.0}
    ])

    # Act
    last_price = state_manager.get_last_purchase_price()

    # Assert
    assert last_price == 105.0

def test_get_last_purchase_price_with_no_open_positions(state_manager):
    """
    Test that `get_last_purchase_price` returns infinity when there are no open positions
    to prevent accidental buy triggers.
    """
    # Arrange: Mock get_open_positions to return an empty list
    state_manager.get_open_positions = Mock(return_value=[])

    # Act
    last_price = state_manager.get_last_purchase_price()

    # Assert
    assert last_price == float('inf')
