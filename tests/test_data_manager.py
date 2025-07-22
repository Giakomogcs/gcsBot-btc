import pytest
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.core.data_manager import DataManager
from unittest.mock import patch

@pytest.fixture
def sample_kaggle_data():
    """
    Provides a sample Kaggle dataframe.
    """
    data = {
        'timestamp': ['2022-01-01 00:00:00', '2022-01-01 00:01:00', '2022-01-01 00:02:00'],
        'open': [40000, 40100, 40200],
        'high': [40100, 40200, 40300],
        'low': [39900, 40000, 40100],
        'close': [40100, 40200, 40300],
        'volume': [10, 20, 30]
    }
    return pd.DataFrame(data)

def test_data_manager_instantiation():
    """
    Tests if the DataManager class can be instantiated.
    """
    dm = DataManager()
    assert dm is not None

def test_preprocess_kaggle_data(sample_kaggle_data):
    """
    Tests the _preprocess_kaggle_data method in DataManager.
    """
    dm = DataManager()
    processed_df = dm._preprocess_kaggle_data(sample_kaggle_data)
    assert not processed_df.empty
    assert 'volume' in processed_df.columns
    assert pd.api.types.is_datetime64_ns_dtype(processed_df.index)

@pytest.mark.online
@patch('yfinance.download')
@patch('src.core.data_manager.Client')
@patch('src.core.data_manager.Database')
def test_fetch_and_update_macro_data(mock_database, mock_binance_client, mock_yf_download, tmp_path):
    """
    Tests the _fetch_and_update_macro_data method in DataManager.
    """
    # Create a dummy dataframe to be returned by the mock
    dummy_df = pd.DataFrame({
        'Open': [100], 'High': [101], 'Low': [99], 'Close': [100], 'Volume': [1000]
    }, index=[pd.to_datetime('2023-01-01')])
    mock_yf_download.return_value = dummy_df

    dm = DataManager()
    dm.is_online = True  # Force online mode for the test
    dm._fetch_and_update_macro_data()

    # We can't easily check if the data was written to the database,
    # but we can check that the mock was called.
    assert mock_yf_download.call_count == 4
