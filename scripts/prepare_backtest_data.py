import sys
import os
import argparse

# Adiciona a raiz do projeto ao path para permitir a importação de módulos
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from collectors.core_price_collector import prepare_backtest_data
from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import config_manager

def main():
    """
    Entry point for the backtest data preparation script.
    Handles command-line arguments for the number of days and force reload option.
    """
    parser = argparse.ArgumentParser(description="Prepare historical data for backtesting.")
    parser.add_argument(
        "days",
        type=int,
        help="The number of days of historical data to prepare."
    )
    
    args = parser.parse_args()

    try:
        # The config_manager singleton is initialized on import, reading BOT_NAME
        # from the environment. Any component that uses it will have the correct bot context.
        bot_name = config_manager.bot_name

        logger.info(f"Starting backtest data preparation for bot '{bot_name}' for the last {args.days} days...")
        
        prepare_backtest_data(days=args.days)
        
        logger.info("✅ Backtest data preparation finished successfully.")
    except Exception as e:
        logger.error(f"An unexpected error occurred during data preparation: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
