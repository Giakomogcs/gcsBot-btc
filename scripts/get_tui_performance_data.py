import sys
import os
import json

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from jules_bot.services.performance_service import get_summary

def main():
    """
    This script acts as a data endpoint for the TUI.
    It fetches the performance summary and prints it as a JSON string.
    """
    summary_data = get_summary()
    print(json.dumps(summary_data))

if __name__ == "__main__":
    main()
