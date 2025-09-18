import os
import sys
import typer
from datetime import datetime, timedelta

# Add project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jules_bot.utils.logger import logger
from collectors.core_price_collector import prepare_backtest_data
from jules_bot.genius_optimizer.genius_optimizer import GeniusOptimizer
from jules_bot.backtesting.engine import Backtester
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
import json
from typing import Optional, List
import pandas as pd
from rich.console import Console
from rich.table import Table

app = typer.Typer()

def run_optimization_for_window(start_date: datetime, end_date: datetime, n_trials: int, seed_params: Optional[dict] = None) -> Optional[dict]:
    """
    Runs the Genius Optimizer for a specific time window.
    """
    logger.info(f"Running optimization from {start_date.date()} to {end_date.date()}...")

    # The active params for the optimizer are read from the bot's config
    active_params_json = config_manager.get('OPTIMIZER', 'active_params_json')
    active_params = json.loads(active_params_json)

    optimizer = GeniusOptimizer(
        bot_name=config_manager.bot_name,
        n_trials=n_trials,
        active_params=active_params,
        start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d'),
        seed_params=seed_params
    )
    best_params = optimizer.run()
    return best_params


def run_backtest_for_window(start_date: datetime, end_date: datetime, params: dict) -> Optional[dict]:
    """
    Runs a backtest for a specific time window with a given set of parameters.
    """
    logger.info(f"Running OOS backtest from {start_date.date()} to {end_date.date()}...")

    try:
        # Apply the best parameters found from the training window as overrides
        config_manager.apply_overrides(params)

        # Instantiate the backtester
        backtester = Backtester(
            db_manager=PostgresManager(), # Use a fresh instance
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            config_manager=config_manager # Pass the global, overridden config
        )

        results = backtester.run(return_full_results=True)
        return results

    except Exception as e:
        logger.error(f"Out-of-sample backtest failed: {e}", exc_info=True)
        return None
    finally:
        # CRITICAL: Always clear the overrides after the backtest is done
        config_manager.clear_overrides()
        logger.info("Configuration overrides cleared.")


def save_best_wfo_params(best_params: dict):
    """
    Saves the best overall parameters found by the WFO to a .env file.
    """
    output_dir = "optimize"
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "wfo_best_params.env")

    logger.info(f"💾 Saving best WFO parameters to '{filepath}'...")

    try:
        with open(filepath, 'w') as f:
            f.write("# Best parameters found by Walk-Forward Optimization\n")
            f.write(f"# Generated on: {datetime.now().isoformat()}\n\n")
            for key, value in best_params.items():
                f.write(f"{key.upper()}={value}\n")
        logger.info("✅ Best parameters saved successfully.")
    except IOError as e:
        logger.error(f"❌ Failed to save best WFO parameters: {e}")


def aggregate_and_display_wfo_results(all_results_with_params: List[tuple]):
    """
    Aggregates results from all OOS windows, displays a final report,
    and saves the best parameter set.
    """
    if not all_results_with_params:
        logger.warning("No out-of-sample results to aggregate.")
        return

    console = Console()
    console.print("\n--- 📊 [bold cyan]Walk-Forward Optimization Final Report[/bold cyan] ---")
    console.print(f"Aggregated results from {len(all_results_with_params)} out-of-sample windows.")

    all_trades = []
    window_performances = []

    # Unpack results and params, calculate metrics for each window
    for result_set, params in all_results_with_params:
        all_trades.extend(result_set.get("trades", []))

        # Calculate profit factor for this specific window
        window_trades_df = pd.DataFrame(result_set.get("trades", []))
        if not window_trades_df.empty:
            sell_trades = window_trades_df[window_trades_df['order_type'] == 'sell']
            winning_trades = sell_trades[sell_trades['realized_pnl_usd'] > 0]
            losing_trades = sell_trades[sell_trades['realized_pnl_usd'] < 0]
            gross_profit = winning_trades['realized_pnl_usd'].sum()
            gross_loss = abs(losing_trades['realized_pnl_usd'].sum())
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
            window_performances.append({'profit_factor': profit_factor, 'params': params})
        else:
            window_performances.append({'profit_factor': 0.0, 'params': params})


    if not all_trades:
        console.print("[yellow]No trades were executed across all out-of-sample periods.[/yellow]")
        return

    # --- Find and Save Best Parameters ---
    if window_performances:
        best_window = max(window_performances, key=lambda x: x['profit_factor'])
        best_params = best_window['params']
        logger.info(f"🏆 Best performing window had Profit Factor: {best_window['profit_factor']:.2f}")
        save_best_wfo_params(best_params)
    else:
        logger.warning("Could not determine best parameters as no windows had trades.")


    # --- Aggregate Overall Metrics for Display ---
    trades_df = pd.DataFrame(all_trades)
    trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'])
    numeric_cols = ['price', 'quantity', 'usd_value', 'commission_usd', 'realized_pnl_usd']
    for col in numeric_cols:
        if col in trades_df.columns:
            trades_df[col] = pd.to_numeric(trades_df[col])

    initial_balance = all_results_with_params[0][0]['initial_balance']
    final_balance = all_results_with_params[-1][0]['final_balance']
    net_pnl_usd = final_balance - initial_balance
    net_pnl_pct = (net_pnl_usd / initial_balance) * 100 if initial_balance > 0 else 0

    sell_trades = trades_df[trades_df['order_type'] == 'sell']
    total_realized_pnl = sell_trades['realized_pnl_usd'].sum()
    total_fees = trades_df['commission_usd'].sum()
    winning_trades = sell_trades[sell_trades['realized_pnl_usd'] > 0]
    losing_trades = sell_trades[sell_trades['realized_pnl_usd'] < 0]
    win_rate = (len(winning_trades) / len(sell_trades)) * 100 if not sell_trades.empty else 0
    gross_profit = winning_trades['realized_pnl_usd'].sum()
    gross_loss = abs(losing_trades['realized_pnl_usd'].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')


    # --- Display Results Table ---
    table = Table(title="[bold]Aggregated Out-of-Sample Performance[/bold]")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold", justify="right")

    table.add_row("Initial Balance", f"${initial_balance:,.2f}")
    table.add_row("Final Balance", f"${final_balance:,.2f}")
    table.add_row("Net PnL", f"${net_pnl_usd:,.2f} ({net_pnl_pct:.2f}%)")
    table.add_row("Total Realized PnL", f"${total_realized_pnl:,.2f}")
    table.add_row("Total Trades", str(len(trades_df)))
    table.add_row("Win Rate (Sell Trades)", f"{win_rate:.2f}%")
    table.add_row("Profit Factor", f"{profit_factor:.2f}" if profit_factor != float('inf') else "∞")
    table.add_row("Total Fees Paid", f"${total_fees:,.2f}")

    console.print(table)


def run_wfo(
    total_days: int,
    training_days: int,
    testing_days: int,
    n_trials_per_window: int,
):
    """
    Main function to run the Walk-Forward Optimization.
    """
    logger.info("--- 🧠 Starting Walk-Forward Optimization ---")
    logger.info(f"Total Period: {total_days} days | Training: {training_days} days | Testing: {testing_days} days | Trials/Window: {n_trials_per_window}")

    # 1. Ensure we have all the necessary historical data for the entire period
    logger.info(f"Ensuring data is available for the last {total_days} days...")
    prepare_backtest_data(days=total_days)
    logger.info("Data preparation complete.")

    # 2. Define the windows for the walk-forward analysis
    end_date = datetime.now()
    start_date = end_date - timedelta(days=total_days)

    current_training_start = start_date
    all_oos_results_with_params = []
    seeded_params = None
    window_num = 1

    while True:
        # Define the boundaries for the current window
        current_training_end = current_training_start + timedelta(days=training_days)
        current_testing_end = current_training_end + timedelta(days=testing_days)

        if current_testing_end > end_date:
            logger.info("Reached the end of the total period. Concluding WFO.")
            break

        logger.info(f"--- Running WFO Window #{window_num} ---")
        logger.info(f"Training Period: {current_training_start.date()} -> {current_training_end.date()}")
        logger.info(f"Testing Period:  {current_training_end.date()} -> {current_testing_end.date()}")

        # 3. Run Genius Optimizer on the training (in-sample) data
        best_params_found = run_optimization_for_window(
            start_date=current_training_start,
            end_date=current_training_end,
            n_trials=n_trials_per_window,
            seed_params=seeded_params
        )

        if not best_params_found:
            logger.warning(f"Window #{window_num}: Optimization did not return any parameters. Skipping this window.")
            current_training_start += timedelta(days=testing_days) # Slide the window
            window_num += 1
            continue

        # 4. Run Backtest on the testing (out-of-sample) data
        oos_results = run_backtest_for_window(
            start_date=current_training_end,
            end_date=current_testing_end,
            params=best_params_found
        )
        if oos_results:
            # Store both the results and the parameters that generated them
            all_oos_results_with_params.append((oos_results, best_params_found))
            logger.info(f"Window #{window_num}: Out-of-sample backtest complete.")
        else:
            logger.warning(f"Window #{window_num}: Out-of-sample backtest failed to produce results.")

        # 5. Prepare for the next window
        seeded_params = best_params_found # Carry over the knowledge
        current_training_start += timedelta(days=testing_days) # Slide the window
        window_num += 1
        logger.info("-" * 50)


    # 6. Aggregate, display, and save final results
    aggregate_and_display_wfo_results(all_oos_results_with_params)
    logger.info("--- ✅ Walk-Forward Optimization Finished ---")


@app.command()
def main(
    total_days: int = typer.Option(180, "--total-days", "-d", help="The total number of days for the entire WFO period."),
    training_days: int = typer.Option(60, "--training-days", "-t", help="The number of days in each training window (in-sample)."),
    testing_days: int = typer.Option(30, "--testing-days", "-v", help="The number of days in each testing window (out-of-sample)."),
    n_trials_per_window: int = typer.Option(100, "--trials", "-n", help="The number of optimization trials to run per window."),
):
    """
    This script runs a full Walk-Forward Optimization (WFO) to find robust
    trading strategy parameters.
    """
    if training_days + testing_days > total_days:
        logger.error("Error: The sum of training and testing days cannot be greater than the total days.")
        raise typer.Exit(code=1)

    run_wfo(
        total_days=total_days,
        training_days=training_days,
        testing_days=testing_days,
        n_trials_per_window=n_trials_per_window,
    )

if __name__ == "__main__":
    app()
