import os
import sys
import optuna
import logging
from decimal import Decimal
from pathlib import Path
import json

# Adiciona a raiz do projeto ao path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.config_manager import config_manager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.backtesting.engine import Backtester
from jules_bot.utils.logger import logger

# Mapeamento de perfis de carteira para capital inicial
WALLET_PROFILES = {
    "beginner": "100.0",
    "intermediate": "1000.0",
    "advanced": "10000.0"
}

# Diretório para salvar todos os outputs da otimização
OPTIMIZE_OUTPUT_DIR = "optimize/"
# Arquivo para salvar os melhores parâmetros encontrados
BEST_PARAMS_FILE = f"{OPTIMIZE_OUTPUT_DIR}.best_params.env"

def define_search_space(trial: optuna.Trial, wallet_profile: str) -> dict:
    """
    Define o espaço de busca para a otimização e retorna um dicionário de overrides.
    """
    overrides = {}

    # --- Configurações Gerais da Estratégia ---
    overrides["STRATEGY_RULES_TARGET_PROFIT"] = str(trial.suggest_float("STRATEGY_RULES_TARGET_PROFIT", 0.002, 0.015, log=True))
    overrides["STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT"] = str(trial.suggest_float("STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT", 0.001, 0.01, log=True))

    # --- Parâmetros do Trailing Stop Dinâmico ---
    overrides["STRATEGY_RULES_DYNAMIC_TRAIL_MIN_PCT"] = str(trial.suggest_float("STRATEGY_RULES_DYNAMIC_TRAIL_MIN_PCT", 0.005, 0.02, log=True))
    overrides["STRATEGY_RULES_DYNAMIC_TRAIL_MAX_PCT"] = str(trial.suggest_float("STRATEGY_RULES_DYNAMIC_TRAIL_MAX_PCT", 0.02, 0.08, log=True))
    overrides["STRATEGY_RULES_DYNAMIC_TRAIL_PROFIT_SCALING"] = str(trial.suggest_float("STRATEGY_RULES_DYNAMIC_TRAIL_PROFIT_SCALING", 0.05, 0.25))

    # --- Gestão de Capital (Dimensionamento de Ordem) ---
    overrides["STRATEGY_RULES_MIN_ORDER_PERCENTAGE"] = str(trial.suggest_float("STRATEGY_RULES_MIN_ORDER_PERCENTAGE", 0.003, 0.01, log=True))
    overrides["STRATEGY_RULES_MAX_ORDER_PERCENTAGE"] = str(trial.suggest_float("STRATEGY_RULES_MAX_ORDER_PERCENTAGE", 0.01, 0.05, log=True))
    overrides["STRATEGY_RULES_LOG_SCALING_FACTOR"] = str(trial.suggest_float("STRATEGY_RULES_LOG_SCALING_FACTOR", 0.001, 0.005, log=True))

    # --- Dificuldade de Compra ---
    overrides["STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD"] = str(trial.suggest_int("STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD", 3, 10))
    overrides["STRATEGY_RULES_DIFFICULTY_ADJUSTMENT_FACTOR"] = str(trial.suggest_float("STRATEGY_RULES_DIFFICULTY_ADJUSTMENT_FACTOR", 0.001, 0.01, log=True))

    # --- Parâmetros Específicos por Regime ---
    for i in range(4): # Para regimes 0, 1, 2, 3
        overrides[f"REGIME_{i}_BUY_DIP_PERCENTAGE"] = str(trial.suggest_float(f"REGIME_{i}_BUY_DIP_PERCENTAGE", 0.001, 0.05, log=True))
        overrides[f"REGIME_{i}_SELL_RISE_PERCENTAGE"] = str(trial.suggest_float(f"REGIME_{i}_SELL_RISE_PERCENTAGE", 0.002, 0.03, log=True))


    # --- Configuração da Carteira ---
    initial_balance = WALLET_PROFILES.get(wallet_profile, "1000.0")
    overrides["BACKTEST_INITIAL_BALANCE"] = initial_balance

    return overrides


def objective(trial: optuna.Trial, bot_name: str, days: int, wallet_profile: str) -> float:
    """
    A função objetivo que o Optuna tentará maximizar.
    """
    # original_log_level = logging.getLogger('jules_bot').getEffectiveLevel()
    try:
        # O log não é mais silenciado aqui. Será controlado pelo handler do TUI.
        # logging.getLogger('jules_bot').setLevel(logging.WARNING)

        config_overrides = define_search_space(trial, wallet_profile)

        # O ConfigManager agora é instanciado por trial para garantir isolamento
        from jules_bot.utils.config_manager import ConfigManager
        trial_config_manager = ConfigManager()
        trial_config_manager.initialize(bot_name)
        trial_config_manager.apply_overrides(config_overrides)

        db_manager = PostgresManager(config_manager=trial_config_manager)

        backtester = Backtester(
            db_manager=db_manager,
            days=days,
            config_manager=trial_config_manager # Passa o config manager específico do trial
        )
        final_balance = backtester.run(trial=trial)

        if final_balance is None:
             return 0.0

        return float(final_balance)

    except optuna.TrialPruned:
        # Essencial para que o Optuna saiba que o trial foi podado
        raise

    except Exception as e:
        logger.error(f"--- Optuna Trial #{trial.number}: FAILED. Error: {e} ---", exc_info=True)
        return 0.0

    # finally:
        # A restauração do nível de log não é mais necessária
        # logging.getLogger('jules_bot').setLevel(original_log_level)

def run_optimization(bot_name: str, n_trials: int, days: int, wallet_profile: str):
    """
    Orquestra o processo de otimização.
    """
    # Garante que o diretório de output exista
    os.makedirs(OPTIMIZE_OUTPUT_DIR, exist_ok=True)

    study_name = f"optimization_{bot_name}"
    storage_url = f"sqlite:///{OPTIMIZE_OUTPUT_DIR}jules_bot_optimization.db"

    logger.info(f"Starting optimization study '{study_name}'...")
    logger.info(f"Storage: {storage_url}, Trials: {n_trials}, Days: {days}, Profile: {wallet_profile}")

    # Configura o pruner para cortar trials não promissores
    pruner = optuna.pruners.MedianPruner()
    study = optuna.create_study(
        study_name=study_name,
        storage=storage_url,
        direction="maximize",
        pruner=pruner,
        load_if_exists=True
    )

    # --- Log de Aprendizagem Evolutiva ---
    n_existing_trials = len(study.trials)
    if n_existing_trials > 0:
        logger.info(f"🧠 Found existing study with {n_existing_trials} trials. Resuming optimization.")
    else:
        logger.info("🧠 Starting new optimization study.")


    # --- Callback for TUI ---
    tui_callback_dir = Path(".tui_files")
    tui_callback_dir.mkdir(exist_ok=True)

    def tui_callback(study: optuna.study.Study, trial: optuna.trial.FrozenTrial):
        """
        Callback to write trial results to a JSON file for the TUI to read.
        """
        trial_data = {
            "number": trial.number,
            "state": trial.state.name,
            "value": trial.value,
            "params": trial.params,
            "datetime_start": trial.datetime_start.isoformat() if trial.datetime_start else None,
            "datetime_complete": trial.datetime_complete.isoformat() if trial.datetime_complete else None,
        }

        # Write to a file specific to this trial
        with open(tui_callback_dir / f"trial_{trial.number}.json", "w") as f:
            json.dump(trial_data, f, indent=4)

        # Also, update the summary of the best trial so far
        try:
            best_trial = study.best_trial
            best_trial_data = {
                "number": best_trial.number,
                "value": best_trial.value,
                "params": best_trial.params,
            }
            with open(tui_callback_dir / "best_trial_summary.json", "w") as f:
                json.dump(best_trial_data, f, indent=4)
        except ValueError:
            # No best trial yet
            pass


    objective_func = lambda trial: objective(trial, bot_name, days, wallet_profile)

    try:
        study.optimize(
            objective_func,
            n_trials=n_trials,
            callbacks=[tui_callback],
            show_progress_bar=False # TUI will be the progress bar
        )
    except KeyboardInterrupt:
        logger.warning("\nOptimization stopped by user.")

    logger.info("="*30 + " OPTIMIZATION FINISHED " + "="*30)

    try:
        best_trial = study.best_trial
        logger.info(f"Best trial: #{best_trial.number} -> Final Balance: ${best_trial.value:,.2f}")

        logger.info("  -> Saving best parameters to " + BEST_PARAMS_FILE)
        with open(BEST_PARAMS_FILE, 'w') as f:
            f.write(f"# Best parameters for bot '{bot_name}' from study '{study_name}'\n")
            f.write(f"# Final Balance: {best_trial.value:.2f}\n\n")
            for key, value in best_trial.params.items():
                if "PROFIT_MULTIPLIER" in key:
                    base_profit = best_trial.params.get("STRATEGY_RULES_TARGET_PROFIT", 0.005)
                    original_key = key.replace("_PROFIT_MULTIPLIER", "_TARGET_PROFIT")
                    final_value = base_profit * value
                    f.write(f"{original_key.upper()}={final_value}\n")
                else:
                    f.write(f"{key.upper()}={value}\n")
        logger.info(f"✅ Best parameters saved successfully.")

    except ValueError:
        logger.warning("No successful trials were completed. Could not determine best parameters.")
