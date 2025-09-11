import os
import sys
import json
import typer
import traceback

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.genius_optimizer.genius_optimizer import GeniusOptimizer
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

app = typer.Typer()

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

        config_manager.initialize(bot_name)
        
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
