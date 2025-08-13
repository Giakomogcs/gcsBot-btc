import sys
import os

# Ensure the project root is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from jules_bot.ui.display_manager import DisplayManager

def main():
    """
    Entry point for the Textual User Interface.
    Parses command-line arguments to determine the bot's mode.
    """
    # Default to 'test' mode if no arguments are provided
    mode = "test"
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["live", "trade"]:
        mode = "trade"

    app = DisplayManager(mode=mode)
    app.run()

if __name__ == '__main__':
    main()
