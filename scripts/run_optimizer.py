import os
import sys
import argparse

# Adiciona a raiz do projeto ao path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.optimizer import run_optimization
from jules_bot.utils.logger import logger

def main():
    """
    Ponto de entrada para o script de otimização de estratégia.
    Lida com os argumentos de linha de comando e inicia o processo de otimização.
    """
    parser = argparse.ArgumentParser(description="Run strategy optimization using Optuna.")
    parser.add_argument("bot_name", type=str, help="The name of the bot to optimize.")
    parser.add_argument("n_trials", type=int, help="The number of optimization trials to run.")
    parser.add_argument("days", type=int, help="The number of past days of data to use for backtesting each trial.")
    parser.add_argument("wallet_profile", type=str, choices=['beginner', 'intermediate', 'advanced'], help="The wallet profile to use (determines initial capital).")

    args = parser.parse_args()

    try:
        logger.info(f"--- Initializing Strategy Optimization Script for bot '{args.bot_name}' ---")

        # O BOT_NAME é definido como variável de ambiente pelo run.py, mas passamos explicitamente
        # para a função de otimização para garantir clareza.
        run_optimization(
            bot_name=args.bot_name,
            n_trials=args.n_trials,
            days=args.days,
            wallet_profile=args.wallet_profile
        )

        logger.info("✅ Optimization script finished successfully.")
    except Exception as e:
        logger.error(f"An unexpected error occurred during the optimization script: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
