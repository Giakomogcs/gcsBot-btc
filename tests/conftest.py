import pytest
from unittest.mock import patch, Mock

@pytest.fixture
def mock_db_manager():
    """Mocks the db_manager singleton."""
    with patch('gcs_bot.database.database_manager.db_manager', autospec=True) as mock_db:
        yield mock_db

@pytest.fixture
def mock_binance_client():
    """Pytest fixture for a mocked Binance client."""
    return Mock()
