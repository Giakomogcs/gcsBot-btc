import os
import optuna
from jules_bot.utils.logger import logger

# Directory for saving all genius optimization outputs
GENIUS_OUTPUT_DIR = "optimize/genius/"

# Mapping from regime index to a human-readable name, used for .env files
REGIME_NAMES = {
    0: "ranging",
    1: "uptrend",
    2: "high_volatility",
    3: "downtrend"
}

def save_best_params_for_regime(study: optuna.Study, regime: int, bot_name: str):
    """
    Saves the best parameters for a specific regime to a .env file in the project root.
    The filename will be, for example, '.env.uptrend'.
    The variables are prefixed with the bot's name (e.g., JULES_BOT_).
    """
    regime_name = REGIME_NAMES.get(regime)
    if not regime_name:
        logger.warning(f"Unknown regime index {regime}, cannot save .env file.")
        return

    # Save the .env file in the project root for easy use with `run.py`
    file_path = os.path.join(GENIUS_OUTPUT_DIR, f".env.{regime_name}")

    # The prefix for environment variables (e.g., "JULES_BOT_")
    env_prefix = bot_name.upper()

    try:
        os.makedirs(GENIUS_OUTPUT_DIR, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(f"# [GENIUS OPTIMIZER] Best parameters for bot '{bot_name}' in '{regime_name.upper()}' regime\n")
            f.write(f"# Best Score (Objective Value): {study.best_value}\n\n")

            # Also write the active regime number so the bot knows which one it is
            f.write(f"{env_prefix}_ACTIVE_REGIME={regime}\n")

            for key, value in study.best_params.items():
                # Ensure the key is prefixed for the config manager
                prefixed_key = f"{env_prefix}_{key}"
                f.write(f"{prefixed_key}={value}\n")

        logger.info(f"✅ Best parameters for regime '{regime_name.upper()}' saved to '{file_path}'")

    except Exception as e:
        logger.error(f"❌ Failed to save .env file for regime {regime_name}: {e}", exc_info=True)


def aggregate_results():
    """
    Aggregates the best parameters from all regime-specific files
    into a single, final .env file.
    This can be used for reference but is not directly used by the backtester.
    """
    final_params_path = os.path.join(GENIUS_OUTPUT_DIR, "all_regimes_summary.txt")
    logger.info(f"Aggregating all regime parameters into {final_params_path}...")

    try:
        with open(final_params_path, "w") as final_file:
            final_file.write("# Genius Optimizer - Aggregated Best Parameters Summary\n")
            final_file.write("# This file is for reference only.\n\n")

            for i in range(len(REGIME_NAMES)):
                regime_name = REGIME_NAMES.get(i)
                if not regime_name: continue

                env_file_path = os.path.join(GENIUS_OUTPUT_DIR, f".env.{regime_name}")
                if os.path.exists(env_file_path):
                    with open(env_file_path, "r") as regime_file:
                        final_file.write(f"--- START REGIME: {regime_name.upper()} ---\n")
                        final_file.write(regime_file.read())
                        final_file.write(f"--- END REGIME: {regime_name.upper()} ---\n\n")

        logger.info(f"✅ Aggregation summary saved to {final_params_path}.")

    except Exception as e:
        logger.error(f"❌ Failed to aggregate results: {e}", exc_info=True)


def save_best_overall_params(bot_name: str, best_trial_data: dict):
    """
    Saves the best overall parameters to a dedicated .env file.
    """
    file_path = os.path.join(GENIUS_OUTPUT_DIR, ".env.best_overall")
    env_prefix = bot_name.upper()

    try:
        with open(file_path, "w") as f:
            f.write(f"# [GENIUS OPTIMIZER] Best Overall Parameters for bot '{bot_name}'\n")
            f.write(f"# Score: {best_trial_data.get('score', 'N/A')}\n")
            f.write(f"# From Regime: {best_trial_data.get('regime', 'N/A')}, Trial: {best_trial_data.get('trial_number', 'N/A')}\n\n")

            for key, value in best_trial_data.get("params", {}).items():
                prefixed_key = f"{env_prefix}_{key}"
                f.write(f"{prefixed_key}={value}\n")
        logger.info(f"✅ Best overall parameters saved to '{file_path}'")
    except Exception as e:
        logger.error(f"❌ Failed to save best overall .env file: {e}", exc_info=True)


def generate_importance_report(study: optuna.Study, regime: int):
    """
    Generates and saves a parameter importance plot for a given study.
    """
    if not study.trials:
        logger.warning(f"Cannot generate importance report for regime {regime}: No trials completed.")
        return

    try:
        fig = optuna.visualization.plot_param_importances(study)
        report_path = os.path.join(GENIUS_OUTPUT_DIR, f"importance_regime_{regime}.html")
        fig.write_html(report_path)
        logger.info(f"Parameter importance report for regime {regime} saved to {report_path}")
    except Exception as e:
        logger.error(f"Could not generate importance plot for regime {regime}. Error: {e}")
