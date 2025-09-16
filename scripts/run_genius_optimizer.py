import os
import sys
import json
import typer
import traceback

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from pathlib import Path
from decimal import Decimal
from jules_bot.genius_optimizer.genius_optimizer import GeniusOptimizer
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.backtesting.engine import Backtester

app = typer.Typer()

def run_baseline_backtest(bot_name: str, days: int):
    """
    Runs a single backtest using the bot's current .env configuration
    and saves the results for the TUI to display as a baseline.
    """
    logger.info("--- Running Baseline Backtest (using current .env settings) ---")
    try:
        db_manager = PostgresManager()

        # We use the globally initialized config_manager
        backtester = Backtester(
            db_manager=db_manager,
            days=days,
            config_manager=config_manager
        )

        results = backtester.run(return_full_results=True)

        # Serialize results to be JSON-friendly (convert Decimals to strings)
        serializable_results = {k: str(v) if isinstance(v, Decimal) else v for k, v in results.items()}

        # Also include the parameters from the config manager
        final_data = {
            "summary": serializable_results,
            "params": config_manager.get_all_params_as_dict()
        }

        tui_files_dir = Path(".tui_files")
        tui_files_dir.mkdir(exist_ok=True)
        baseline_file = tui_files_dir / "baseline_summary.json"

        with open(baseline_file, "w") as f:
            json.dump(final_data, f, indent=4)

        logger.info(f"✅ Baseline backtest summary saved to {baseline_file}")

    except Exception as e:
        logger.error(f"❌ Failed to run baseline backtest: {e}", exc_info=True)
        # We don't re-raise the exception, as failing the baseline run
        # should not prevent the main optimization from starting.

@app.command()
def main(
    bot_name: str = typer.Argument(..., help="The name of the bot to optimize."),
    days: int = typer.Argument(..., help="The number of days of historical data to use."),
    n_trials: int = typer.Argument(..., help="The number of optimization trials to run per regime."),
    active_params_json: str = typer.Argument(..., help="A JSON string of the active parameters for the optimizer."),
):
    """
    Runs the Genius Optimizer with the specified settings.
    This script is designed to be called from another process, such as run.py,
    to allow for background execution.
    """
    logger.info("--- 🤖 Genius Optimizer Runner Script Started ---")
    try:
        active_params = json.loads(active_params_json)
        logger.info(f"   - Bot: {bot_name}")
        logger.info(f"   - Days: {days}")
        logger.info(f"   - Trials per Regime: {n_trials}")
        logger.info(f"   - Active Parameters: {list(active_params.keys())}")

        # The config_manager is a singleton that initializes itself on import,
        # using the BOT_NAME environment variable. No explicit re-initialization is needed.
        # config_manager.initialize(bot_name) # This was the source of the crash.

        # 1. Run baseline backtest before starting the optimization
        run_baseline_backtest(bot_name, days)
        
        # 2. Run the main optimization process
        genius_optimizer = GeniusOptimizer(
            bot_name=bot_name,
            days=days,
            n_trials=n_trials,
            active_params=active_params
        )
        genius_optimizer.run()

        logger.info("--- ✅ Genius Optimizer Runner Script Finished Successfully ---")

    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON format for active parameters.", exc_info=True)
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ An unexpected error occurred during optimization: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    app()
