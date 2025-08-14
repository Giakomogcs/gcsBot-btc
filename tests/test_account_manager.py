import pytest
import sys
import os
from unittest.mock import Mock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.bot.account_manager import AccountManager
from binance.exceptions import BinanceAPIException
from jules_bot.utils.config_manager import config_manager as real_config_manager

@pytest.fixture
def mock_binance_client():
    """Pytest fixture for a mocked Binance client."""
    return Mock()

@pytest.fixture
def account_manager(mock_binance_client):
    """Pytest fixture for AccountManager with a mocked client."""
    # Store original methods
    original_get = real_config_manager.get
    original_getboolean = real_config_manager.getboolean

    # Monkeypatch the methods directly
    real_config_manager.get = Mock(return_value='BTCUSDT')
    real_config_manager.getboolean = Mock(return_value=False)

    yield AccountManager(binance_client=mock_binance_client)

    # Restore original methods after the test
    real_config_manager.get = original_get
    real_config_manager.getboolean = original_getboolean

def test_get_open_orders_success(account_manager, mock_binance_client):
    """Test get_open_orders successfully retrieves open orders."""
    # Arrange
    mock_orders = [{'symbol': 'BTCUSDT', 'orderId': 123, 'status': 'NEW'}]
    mock_binance_client.get_open_orders.return_value = mock_orders

    # Act
    orders = account_manager.get_open_orders()

    # Assert
    assert orders == mock_orders
    mock_binance_client.get_open_orders.assert_called_once_with(symbol='BTCUSDT')

def test_get_open_orders_api_error(account_manager, mock_binance_client):
    """Test get_open_orders handles Binance API errors."""
    # Arrange
    mock_response = Mock()
    mock_response.text = '{"code": -1021, "msg": "Timestamp for this request was 1000ms ahead of the server time."}'
    mock_binance_client.get_open_orders.side_effect = BinanceAPIException(response=mock_response, status_code=400, text=mock_response.text)

    # Act
    orders = account_manager.get_open_orders()

    # Assert
    assert orders == []

def test_get_trade_history_success(account_manager, mock_binance_client):
    """Test get_trade_history successfully retrieves trade history."""
    # Arrange
    mock_trades = [{'symbol': 'BTCUSDT', 'id': 1, 'price': '50000'}]
    mock_binance_client.get_my_trades.return_value = mock_trades

    # Act
    trades = account_manager.get_trade_history(limit=5)

    # Assert
    assert trades == mock_trades
    mock_binance_client.get_my_trades.assert_called_once_with(symbol='BTCUSDT', limit=5)

def test_get_trade_history_api_error(account_manager, mock_binance_client):
    """Test get_trade_history handles Binance API errors."""
    # Arrange
    mock_response = Mock()
    mock_response.text = '{"code": -1021, "msg": "Timestamp for this request was 1000ms ahead of the server time."}'
    mock_binance_client.get_my_trades.side_effect = BinanceAPIException(response=mock_response, status_code=400, text=mock_response.text)

    # Act
    trades = account_manager.get_trade_history()

    # Assert
    assert trades == []

def test_update_on_buy_success(account_manager, mock_binance_client):
    """Test update_on_buy successfully places a buy order."""
    # Arrange
    mock_order = {'symbol': 'BTCUSDT', 'orderId': 124, 'status': 'FILLED'}
    mock_binance_client.order_market_buy.return_value = mock_order

    # Act
    result = account_manager.update_on_buy(quote_order_qty=1000)

    # Assert
    assert result is True
    mock_binance_client.order_market_buy.assert_called_once_with(symbol='BTCUSDT', quoteOrderQty=1000)

def test_update_on_buy_api_error(account_manager, mock_binance_client):
    """Test update_on_buy handles Binance API errors."""
    # Arrange
    mock_response = Mock()
    mock_response.text = '{"code": -2010, "msg": "Account has insufficient balance for requested action."}'
    mock_binance_client.order_market_buy.side_effect = BinanceAPIException(response=mock_response, status_code=400, text=mock_response.text)

    # Act
    result = account_manager.update_on_buy(quote_order_qty=1000)

    # Assert
    assert result is False

def test_update_on_sell_success(account_manager, mock_binance_client):
    """Test update_on_sell successfully places a sell order."""
    # Arrange
    mock_order = {'symbol': 'BTCUSDT', 'orderId': 125, 'status': 'FILLED'}
    mock_binance_client.order_market_sell.return_value = mock_order
    # Mock the internal validation/formatting function to isolate the test
    account_manager._format_quantity_for_symbol = Mock(return_value=0.1)

    # Act
    result = account_manager.update_on_sell(quantity_btc=0.1, current_price=50000)

    # Assert
    assert result == mock_order
    account_manager._format_quantity_for_symbol.assert_called_once_with(symbol='BTCUSDT', quantity=0.1, current_price=50000)
    mock_binance_client.order_market_sell.assert_called_once_with(symbol='BTCUSDT', quantity=0.1)


def test_update_on_sell_api_error(account_manager, mock_binance_client):
    """Test update_on_sell handles Binance API errors."""
    # Arrange
    mock_response = Mock()
    mock_response.text = '{"code": -2010, "msg": "Account has insufficient balance for requested action."}'
    mock_binance_client.order_market_sell.side_effect = BinanceAPIException(response=mock_response, status_code=400, text=mock_response.text)
    # Mock the internal validation/formatting function
    account_manager._format_quantity_for_symbol = Mock(return_value=0.1)

    # Act
    result = account_manager.update_on_sell(quantity_btc=0.1, current_price=50000)

    # Assert
    assert result is None
