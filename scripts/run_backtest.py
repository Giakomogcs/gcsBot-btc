import os
import sys

# Adiciona a raiz do projeto ao path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.backtesting.engine import Backtester
from jules_bot.utils.config_manager import config_manager

def main():
    """
    Runs a full backtest using the provided historical data.
    """
    historical_data_path = config_manager.get('DATA_PATHS', 'historical_data_file')
    backtester = Backtester(historical_data_path)
    backtester.run()

if __name__ == "__main__":
    main()
