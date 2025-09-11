import os
import optuna
from jules_bot.utils.logger import logger

# Directory for saving all genius optimization outputs
GENIUS_OUTPUT_DIR = "optimize/genius/"

def save_best_params_for_regime(study: optuna.Study, regime: int):
    """
    Saves the best parameters for a specific regime to a temporary file.
    """
    os.makedirs(GENIUS_OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(GENIUS_OUTPUT_DIR, f"best_params_regime_{regime}.env")

    with open(file_path, "w") as f:
        f.write(f"# Best parameters for Regime {regime}\n")
        f.write(f"# Best Value: {study.best_value}\n")
        for key, value in study.best_params.items():
            f.write(f"{key}={value}\n")
    logger.info(f"Best parameters for regime {regime} saved to {file_path}")

def aggregate_results():
    """
    Aggregates the best parameters from all regime-specific files
    into a single, final .env file.
    """
    final_params_path = os.path.join(GENIUS_OUTPUT_DIR, ".best_params.genius.env")
    logger.info(f"Aggregating all regime parameters into {final_params_path}...")

    with open(final_params_path, "w") as final_file:
        final_file.write("# Genius Optimizer - Aggregated Best Parameters\n\n")
        for i in range(4):
            regime_file_path = os.path.join(GENIUS_OUTPUT_DIR, f"best_params_regime_{i}.env")
            if os.path.exists(regime_file_path):
                with open(regime_file_path, "r") as regime_file:
                    final_file.write(regime_file.read())
                    final_file.write("\n")
    logger.info("Aggregation complete.")

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
