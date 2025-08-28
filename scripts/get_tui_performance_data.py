import sys
import os
import json

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from jules_bot.services.performance_service import get_summary
from jules_bot.utils.config_manager import config_manager

def main():
    """
    This script acts as a data endpoint for the TUI.
    It fetches the performance summary and prints it as a JSON string.
    The bot name is determined by the BOT_NAME environment variable.
    """
    bot_name = os.getenv("BOT_NAME")
    if not bot_name:
        print(json.dumps({"error": "BOT_NAME environment variable not set."}), file=sys.stderr)
        sys.exit(1)

    # Initialize the config manager with the bot name to load correct .env variables
    config_manager.initialize(bot_name)

    summary_data = get_summary(bot_name=bot_name)
    print(json.dumps(summary_data))

if __name__ == "__main__":
    main()