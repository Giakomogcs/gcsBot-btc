import pytest
from unittest.mock import patch, Mock

@pytest.fixture
def mock_db_manager():
    """Mocks the DatabaseManager class and returns a mock instance."""
    with patch('jules_bot.database.database_manager.DatabaseManager', autospec=True) as mock_db_class:
        mock_instance = mock_db_class.return_value
        yield mock_instance

@pytest.fixture
def mock_binance_client():
    """Pytest fixture for a mocked Binance client."""
    return Mock()
