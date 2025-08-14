import os
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

def clear_backtest_trades():
    """
    Connects to the database and clears all trades from the 'backtest' environment.
    """
    try:
        logger.info("Starting the process to clear backtest trades...")

        # Load database configuration from config.ini
        db_config = {
            'user': config_manager.get('POSTGRES', 'user'),
            'password': config_manager.get('POSTGRES', 'password'),
            'host': config_manager.get('POSTGRES', 'host'),
            'port': config_manager.get('POSTGRES', 'port'),
            'dbname': config_manager.get('POSTGRES', 'dbname')
        }

        # Initialize the PostgresManager
        db_manager = PostgresManager(config=db_config)

        # Call the method to clear backtest trades
        db_manager.clear_backtest_trades()

        logger.info("Backtest trades clearing process finished successfully.")

    except Exception as e:
        logger.error(f"An error occurred during the backtest trade clearing process: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    clear_backtest_trades()
