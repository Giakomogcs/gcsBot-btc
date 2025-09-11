import os
import pandas as pd
import optuna
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.genius_optimizer.objective import create_objective_function
from jules_bot.genius_optimizer.regime_analyzer import RegimeAnalyzer
from jules_bot.genius_optimizer.results import (
    save_best_params_for_regime,
    generate_importance_report,
    aggregate_results,
    GENIUS_OUTPUT_DIR
)

class GeniusOptimizer:
    """
    The main class for the "Genius Optimizer".
    Orchestrates the entire process of data segmentation, regime-specific
    optimization, and results aggregation.
    """
    def __init__(self, bot_name: str, days: int, n_trials: int, active_params: dict):
        self.bot_name = bot_name
        self.days = days
        self.n_trials = n_trials
        self.active_params = active_params
        self.studies = {}
        self.db_manager = PostgresManager() # Initialize db manager for the whole process
        os.makedirs(GENIUS_OUTPUT_DIR, exist_ok=True)
        logger.info("🧠 Genius Optimizer initialized.")

    def run_study_for_regime(self, regime: int, data_segment: pd.DataFrame):
        """
        Creates and runs a full Optuna study for a single market regime
        using a specific segment of data.
        """
        study_name = f"genius_optimization_{self.bot_name}_regime_{regime}"
        storage_url = f"sqlite:///{GENIUS_OUTPUT_DIR}{study_name}.db"

        logger.info(f"--- Starting optimization for [Regime {regime}] ---")
        logger.info(f"Study: {study_name}, Storage: {storage_url}, Data points: {len(data_segment)}")

        regime_active_params = self.active_params.copy()
        regime_active_params["active_regime"] = regime

        objective_function = create_objective_function(
            bot_name=self.bot_name,
            db_manager=self.db_manager,
            active_params=regime_active_params,
            data_segment=data_segment
        )

        study = optuna.create_study(
            study_name=study_name,
            storage=storage_url,
            direction="maximize",
            load_if_exists=True
        )

        # Prune previous trials if they are no longer relevant
        if study.trials and any(t.state == optuna.trial.TrialState.PRUNED for t in study.trials):
             logger.info("Pruning previous failed trials from the study.")
             # This is a bit complex, might need a helper function if needed often

        # --- TUI Callback ---
        tui_callback_dir = Path(".tui_files")
        tui_callback_dir.mkdir(exist_ok=True)

        def tui_callback(study: optuna.study.Study, trial: optuna.trial.FrozenTrial):
            """
            Callback to write trial results to a JSON file for the TUI to read.
            This will be called after each trial is completed.
            """
            # We add user attrs in the objective function to get more detailed results
            final_balance = trial.user_attrs.get("final_balance", 0.0)
            max_drawdown = trial.user_attrs.get("max_drawdown", 0.0)
            win_rate = trial.user_attrs.get("win_rate", 0.0)

            trial_data = {
                "regime": regime,
                "number": trial.number,
                "state": trial.state.name,
                "score": trial.value,
                "final_balance": final_balance,
                "max_drawdown": max_drawdown,
                "win_rate": win_rate,
                "params": trial.params,
                "datetime_start": trial.datetime_start.isoformat() if trial.datetime_start else None,
            }
            # A unique filename for each trial to avoid race conditions
            file_path = tui_callback_dir / f"genius_trial_{regime}_{trial.number}.json"
            with open(file_path, "w") as f:
                json.dump(trial_data, f, indent=4)

            # Also write a summary of the best trial so far for this regime
            best_trial = study.best_trial
            if best_trial:
                best_trial_data = {
                    "regime": regime,
                    "number": best_trial.number,
                    "score": best_trial.value,
                    "final_balance": best_trial.user_attrs.get("final_balance", 0.0),
                    "max_drawdown": best_trial.user_attrs.get("max_drawdown", 0.0),
                    "win_rate": best_trial.user_attrs.get("win_rate", 0.0),
                }
                summary_path = tui_callback_dir / f"genius_summary_regime_{regime}.json"
                with open(summary_path, "w") as f:
                    json.dump(best_trial_data, f, indent=4)


        study.optimize(
            objective_function,
            n_trials=self.n_trials,
            callbacks=[tui_callback]
        )

        self.studies[regime] = study
        logger.info(f"--- Finished optimization for [Regime {regime}] ---")
        logger.info(f"Best score: {study.best_value}")
        logger.info(f"Best params: {study.best_params}")

        save_best_params_for_regime(study, regime)
        generate_importance_report(study, regime)

    def run(self):
        """
        The main entry point to start the optimization process.
        """
        logger.info("🚀 Starting Genius Optimization process...")

        # 1. Segment data by market regime
        logger.info("STEP 1: Analyzing and segmenting historical data...")
        regime_analyzer = RegimeAnalyzer(db_manager=self.db_manager, days=self.days)
        segmented_data = regime_analyzer.run()

        if not segmented_data:
            logger.error("No data segments were created. Aborting optimization.")
            return

        # 2. Loop through regimes and run optimization for each
        logger.info("STEP 2: Running optimization for each market regime...")
        for regime, data_segment in segmented_data.items():
            self.run_study_for_regime(regime, data_segment)

        # 3. Aggregate final results
        logger.info("STEP 3: Aggregating best parameters from all regimes...")
        aggregate_results()

        logger.info("✅ Genius Optimization process finished successfully!")
        logger.info(f"All results and reports saved in '{GENIUS_OUTPUT_DIR}' directory.")
