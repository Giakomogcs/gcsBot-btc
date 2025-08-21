import os
import sys
import argparse

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.logger import logger
from jules_bot.database.models import PriceHistory
from sqlalchemy import delete

def wipe_price_data(symbol: str):
    """
    Deletes all price history for a given symbol from the database.
    """
    if not symbol:
        logger.error("A symbol must be provided.")
        return

    logger.warning(f"This is a destructive action. You are about to delete ALL price history for the symbol '{symbol}'.")
    confirm = input("Are you sure you want to continue? (yes/no): ")

    if confirm.lower() != 'yes':
        logger.info("Operation cancelled by user.")
        return

    logger.info(f"Proceeding with deletion for symbol '{symbol}'...")

    try:
        db_manager = PostgresManager()
        with db_manager.get_db() as db:
            logger.info("Database session started.")

            stmt = delete(PriceHistory).where(PriceHistory.symbol == symbol)
            result = db.execute(stmt)
            db.commit()

            logger.info(f"Successfully deleted {result.rowcount} rows for symbol '{symbol}'.")
            logger.info("Please run the `prepare_backtest_data` script to re-download fresh data.")

    except Exception as e:
        logger.error(f"An error occurred while wiping data for symbol '{symbol}': {e}", exc_info=True)
        if 'db' in locals() and db.is_active:
            db.rollback()
            logger.info("Transaction rolled back.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Wipe price history for a specific symbol from the database.")
    parser.add_argument("--symbol", type=str, required=True, help="The symbol to wipe data for (e.g., BTCUSDT).")

    args = parser.parse_args()

    wipe_price_data(args.symbol)
