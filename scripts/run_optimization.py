import argparse
import json
import itertools
import pandas as pd
import numpy as np
from pathlib import Path
import copy
from datetime import datetime
from decimal import Decimal

# Add project root to path to allow direct script execution
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.logger import logger
from jules_bot.utils.config_manager import ConfigManager, config_manager
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.backtesting.engine import Backtester
from jules_bot.optimization.strategy_generator import StrategyGenerator

def generate_parameter_combinations(config: dict) -> tuple:
    """
    Generates all possible combinations of parameters from the optimization config.
    Returns the combinations and the parameter definitions.
    """
    param_definitions = config.get('parameters', {})
    param_names = list(param_definitions.keys())
    value_lists = []

    for name in param_names:
        param = param_definitions[name]
        if 'values' in param:
            value_lists.append(param['values'])
        elif 'range' in param:
            start = param['range']['min']
            stop = param['range']['max']
            step = param['range']['step']
            values = np.arange(start, stop + step * 0.5, step).tolist()
            value_lists.append([f"{v:.8f}".rstrip('0').rstrip('.') for v in values])
        else:
            raise ValueError(f"Parameter '{name}' must have either 'values' or 'range' defined.")

    combinations = list(itertools.product(*value_lists))
    param_sets = [dict(zip(param_names, combo)) for combo in combinations]
    return param_sets, param_definitions

def run_optimization(backtest_days: int, config_path: Path = None, smart_tune: bool = False, initial_balance: float = None):
    """
    Main function to run the optimization process.
    """
    logger.info(f"--- Starting Strategy Optimization ---")

    opt_config = {}
    if smart_tune:
        logger.info("Smart Tune mode enabled. Generating adaptive parameter ranges.")
        if initial_balance is None:
            balance_str = config_manager.get('BACKTEST', 'initial_balance', '1000.0')
            initial_balance = Decimal(balance_str)
        else:
            initial_balance = Decimal(str(initial_balance))

        strategy_gen = StrategyGenerator(config_manager)
        opt_config = strategy_gen.generate_parameter_space(initial_balance)
        logger.info(f"Generated strategy for a portfolio of ${initial_balance:,.2f}")

    elif config_path:
        logger.info(f"Loading optimization configuration from: {config_path}")
        with open(config_path, 'r') as f:
            opt_config = json.load(f)
    else:
        logger.error("Optimization requires a config file (`--config`) or smart tune mode (`--smart-tune`).")
        return

    param_sets, param_definitions = generate_parameter_combinations(opt_config)
    total_runs = len(param_sets)
    logger.info(f"Generated {total_runs} unique parameter combinations to test.")

    db_manager = PostgresManager()
    all_results = []

    for i, params in enumerate(param_sets):
        run_number = i + 1
        logger.info(f"--- Running Backtest {run_number}/{total_runs} ---")
        logger.info(f"Parameters: {params}")

        try:
            temp_cm = copy.deepcopy(config_manager)

            config_update_dict = {}
            for param_name, param_value in params.items():
                section = param_definitions[param_name]['section']
                if section not in config_update_dict:
                    config_update_dict[section] = {}
                config_update_dict[section][param_name] = param_value

            temp_cm.update_from_dict(config_update_dict)

            backtester = Backtester(
                db_manager=db_manager,
                days=backtest_days,
                config_manager_override=temp_cm
            )

            summary = backtester.run()

            if summary and "error" not in summary:
                run_result = {**params, **summary}
                all_results.append(run_result)
            else:
                logger.error(f"Backtest run {run_number} failed or produced no results. Skipping.")
                all_results.append({**params, "Error": summary.get("error", "Unknown error")})

        except Exception as e:
            logger.critical(f"A critical error occurred during backtest run {run_number}: {e}", exc_info=True)
            all_results.append({**params, "Error": str(e)})

    logger.info("--- Optimization Finished ---")

    if not all_results:
        logger.warning("No backtest runs completed successfully. No report to generate.")
        return

    results_df = pd.DataFrame(all_results)
    settings = opt_config.get('settings', {})
    sort_by_metric = settings.get('sort_by', 'Net P&L')
    sort_ascending = settings.get('ascending', False)

    if sort_by_metric in results_df.columns:
        results_df = results_df.sort_values(by=sort_by_metric, ascending=sort_ascending)
    else:
        logger.warning(f"Sort metric '{sort_by_metric}' not found in results. Not sorting.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_filename = f"optimization_results_{timestamp}.csv"
    results_df.to_csv(results_filename, index=False, float_format='%.8f')
    logger.info(f"Full optimization results saved to: {results_filename}")

    top_n = settings.get('top_n_results', 10)
    logger.info(f"--- Top {top_n} Performing Strategies (sorted by {sort_by_metric}) ---")

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)

    print("\n" + results_df.head(top_n).to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run strategy optimization by backtesting multiple parameter combinations.")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to the optimization configuration JSON file for manual mode."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="The number of past days to run the backtest over."
    )
    parser.add_argument(
        '--smart-tune',
        action='store_true',
        help="Enable Smart Tune mode to auto-generate adaptive parameter ranges."
    )
    parser.add_argument(
        '--initial-balance',
        type=float,
        default=None,
        help="Specify the initial balance for Smart Tune mode. Overrides config.ini."
    )
    parser.add_argument(
        "--bot-name",
        type=str,
        default="jules_bot",
        help="The name of the bot configuration to use."
    )
    args = parser.parse_args()

    # Initialize the global config manager with the specified bot name
    # This is crucial for components like PostgresManager that rely on it.
    config_manager.initialize(args.bot_name)

    if not args.smart_tune and not args.config:
        logger.error("You must either specify a --config file for manual mode or use --smart-tune for automatic mode.")
        sys.exit(1)

    if args.smart_tune:
        run_optimization(backtest_days=args.days, smart_tune=True, initial_balance=args.initial_balance)
    else:
        config_file_path = Path(args.config)
        if not config_file_path.exists():
            example_path = Path("optimization_config.json.example")
            if config_file_path.name == "optimization_config.json" and example_path.exists():
                logger.warning("optimization_config.json not found, using example file.")
                config_file_path = example_path
            else:
                logger.error(f"Optimization config file not found: {config_file_path}")
                sys.exit(1)
        run_optimization(backtest_days=args.days, config_path=config_file_path)
