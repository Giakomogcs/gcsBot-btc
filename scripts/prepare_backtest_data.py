import sys
import os

# Adiciona a raiz do projeto ao path para permitir a importação de módulos
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from collectors.core_price_collector import prepare_backtest_data
from jules_bot.utils.logger import logger

import argparse

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
    parser.add_argument(
        "--force-reload",
        action="store_true",
        help="If set, the script will clear and re-populate the database even if it already contains data."
    )
    args = parser.parse_args()

    try:
        logger.info(f"Starting backtest data preparation for the last {args.days} days...")
        if args.force_reload:
            logger.info("Force reload flag is set. Data will be re-populated.")
        
        prepare_backtest_data(days=args.days, force_reload=args.force_reload)
        
        logger.info("✅ Backtest data preparation finished successfully.")
    except Exception as e:
        logger.error(f"An unexpected error occurred during data preparation: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
