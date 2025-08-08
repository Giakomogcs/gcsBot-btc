import os
import sys

# Adiciona a raiz do projeto ao path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.backtesting.engine import Backtester
from jules_bot.utils.config_manager import config_manager
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.logger import logger

def clear_previous_backtest_trades():
    """
    Connects to the database and clears all records from the 'trades'
    measurement in the backtest bucket to ensure a clean slate.
    """
    logger.info("--- Starting Backtest Environment Cleanup ---")
    try:
        # Load the specific backtest configuration for the database
        db_config = config_manager.get_section('INFLUXDB')

        # We need to construct a config dictionary suitable for DatabaseManager
        # The manager expects url, token, org, and the specific bucket
        db_connection_config = {
            "url": f"http://{db_config['host']}:{db_config['port']}",
            "token": db_config['token'],
            "org": db_config['org'],
            "bucket": db_config['bucket_backtest']
        }

        db_manager = DatabaseManager(config=db_connection_config)

        # The 'trades' measurement is where trade data is stored.
        # Clearing this ensures that reports are not contaminated by previous runs.
        logger.info(f"Attempting to clear 'trades' measurement from bucket '{db_config['bucket_backtest']}'...")
        db_manager.clear_measurement("trades")

        db_manager.close_client()
        logger.info("--- Backtest Environment Cleanup Finished ---")

    except Exception as e:
        logger.error(f"An error occurred during backtest cleanup: {e}", exc_info=True)
        # We should exit if we can't guarantee a clean state
        sys.exit(1)


def main():
    """
    Runs a full backtest using the provided historical data.
    """
    # CRITICAL: Ensure the environment is clean before running a new backtest
    clear_previous_backtest_trades()

    logger.info("--- Starting New Backtest Simulation ---")
    historical_data_path = config_manager.get('DATA_PATHS', 'historical_data_file')
    backtester = Backtester(historical_data_path)
    backtester.run()
    logger.info("--- Backtest Simulation Finished ---")


if __name__ == "__main__":
    main()
