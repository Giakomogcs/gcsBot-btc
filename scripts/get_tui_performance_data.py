import sys
import os
import json

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from jules_bot.services.performance_service import get_summary
from jules_bot.utils.config_manager import config_manager

def main(bot_name: str):
    """
    This script acts as a data endpoint for the TUI.
    It fetches the performance summary and prints it as a JSON string.
    """
    # Initialize the config manager with the bot name to load correct .env variables
    config_manager.initialize(bot_name)

    summary_data = get_summary(bot_id=bot_name)
    print(json.dumps(summary_data))

if __name__ == "__main__":
    bot_name = "jules_bot"
    if len(sys.argv) > 1:
        bot_name = sys.argv[1]
    main(bot_name)