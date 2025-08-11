import os
import sys
import argparse
from datetime import datetime

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
        # Get the base InfluxDB connection details from environment variables
        db_connection_config = config_manager.get_db_config()

        # Get the specific bucket for backtesting from the config file
        db_connection_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_backtest')

        db_manager = DatabaseManager(config=db_connection_config)

        # The 'trades' measurement is where trade data is stored.
        # Clearing this ensures that reports are not contaminated by previous runs.
        logger.info(f"Attempting to clear 'trades' measurement from bucket '{db_connection_config['bucket']}'...")
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
    parser = argparse.ArgumentParser(
        description="Run a backtest for a specific number of days or over a defined date range.",
        usage="%(prog)s [days | --start-date YYYY-MM-DD --end-date YYYY-MM-DD]"
    )
    parser.add_argument(
        "days",
        nargs='?',
        type=int,
        default=None,
        help="The number of past days to include in the backtest (e.g., 30)."
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="The start date for the backtest in YYYY-MM-DD format."
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="The end date for the backtest in YYYY-MM-DD format."
    )

    args = parser.parse_args()

    # Validate arguments
    if args.days is None and (args.start_date is None or args.end_date is None):
        logger.error("Error: You must provide either the number of 'days' or both '--start-date' and '--end-date'.")
        parser.print_help()
        sys.exit(1)

    if args.days is not None and (args.start_date is not None or args.end_date is not None):
        logger.error("Error: You cannot use 'days' and date range arguments simultaneously.")
        parser.print_help()
        sys.exit(1)

    if args.start_date and args.end_date:
        try:
            # Validate date format
            datetime.strptime(args.start_date, '%Y-%m-%d')
            datetime.strptime(args.end_date, '%Y-%m-%d')
        except ValueError as e:
            logger.error(f"Error: Invalid date format. Please use YYYY-MM-DD. Details: {e}")
            sys.exit(1)

    try:
        # CRITICAL: Ensure the environment is clean before running a new backtest
        clear_previous_backtest_trades()

        logger.info("--- Starting New Backtest Simulation ---")
        
        backtester = None
        if args.days:
            backtester = Backtester(days=args.days)
        else:
            backtester = Backtester(start_date=args.start_date, end_date=args.end_date)
        
        backtester.run()
        logger.info("--- Backtest Simulation Finished ---")

    except Exception as e:
        logger.error(f"An unexpected error occurred during the backtest execution: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
