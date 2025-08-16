import asyncio
import json
import os
import sys
import typer

# Add project root to sys.path to allow imports from other directories
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.services.status_service import StatusService
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator
from jules_bot.utils.logger import logger

def get_bot_data(mode: str):
    """
    Fetches and returns a comprehensive status report for the trading bot.
    """
    if mode not in ["trade", "test"]:
        logger.error("Invalid mode specified. Please choose 'trade' or 'test'.")
        return {"error": "Invalid mode specified. Please choose 'trade' or 'test'."}

    logger.info(f"Gathering bot data for '{mode}' environment...")

    try:
        config_manager = ConfigManager()
        db_config = config_manager.get_db_config('POSTGRES')
        db_manager = PostgresManager(config=db_config)
        feature_calculator = LiveFeatureCalculator(db_manager, mode=mode)
        status_service = StatusService(db_manager, config_manager, feature_calculator)

        bot_id = f"jules_{mode}_bot"

        status_data = status_service.get_extended_status(mode, bot_id)

        if "error" in status_data:
            logger.error(f"An error occurred while fetching data: {status_data['error']}")
            return status_data

        logger.info("Successfully retrieved bot data.")
        return status_data

    except Exception as e:
        logger.error(f"A critical error occurred: {e}", exc_info=True)
        return {"error": f"A critical error occurred: {e}"}

def main(
    mode: str = typer.Argument(
        "test",
        help="The environment to get data for ('trade' or 'test')."
    )
):
    """
    Fetches and displays a comprehensive status report for the trading bot.
    """
    status_data = get_bot_data(mode)
    print(json.dumps(status_data, indent=4, default=str)) # Use default=str to handle non-serializable types like datetime

if __name__ == "__main__":
    typer.run(main)
