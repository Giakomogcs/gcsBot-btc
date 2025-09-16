import os
import pandas as pd
import optuna
from pathlib import Path
import json
import concurrent.futures
import threading
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
        self.global_best_lock = threading.Lock() # Lock for thread-safe access to the global best trial file
        self.best_overall_score = float('-inf') # Track the best score in memory
        os.makedirs(GENIUS_OUTPUT_DIR, exist_ok=True)
        # Clean up old TUI files before a new run
        self._cleanup_tui_files()
        logger.info("🧠 Genius Optimizer initialized.")

    def _cleanup_tui_files(self):
        """Removes old trial and summary files from the .tui_files directory."""
        tui_dir = Path(".tui_files")
        if not tui_dir.exists():
            tui_dir.mkdir(exist_ok=True)
            return

        logger.info(f"Cleaning up old TUI files in {tui_dir}...")
        files_to_delete = list(tui_dir.glob("genius_*.json"))
        files_to_delete.extend(list(tui_dir.glob("best_overall_trial.json")))
        # We keep the baseline summary, as it's generated before this class is instantiated

        for f in files_to_delete:
            try:
                os.remove(f)
            except OSError as e:
                logger.warning(f"Could not remove TUI file {f}: {e}")


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
            Callback to write trial results to JSON files for the TUI to read.
            This will be called after each trial is completed.
            """
            if trial.state != optuna.trial.TrialState.COMPLETE:
                return # Don't log non-completed trials

            # --- Log individual trial file (for the live log) ---
            # This part remains mostly the same.
            trial_data = {
                "regime": regime,
                "number": trial.number,
                "state": trial.state.name,
                "score": trial.value,
                "params": trial.params,
                "datetime_start": trial.datetime_start.isoformat() if trial.datetime_start else None,
                # Add the full summary to the individual log file as well
                "summary": trial.user_attrs.get("full_summary", {})
            }
            file_path = tui_callback_dir / f"genius_trial_{regime}_{trial.number}.json"
            with open(file_path, "w") as f:
                json.dump(trial_data, f, indent=4)

            # --- Update the global best trial file (thread-safe) ---
            with self.global_best_lock:
                # Use the in-memory score for a quick check
                if trial.value is not None and trial.value > self.best_overall_score:
                    self.best_overall_score = trial.value # Update in-memory score

                    # Prepare the data for the best trial summary
                    best_trial_summary = {
                        "regime": regime,
                        "trial_number": trial.number,
                        "score": trial.value,
                        "params": trial.params,
                        "summary": trial.user_attrs.get("full_summary", {}) # Get the full summary dict
                    }

                    # Write the new best to the file
                    best_trial_file = tui_callback_dir / "best_overall_trial.json"
                    with open(best_trial_file, "w") as f:
                        json.dump(best_trial_summary, f, indent=4)

                    logger.info(f"🏆 New best trial found! Score: {trial.value:.4f}, Regime: {regime}, Trial: {trial.number}")


        study.optimize(
            objective_function,
            n_trials=self.n_trials,
            callbacks=[tui_callback]
        )

        self.studies[regime] = study
        logger.info(f"--- Finished optimization for [Regime {regime}] ---")
        logger.info(f"Best score: {study.best_value}")
        logger.info(f"Best params: {study.best_params}")

        save_best_params_for_regime(study, regime, self.bot_name)
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

        # 2. Run optimization for each regime in parallel
        logger.info(f"STEP 2: Running optimization for {len(segmented_data)} market regimes in parallel...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(segmented_data)) as executor:
            # Create a future for each regime optimization
            futures = {
                executor.submit(self.run_study_for_regime, regime, data_segment): regime
                for regime, data_segment in segmented_data.items()
            }

            for future in concurrent.futures.as_completed(futures):
                regime = futures[future]
                try:
                    # block and get the result, or exception
                    future.result()  
                except Exception as exc:
                    logger.error(f"Regime {regime} optimization generated an exception: {exc}", exc_info=True)

        # 3. Aggregate final results
        logger.info("STEP 3: Aggregating best parameters from all regimes...")
        aggregate_results()

        logger.info("✅ Genius Optimization process finished successfully!")
        logger.info(f"All results and reports saved in '{GENIUS_OUTPUT_DIR}' directory.")
