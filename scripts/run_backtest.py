import sys

def main():
    """
    This script is deprecated. The backtest is now run via the main application UI.
    """
    print("--- DEPRECATION WARNING ---")
    print("This script is no longer used to run the backtest.")
    print("To run a backtest, please follow these steps:")
    print("1. Edit your 'config.yml' and set 'app.execution_mode' to 'backtest'.")
    print("2. Run the application using 'docker-compose up --build'.")
    print("This will launch the Textual UI for backtesting.")
    sys.exit(0)

if __name__ == "__main__":
    main()
