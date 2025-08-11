import os
import sys

# Adiciona a raiz do projeto ao path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.backtesting.engine import Backtester
from jules_bot.utils.config_manager import config_manager
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.logger import logger

def clear_previous_backtest_trades():
    """
    Connects to the database and clears all records from the 'trades'
    measurement in the backtest bucket to ensure a clean slate.
    """
    logger.info("--- Starting Backtest Environment Cleanup ---")
    try:
        # Get the base InfluxDB connection details from environment variables
        db_connection_config = config_manager.get_db_config()

        # Get the specific bucket for backtesting from the config file
        db_connection_config['bucket'] = config_manager.get('INFLUXDB', 'bucket_backtest')

        db_manager = DatabaseManager(config=db_connection_config)

        # The 'trades' measurement is where trade data is stored.
        # Clearing this ensures that reports are not contaminated by previous runs.
        logger.info(f"Attempting to clear 'trades' measurement from bucket '{db_connection_config['bucket']}'...")
        db_manager.clear_measurement("trades")

        db_manager.close_client()
        logger.info("--- Backtest Environment Cleanup Finished ---")

    except Exception as e:
        logger.error(f"An error occurred during backtest cleanup: {e}", exc_info=True)
        # We should exit if we can't guarantee a clean state
        sys.exit(1)


def main():
    """
    Runs a full backtest using the provided historical data.
    """
    if len(sys.argv) < 2:
        logger.error("Erro: Número de dias para o backtest não fornecido.")
        logger.error("Uso: python scripts/run_backtest.py <numero_de_dias>")
        sys.exit(1)

    try:
        days = int(sys.argv[1])

        # CRITICAL: Ensure the environment is clean before running a new backtest
        clear_previous_backtest_trades()

        logger.info("--- Starting New Backtest Simulation ---")
        backtester = Backtester(days=days)
        backtester.run()
        logger.info("--- Backtest Simulation Finished ---")

    except ValueError:
        logger.error(f"Erro: O argumento '{sys.argv[1]}' não é um número inteiro válido.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Ocorreu um erro inesperado durante a execução do backtest: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
