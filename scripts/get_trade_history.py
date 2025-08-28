import json
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager

def get_trade_history():
    """
    Fetches the complete trade history for a given bot and prints it as JSON.
    The bot name is determined by the BOT_NAME environment variable.
    """
    bot_name = os.getenv("BOT_NAME")
    if not bot_name:
        print(json.dumps({"error": "BOT_NAME environment variable not set."}), file=sys.stderr)
        sys.exit(1)

    try:
        # Initialize the config manager with the bot name to ensure we connect
        # to the correct database schema.
        config_manager.initialize(bot_name)

        db_manager = PostgresManager()

        # Fetch all trades. For a TUI, fetching all trades is generally acceptable.
        # If performance becomes an issue, pagination could be added here.
        all_trades = db_manager.get_all_trades_in_range()

        # Serialize the list of Trade objects into a list of dictionaries
        history_list = [trade.to_dict() for trade in all_trades]

        # Print the JSON output
        print(json.dumps(history_list, indent=4))

    except Exception as e:
        # It's crucial to output a JSON error message for the TUI to parse
        print(json.dumps({"error": f"Failed to get trade history: {e}"}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    get_trade_history()
