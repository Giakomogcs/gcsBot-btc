import os
import sys

# Adiciona a raiz do projeto ao path para permitir a importação de módulos
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager

def main():
    """
    Entry point for the backtest trade cleanup script.
    This script specifically targets and deletes trades from the 'backtest' environment.
    """
    try:
        # The config_manager singleton is initialized on import from the BOT_NAME env var.
        # PostgresManager will use it to connect to the correct schema.
        bot_name = config_manager.bot_name
        logger.info(f"Initializing database manager for bot '{bot_name}' to clear backtest trades...")
        db_manager = PostgresManager()

        # Call the specific method to clear only backtest trades
        db_manager.clear_backtest_trades()

        logger.info("✅ Backtest trades cleared successfully.")
    except Exception as e:
        logger.error(f"An unexpected error occurred during backtest trade cleanup: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
