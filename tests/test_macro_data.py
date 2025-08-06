import pytest
import pandas as pd
import os
from unittest.mock import patch
from gcs_bot.data.data_manager import DataManager
from gcs_bot.utils.config_manager import settings

@pytest.fixture
def test_dm(mock_db_manager):
    """
    Provides a DataManager instance with a mock database manager.
    """
    dm = DataManager(db_manager=mock_db_manager, config=None, logger=None)
    return dm

@pytest.fixture
def sample_macro_data():
    """
    Provides a sample macro dataframe.
    """
    data = {
        'Date': ['2023-01-01', '2023-01-02', '2023-01-03'],
        'Open': [100, 101, 102],
        'High': [101, 102, 103],
        'Low': [99, 100, 101],
        'Close': [100, 101, 102],
        'Volume': [1000, 2000, 3000]
    }
    df = pd.DataFrame(data)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date')
    return df

@patch('yfinance.download')
def test_fetch_and_update_macro_data_offline(mock_yf_download, test_dm, sample_macro_data):
    """
    Tests the _fetch_and_update_macro_data method in offline mode.
    """
    # Arrange
    test_dm.client = None
    macro_dir = os.path.join(settings.data_paths.macro_data_dir, 'macro')
    os.makedirs(macro_dir, exist_ok=True)
    file_path = os.path.join(macro_dir, 'dxy.csv')
    sample_macro_data.reset_index().to_csv(file_path, index=False) # Save with 'Date' column
    mock_yf_download.return_value = sample_macro_data
    test_dm.db_manager.get_last_n_trades.return_value = pd.DataFrame({'timestamp': [pd.to_datetime('2022-01-01')]})

    # Act
    test_dm._fetch_and_update_macro_data()

    # Assert
    # In offline mode, yf.download should not be called.
    # Instead, the data should be loaded from the local file and inserted into the database.
    assert mock_yf_download.call_count == 0
    assert test_dm.db_manager.write_trade.call_count >= 1
    inserted_df = test_dm.db_manager.write_trade.call_args[0][0]
    assert not inserted_df.empty

@patch('yfinance.download')
def test_fetch_and_update_macro_data_online(mock_yf_download, test_dm, sample_macro_data):
    """
    Tests the _fetch_and_update_macro_data method in online mode.
    """
    # Arrange
    with patch('gcs_bot.utils.config_manager.settings.app.force_offline_mode', False):
        mock_yf_download.return_value = sample_macro_data
        test_dm.client = True

        # Act
        test_dm._fetch_and_update_macro_data()

        # Assert
        assert mock_yf_download.call_count == 4
        assert test_dm.db_manager.write_trade.call_count == 4
