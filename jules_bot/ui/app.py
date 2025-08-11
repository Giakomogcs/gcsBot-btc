import sys
import os

# Ensure the project root is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from jules_bot.ui.display_manager import DisplayManager

def main():
    """
    Entry point for the Textual User Interface.
    """
    app = DisplayManager()
    app.run()

if __name__ == '__main__':
    main()
