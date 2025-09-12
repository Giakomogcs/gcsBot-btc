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
    Connects to the database and clears all tables for the bot defined
    by the BOT_NAME environment variable. This is a destructive operation.
    """
    # The PostgresManager will be instantiated using the bot_name from the
    # config_manager singleton, which is initialized from the BOT_NAME env var.
    db_manager = PostgresManager()
    bot_name_from_db = db_manager.bot_name # This is the schema name (e.g., 'my_bot')

    user_confirmed = False
    if force:
        user_confirmed = True
    else:
        print("\n" + "="*50)
        print("⚠️  WARNING: DESTRUCTIVE ACTION  ⚠️")
        print("="*50)
        print(f"You are about to permanently delete all data for bot '{bot_name_from_db}'")
        print(f"from the following tables in schema '{bot_name_from_db}':")
        print("  - trades")
        print("  - bot_status")
        print("  - price_history")
        print("\nThis action is irreversible.")

        confirm = input(f"Are you absolutely sure you want to continue for bot '{bot_name_from_db}'? (yes/no): ")
        if confirm.lower() == 'yes':
            user_confirmed = True

    if user_confirmed:
        logger.info(f"User confirmed database wipe for bot '{bot_name_from_db}'. Proceeding...")
        try:
            db_manager.clear_all_tables()
            print(f"\n✅ Database for bot '{bot_name_from_db}' has been successfully wiped.")
            logger.info(f"Database wipe for bot '{bot_name_from_db}' executed successfully.")
        except Exception as e:
            logger.error(f"An error occurred during database wipe for bot '{bot_name_from_db}': {e}", exc_info=True)
            print(f"\n❌ An error occurred. Check the logs for details.")
    else:
        print("\n🚫 Database wipe cancelled.")
        logger.info(f"User cancelled database wipe for bot '{bot_name_from_db}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wipe all data from the database.")
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force wipe without confirmation prompt.'
    )
    args = parser.parse_args()

    wipe_database(force=args.force)
