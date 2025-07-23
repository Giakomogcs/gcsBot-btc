import pytest
import pandas as pd
import numpy as np
import sys
import os
from unittest.mock import patch
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.core.data_manager import DataManager

@pytest.fixture
def test_dm():
    """
    Provides a DataManager instance with a mock database.
    """
    with patch('src.core.data_manager.Database') as mock_db:
        dm = DataManager()
        dm.db = mock_db.return_value
        yield dm

def create_sample_data(rows=1000):
    """
    Creates a sample dataframe with realistic data.
    """
    start_date = pd.to_datetime('2023-01-01')
    end_date = start_date + pd.to_timedelta(rows, 'm')
    dates = pd.date_range(start=start_date, end=end_date, freq='m')
    data = {
        'timestamp': dates,
        'open': np.random.uniform(30000, 50000, size=len(dates)),
        'high': np.random.uniform(30000, 50000, size=len(dates)),
        'low': np.random.uniform(30000, 50000, size=len(dates)),
        'close': np.random.uniform(30000, 50000, size=len(dates)),
        'volume': np.random.uniform(10, 100, size=len(dates))
    }
    df = pd.DataFrame(data)
    return df

@patch('src.core.data_manager.DataManager._fetch_and_update_twitter_sentiment')
@patch('src.core.data_manager.DataManager._fetch_and_update_macro_data')
@patch('src.core.data_manager.DataManager._load_and_unify_local_macro_data')
@patch('src.core.data_manager.DataManager._fetch_and_manage_btc_data')
def test_data_pipeline_does_not_lose_data(mock_fetch_btc, mock_load_macro, mock_fetch_macro, mock_fetch_twitter, test_dm):
    """
    Tests that the data pipeline does not lose data unnecessarily.
    """
    # Arrange
    os.makedirs(os.path.join("data", "macro"), exist_ok=True)
    sample_data = create_sample_data()
    mock_fetch_btc.return_value = sample_data
    mock_load_macro.return_value = pd.DataFrame()
    mock_fetch_macro.return_value = None
    mock_fetch_twitter.return_value = None
    test_dm.db.fetch_data.return_value = pd.DataFrame(columns=['timestamp', 'sentiment'])

    # Act
    processed_data = test_dm.update_and_load_data('BTC/USDT', '1m')

    # Assert
    assert not processed_data.empty, "Processed data is empty"
    assert len(processed_data) > 0, "Processed data has no rows"
    assert len(processed_data) <= len(sample_data), "Processed data has more rows than original data"
