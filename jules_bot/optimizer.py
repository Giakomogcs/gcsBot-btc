import os
import sys
import optuna
import logging
from decimal import Decimal

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

# Arquivo para salvar os melhores parâmetros encontrados
BEST_PARAMS_FILE = ".best_params.env"

def define_search_space(trial: optuna.Trial, wallet_profile: str) -> None:
    """
    Define o espaço de busca para a otimização, sugerindo valores para os parâmetros.
    Os valores são diretamente definidos como variáveis de ambiente para esta "tentativa".
    """
    # --- Configurações Gerais da Estratégia ---
    os.environ["STRATEGY_RULES_TARGET_PROFIT"] = str(trial.suggest_float("STRATEGY_RULES_TARGET_PROFIT", 0.002, 0.015, log=True))
    os.environ["STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT"] = str(trial.suggest_float("STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT", 0.001, 0.01, log=True))

    # --- Parâmetros do Trailing Stop Dinâmico ---
    os.environ["STRATEGY_RULES_DYNAMIC_TRAIL_MIN_PCT"] = str(trial.suggest_float("STRATEGY_RULES_DYNAMIC_TRAIL_MIN_PCT", 0.005, 0.02, log=True))
    os.environ["STRATEGY_RULES_DYNAMIC_TRAIL_MAX_PCT"] = str(trial.suggest_float("STRATEGY_RULES_DYNAMIC_TRAIL_MAX_PCT", 0.02, 0.08, log=True))
    os.environ["STRATEGY_RULES_DYNAMIC_TRAIL_PROFIT_SCALING"] = str(trial.suggest_float("STRATEGY_RULES_DYNAMIC_TRAIL_PROFIT_SCALING", 0.05, 0.25))

    # --- Gestão de Capital (Dimensionamento de Ordem) ---
    os.environ["STRATEGY_RULES_MIN_ORDER_PERCENTAGE"] = str(trial.suggest_float("STRATEGY_RULES_MIN_ORDER_PERCENTAGE", 0.003, 0.01, log=True))
    os.environ["STRATEGY_RULES_MAX_ORDER_PERCENTAGE"] = str(trial.suggest_float("STRATEGY_RULES_MAX_ORDER_PERCENTAGE", 0.01, 0.05, log=True))
    os.environ["STRATEGY_RULES_LOG_SCALING_FACTOR"] = str(trial.suggest_float("STRATEGY_RULES_LOG_SCALING_FACTOR", 0.001, 0.005, log=True))

    # --- Parâmetros Específicos por Regime ---
    base_profit_target = float(os.environ["STRATEGY_RULES_TARGET_PROFIT"])
    regime_0_multiplier = trial.suggest_float("REGIME_0_PROFIT_MULTIPLIER", 0.5, 1.0)
    os.environ["REGIME_0_TARGET_PROFIT"] = str(base_profit_target * regime_0_multiplier)
    regime_1_multiplier = trial.suggest_float("REGIME_1_PROFIT_MULTIPLIER", 0.9, 2.0)
    os.environ["REGIME_1_TARGET_PROFIT"] = str(base_profit_target * regime_1_multiplier)
    regime_2_multiplier = trial.suggest_float("REGIME_2_PROFIT_MULTIPLIER", 1.2, 3.0)
    os.environ["REGIME_2_TARGET_PROFIT"] = str(base_profit_target * regime_2_multiplier)
    regime_3_multiplier = trial.suggest_float("REGIME_3_PROFIT_MULTIPLIER", 0.6, 1.2)
    os.environ["REGIME_3_TARGET_PROFIT"] = str(base_profit_target * regime_3_multiplier)

    # --- Configuração da Carteira ---
    initial_balance = WALLET_PROFILES.get(wallet_profile, "1000.0")
    os.environ["BACKTEST_INITIAL_BALANCE"] = initial_balance

def objective(trial: optuna.Trial, bot_name: str, days: int, wallet_profile: str) -> float:
    """
    A função objetivo que o Optuna tentará maximizar.
    """
    original_log_level = logging.getLogger('jules_bot').getEffectiveLevel()
    try:
        # Silenciar logs durante a otimização para uma saída mais limpa
        logging.getLogger('jules_bot').setLevel(logging.WARNING)

        define_search_space(trial, wallet_profile)
        config_manager.initialize(bot_name)

        db_manager = PostgresManager()
        db_manager.clear_backtest_trades()

        backtester = Backtester(db_manager=db_manager, days=days)
        # Passa o 'trial' para o backtester para permitir o pruning
        final_balance = backtester.run(trial=trial)

        if final_balance is None:
             return 0.0

        return float(final_balance)

    except optuna.TrialPruned:
        # Essencial para que o Optuna saiba que o trial foi podado
        raise

    except Exception as e:
        logger.error(f"--- Optuna Trial #{trial.number}: FAILED. Error: {e} ---", exc_info=False)
        return 0.0

    finally:
        # Restaura o nível de log original
        logging.getLogger('jules_bot').setLevel(original_log_level)

def run_optimization(bot_name: str, n_trials: int, days: int, wallet_profile: str):
    """
    Orquestra o processo de otimização.
    """
    study_name = f"optimization_{bot_name}"
    storage_url = "sqlite:///jules_bot_optimization.db"

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

    objective_func = lambda trial: objective(trial, bot_name, days, wallet_profile)

    try:
        study.optimize(objective_func, n_trials=n_trials, show_progress_bar=True)
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
