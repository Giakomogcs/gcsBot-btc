import optuna
from typing import Dict, Any, List

def define_search_space(trial: optuna.Trial, active_params: Dict[str, Any]) -> Dict[str, str]:
    """
    Defines the comprehensive, configurable search space for the Genius Optimizer.

    Args:
        trial: An Optuna trial object.
        active_params: A dictionary specifying which parameters should be optimized
                       in this particular run. This allows for focused optimization.

    Returns:
        A dictionary of parameter overrides to be used in the backtest.
        All values are converted to strings, as they will be used as env vars.
    """
    overrides = {}

    # --- Boolean Flags for Core Strategy Features ---
    if "USE_DYNAMIC_TRAILING_STOP" in active_params:
        overrides["STRATEGY_RULES_USE_DYNAMIC_TRAILING_STOP"] = trial.suggest_categorical(
            "STRATEGY_RULES_USE_DYNAMIC_TRAILING_STOP", [True, False]
        )

    if "USE_REVERSAL_BUY_STRATEGY" in active_params:
        overrides["STRATEGY_RULES_USE_REVERSAL_BUY_STRATEGY"] = trial.suggest_categorical(
            "STRATEGY_RULES_USE_REVERSAL_BUY_STRATEGY", [True, False]
        )

    # --- Dynamic Trailing Stop Parameters ---
    # These are only suggested if the feature is active for this trial
    use_dts = overrides.get("STRATEGY_RULES_USE_DYNAMIC_TRAILING_STOP", True)
    if use_dts and "DYNAMIC_TRAIL" in active_params:
        overrides["STRATEGY_RULES_DYNAMIC_TRAIL_MIN_PCT"] = trial.suggest_float(
            "STRATEGY_RULES_DYNAMIC_TRAIL_MIN_PCT", 0.005, 0.02, log=True
        )
        overrides["STRATEGY_RULES_DYNAMIC_TRAIL_MAX_PCT"] = trial.suggest_float(
            "STRATEGY_RULES_DYNAMIC_TRAIL_MAX_PCT", 0.02, 0.08, log=True
        )
        overrides["STRATEGY_RULES_DYNAMIC_TRAIL_PROFIT_SCALING"] = trial.suggest_float(
            "STRATEGY_RULES_DYNAMIC_TRAIL_PROFIT_SCALING", 0.05, 0.25
        )

    # --- Reversal Buy Strategy Parameters ---
    use_reversal = overrides.get("STRATEGY_RULES_USE_REVERSAL_BUY_STRATEGY", True)
    if use_reversal and "REVERSAL_BUY" in active_params:
        overrides["STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT"] = trial.suggest_float(
            "STRATEGY_RULES_REVERSAL_BUY_THRESHOLD_PERCENT", 0.001, 0.01, log=True
        )
        overrides["STRATEGY_RULES_REVERSAL_MONITORING_TIMEOUT_SECONDS"] = trial.suggest_int(
            "STRATEGY_RULES_REVERSAL_MONITORING_TIMEOUT_SECONDS", 60, 300
        )

    # --- Capital and Order Sizing ---
    if "SIZING" in active_params:
        overrides["STRATEGY_RULES_MIN_ORDER_PERCENTAGE"] = trial.suggest_float(
            "STRATEGY_RULES_MIN_ORDER_PERCENTAGE", 0.003, 0.01, log=True
        )
        overrides["STRATEGY_RULES_MAX_ORDER_PERCENTAGE"] = trial.suggest_float(
            "STRATEGY_RULES_MAX_ORDER_PERCENTAGE", 0.01, 0.05, log=True
        )
        overrides["STRATEGY_RULES_LOG_SCALING_FACTOR"] = trial.suggest_float(
            "STRATEGY_RULES_LOG_SCALING_FACTOR", 0.001, 0.005, log=True
        )

    # --- Incremental Buy Difficulty ---
    if "DIFFICULTY" in active_params:
        overrides["STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD"] = trial.suggest_int(
            "STRATEGY_RULES_CONSECUTIVE_BUYS_THRESHOLD", 3, 10
        )
        overrides["STRATEGY_RULES_DIFFICULTY_ADJUSTMENT_FACTOR"] = trial.suggest_float(
            "STRATEGY_RULES_DIFFICULTY_ADJUSTMENT_FACTOR", 0.001, 0.01, log=True
        )
        overrides["STRATEGY_RULES_DIFFICULTY_RESET_TIMEOUT_HOURS"] = trial.suggest_int(
            "STRATEGY_RULES_DIFFICULTY_RESET_TIMEOUT_HOURS", 1, 12
        )

    # --- Regime-Specific Parameters ---
    # This logic assumes we are optimizing for ONE regime at a time.
    # The 'active_regime' will be passed in the 'active_params' dict.
    regime = active_params.get("active_regime")
    if regime is not None:
        prefix = f"REGIME_{regime}"
        overrides[f"{prefix}_BUY_DIP_PERCENTAGE"] = trial.suggest_float(
            f"{prefix}_BUY_DIP_PERCENTAGE", 0.001, 0.05, log=True
        )
        overrides[f"{prefix}_SELL_RISE_PERCENTAGE"] = trial.suggest_float(
            f"{prefix}_SELL_RISE_PERCENTAGE", 0.002, 0.03, log=True
        )
        overrides[f"{prefix}_TARGET_PROFIT"] = trial.suggest_float(
            f"{prefix}_TARGET_PROFIT", 0.002, 0.02, log=True
        )

    # --- Data Pipeline Parameters (Advanced) ---
    # Placeholder for optimizing the features used to define regimes.
    # This would involve suggesting combinations of features.
    # if "REGIME_FEATURES" in active_params:
    #     features = ["atr_14", "macd_diff_12_26_9", "rsi_14", "bb_bbm_14"]
    #     # Suggest a subset of features to use
    #     n_features = trial.suggest_int("n_features", 2, len(features))
    #     suggested_features = trial.suggest_categorical("regime_features",
    #         list(itertools.combinations(features, n_features)))
    #     overrides["DATA_PIPELINE_REGIME_FEATURES"] = ",".join(suggested_features)


    # Convert all override values to strings for the config manager
    for key, value in overrides.items():
        overrides[key] = str(value)

    return overrides
