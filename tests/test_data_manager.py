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
        'Timestamp': [1622505600, 1622505660, 1622505720],
        'Open': [40000, 40100, 40200],
        'High': [40100, 40200, 40300],
        'Low': [39900, 40000, 40100],
        'Close': [40100, 40200, 40300],
        'Volume_(BTC)': [10, 20, 30]
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
    assert 'Volume_(BTC)' not in processed_df.columns
    assert pd.api.types.is_datetime64_ns_dtype(processed_df.index)

@pytest.mark.online
@patch('yfinance.download')
def test_fetch_and_update_macro_data(mock_yf_download, tmp_path):
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
    macro_data_path = tmp_path / 'macro'
    dm._fetch_and_update_macro_data(caminho_dados=str(macro_data_path))

    # Check if the files were created
    assert os.path.exists(macro_data_path / 'dxy.csv')
    assert os.path.exists(macro_data_path / 'gold.csv')
    assert os.path.exists(macro_data_path / 'tnx.csv')
    assert os.path.exists(macro_data_path / 'vix.csv')
