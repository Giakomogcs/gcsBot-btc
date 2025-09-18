import math
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
    Calculates a composite "Genius Score" based on multiple performance metrics.
    This new version is more robust, factoring in profit factor and trade count
    to avoid overfitting and reward statistical significance.
    A higher score is better.
    """
    if not results:
        return -1000.0

    # --- Basic Sanity Checks ---
    final_balance = results.get("final_balance", Decimal("0.0"))
    if final_balance is None or float(final_balance) <= 1.0: # Can't be zero or negative
        return -1000.0

    max_drawdown = float(results.get("max_drawdown", 1.0))
    if max_drawdown > 0.95: # Reject strategies that lose almost everything
        return -1000.0

    # --- Core Metrics ---
    sortino_ratio = float(results.get("sortino_ratio", 0.0))
    net_pnl_pct = float(results.get("net_pnl_pct", 0.0))
    profit_factor = float(results.get("profit_factor", 0.0))
    sell_trades_count = int(results.get("sell_trades_count", 0))

    # --- Penalty for Lack of Trades (Statistical Significance) ---
    # A strategy isn't reliable if it only made a few trades.
    # We use a logarithmic scale so the penalty is harsh for very few trades
    # but grows slowly after a reasonable number (e.g., > 10).
    min_trades_for_full_score = 5
    if sell_trades_count < min_trades_for_full_score:
        # Penalize heavily if no trades or very few trades were made
        trade_count_penalty = 0.1 * (sell_trades_count / min_trades_for_full_score)
    else:
        # Reward having more trades, but with diminishing returns
        trade_count_penalty = math.log10(sell_trades_count - min_trades_for_full_score + 10)

    # Normalize the penalty to be a factor between ~0.1 and 1+
    trade_count_factor = min(max(trade_count_penalty, 0.1), 1.5)


    # --- Penalty for Drawdown ---
    # The closer to 1 (100% drawdown), the harsher the penalty.
    drawdown_penalty = (1 - max_drawdown) ** 2

    # --- Profit Factor Component ---
    # A profit factor < 1 means the strategy is losing money.
    # We can use it as a direct multiplier, but cap its influence to avoid runaway scores.
    # A good strategy should have a profit factor > 1.2.
    profit_factor_score = min(profit_factor, 3.0) # Cap at 3.0 to prevent extreme influence

    # --- Final Score Calculation ---
    # We combine the metrics. The core is the risk-adjusted return (Sortino * PnL),
    # which is then weighted by the other factors.
    base_score = sortino_ratio * net_pnl_pct

    # If the base score is negative, we penalize it further with bad profit factor
    if base_score < 0:
        final_score = base_score * (2 - profit_factor_score) # Lower profit factor makes it more negative
    else:
        # For positive scores, all factors are multipliers
        final_score = (
            base_score
            * drawdown_penalty
            * profit_factor_score
            * trade_count_factor
        )

    # Final check for invalid numbers (NaN, infinity)
    if not math.isfinite(final_score):
        return 0.0

    return final_score


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

            # Each trial needs its own ConfigManager instance to hold the overrides.
            # The global config_manager is a singleton and should not be modified here.
            # The bot_name is automatically picked up from the environment, so no .initialize() is needed.
            trial_config_manager = ConfigManager()
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
