import optuna
import pandas as pd
from decimal import Decimal

from jules_bot.utils.logger import logger
from jules_bot.backtesting.engine import Backtester
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.genius_optimizer.search_space import define_search_space

def calculate_genius_score(results: dict) -> float:
    """
    Calculates a composite score based on multiple performance metrics.
    A higher score is better.
    """
    if not results:
        return -1000.0

    final_balance = results.get("final_balance", Decimal("0.0"))
    if final_balance is None or float(final_balance) <= 0:
        return -1000.0

    sortino_ratio = float(results.get("sortino_ratio", 0.0))
    net_pnl_pct = float(results.get("net_pnl_pct", 0.0))
    max_drawdown = float(results.get("max_drawdown", 1.0))

    if max_drawdown > 0.95:
        return -1000.0

    drawdown_penalty = (1 - max_drawdown) ** 2
    score = sortino_ratio * net_pnl_pct * drawdown_penalty

    if score != score or score == float('inf') or score == float('-inf'):
        return 0.0 # Return a neutral score for invalid math results

    return score


def create_objective_function(bot_name: str, db_manager: PostgresManager, active_params: dict, data_segment: pd.DataFrame):
    """
    Factory function to create the objective function with specific context.
    'data_segment' is the pre-processed, regime-specific data to be used.
    'active_params' defines which parameters to tune in this run.
    """

    def objective(trial: optuna.Trial) -> float:
        """
        The objective function that Optuna will maximize.
        It runs a backtest on a specific data segment and returns the 'Genius Score'.
        """
        try:
            config_overrides = define_search_space(trial, active_params)

            trial_config_manager = ConfigManager()
            trial_config_manager.initialize(bot_name)
            trial_config_manager.apply_overrides(config_overrides)

            if not trial_config_manager.get('BACKTEST', 'initial_balance'):
                 trial_config_manager.set('BACKTEST', 'initial_balance', '1000.0')

            # The Backtester is now initialized with the specific data segment
            backtester = Backtester(
                db_manager=db_manager,
                config_manager=trial_config_manager,
                data=data_segment # Pass the segmented data directly
            )

            results = backtester.run(trial=trial, return_full_results=True)

            score = calculate_genius_score(results)

            if results:
                # Serialize results to be JSON-friendly (convert Decimals to strings)
                serializable_results = {k: str(v) if isinstance(v, Decimal) else v for k, v in results.items()}
                trial.set_user_attr("full_summary", serializable_results)

            return score

        except optuna.TrialPruned:
            raise
        except Exception as e:
            logger.error(f"--- Genius Optuna Trial #{trial.number}: FAILED. Error: {e} ---", exc_info=True)
            return -1000.0

    return objective
