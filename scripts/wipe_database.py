import sys
import os

# Add the project root to the Python path
# This allows us to import modules from the 'jules_bot' package
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

import argparse
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

def wipe_database(force=False):
    """
    Connects to the database and clears all tables.
    This is a destructive operation and should be used with caution.
    """
    user_confirmed = False
    if force:
        user_confirmed = True
    else:
        print("\n" + "="*50)
        print("⚠️  WARNING: DESTRUCTIVE ACTION  ⚠️")
        print("="*50)
        print("You are about to permanently delete all data from the following tables:")
        print("  - trades")
        print("  - bot_status")
        print("  - price_history")
        print("\nThis action is irreversible.")

        confirm = input("Are you absolutely sure you want to continue? (yes/no): ")
        if confirm.lower() == 'yes':
            user_confirmed = True

    if user_confirmed:
        logger.info("User confirmed database wipe. Proceeding...")
        try:
            db_config = config_manager.get_db_config('POSTGRES')
            db_manager = PostgresManager(config=db_config)

            logger.info("Instantiated PostgresManager. Calling clear_all_tables()...")
            db_manager.clear_all_tables()

            print("\n✅ Database has been successfully wiped.")
            logger.info("Database wipe command executed successfully.")

        except Exception as e:
            logger.error(f"An error occurred during database wipe: {e}", exc_info=True)
            print(f"\n❌ An error occurred. Check the logs for details.")
    else:
        print("\n🚫 Database wipe cancelled.")
        logger.info("User cancelled database wipe.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wipe all data from the database.")
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force wipe without confirmation prompt.'
    )
    args = parser.parse_args()

    wipe_database(force=args.force)
