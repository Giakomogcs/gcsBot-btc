import os
import sys

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

def clear_testnet_trades():
    """
    Connects to the database and clears all trades from the 'test' environment
    for a specific bot.
    """
    try:
        # The config_manager singleton is initialized on import from the BOT_NAME env var.
        # PostgresManager will use it to connect to the correct schema.
        bot_name = config_manager.bot_name
        logger.info(f"Starting the process to clear testnet trades for bot '{bot_name}'...")

        db_manager = PostgresManager()
        db_manager.clear_testnet_trades()

        logger.info(f"Testnet trades clearing process for bot '{bot_name}' finished successfully.")

    except Exception as e:
        logger.error(f"An error occurred during the testnet trade clearing process: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    clear_testnet_trades()
