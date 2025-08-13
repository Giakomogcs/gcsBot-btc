import os
import sys
import logging

# Ensure the project root is in the Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core.market_data_provider import MarketDataProvider
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.services.status_service import StatusService
from jules_bot.bot.command_manager import CommandManager
from jules_bot.ui.display_manager import DisplayManager
from jules_bot.utils.logger import logger

def main():
    """
    Entry point for the local UI runner.
    Initializes all services and runs the Textual application.
    """
    # 1. Determine Mode
    mode = "test"
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["live", "trade"]:
        mode = "trade"

    logger.info(f"--- Starting Jules Bot UI in {mode.upper()} mode ---")

    try:
        # 2. Initialize Services
        logger.info("Initializing services...")
        config_manager = ConfigManager()
        db_config = config_manager.get_db_config('POSTGRES')
        db_manager = PostgresManager(config=db_config)
        market_data_provider = MarketDataProvider(db_manager)
        exchange_manager = ExchangeManager(mode=mode)
        status_service = StatusService(db_manager, config_manager, market_data_provider)
        command_manager = CommandManager(db_manager, exchange_manager, f"jules_{mode}_bot", "BTC/USDT")
        logger.info("Services initialized successfully.")

        # 3. Initialize and Run the App
        # The DisplayManager now handles its own periodic updates via a worker.
        app = DisplayManager(
            mode=mode,
            command_manager=command_manager,
            status_service=status_service
        )
        app.run()

    except Exception as e:
        logger.critical(f"A critical error occurred while starting the application: {e}", exc_info=True)
        sys.exit(1)

    logger.info(f"--- Jules Bot UI for {mode.upper()} mode has shut down. ---")

if __name__ == '__main__':
    main()
