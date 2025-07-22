import pytest
import pandas as pd
import os
from unittest.mock import patch
from src.core.data_manager import DataManager
from src.config import settings

@pytest.fixture
def test_dm():
    """
    Provides a DataManager instance with a mock database.
    """
    with patch('src.core.data_manager.Database') as mock_db:
        dm = DataManager()
        dm.db = mock_db.return_value
        yield dm

@pytest.fixture
def sample_macro_data():
    """
    Provides a sample macro dataframe.
    """
    data = {
        'date': ['2023-01-01', '2023-01-02', '2023-01-03'],
        'open': [100, 101, 102],
        'high': [101, 102, 103],
        'low': [99, 100, 101],
        'close': [100, 101, 102],
        'volume': [1000, 2000, 3000]
    }
    return pd.DataFrame(data)

def test_fetch_and_update_macro_data_offline(test_dm, sample_macro_data):
    """
    Tests the _fetch_and_update_macro_data method in offline mode.
    """
    # Arrange
    test_dm.client = None
    file_path = os.path.join(settings.DATA_DIR, 'macro', 'dxy.csv')
    sample_macro_data.to_csv(file_path, index=False)

    # Act
    test_dm._fetch_and_update_macro_data()

    # Assert
    for call in test_dm.db.insert_dataframe.call_args_list:
        args, kwargs = call
        assert isinstance(args[0], pd.DataFrame)
        assert args[1] == 'macro_dxy'
        assert kwargs['if_exists'] == 'replace'

@patch('yfinance.download')
def test_fetch_and_update_macro_data_online(mock_yf_download, test_dm, sample_macro_data):
    """
    Tests the _fetch_and_update_macro_data method in online mode.
    """
    # Arrange
    mock_yf_download.return_value = sample_macro_data
    test_dm.client = True

    # Act
    test_dm._fetch_and_update_macro_data()

    # Assert
    assert mock_yf_download.call_count == 4
    assert test_dm.db.insert_dataframe.call_count == 4
