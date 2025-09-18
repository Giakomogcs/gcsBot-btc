import json
import glob
import time
from pathlib import Path
from rich.text import Text
from rich.panel import Panel
from datetime import datetime
import psutil
from decimal import Decimal, InvalidOperation

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Log, DataTable, ProgressBar
from textual.containers import Container, Vertical, ScrollableContainer
from textual.timer import Timer

# Directory where the optimizer drops its progress files
TUI_FILES_DIR = Path(".tui_files")

class ComparisonWidget(Container):
    """A widget to display a side-by-side comparison of a backtest result."""

    def __init__(self, title: str, **kwargs):
        super().__init__(**kwargs)
        self.title_text = title
        self.baseline_summary = {} # Store baseline data for comparison

    def compose(self) -> ComposeResult:
        """Compose the widget's layout."""
        with Container(classes="main_container"):
            yield Static(self.title_text, classes="widget_title")
            with Container(classes="table_container"):
                yield DataTable(id="metrics_table", classes="summary_table")
                yield DataTable(id="params_table", classes="params_table")

    def on_mount(self) -> None:
        """Called when the widget is mounted to set up tables."""
        metrics_table = self.query_one("#metrics_table", DataTable)
        metrics_table.add_column("Metric", width=25)
        metrics_table.add_column("Value", width=20)
        metrics_table.add_column("Improvement", width=20) # New column
        metrics_table.add_row("[dim]Waiting for data...[/dim]", "", "")

        params_table = self.query_one("#params_table", DataTable)
        params_table.add_column("Parameter", width=30)
        params_table.add_column("Best Value", width=20)
        params_table.add_column("Baseline Value", width=20)
        params_table.add_row("[dim]Waiting for data...[/dim]", "", "")

    def update_data(self, data: dict, baseline_data: dict = None):
        """Updates the widget's tables with new data."""
        if not data:
            return

        is_baseline = baseline_data is None

        # Correctly and safely extract all data parts at the beginning
        summary = data.get("summary", {})
        params = data.get("params", {})
        baseline_summary_metrics = baseline_data.get("summary", {}) if baseline_data else {}
        baseline_params = baseline_data.get("params", {}) if baseline_data else {}

        # === Update Metrics Table ===
        metrics_table = self.query_one("#metrics_table", DataTable)
        metrics_table.clear()
        metrics_table.add_column("Metric", width=25)
        metrics_table.add_column("Value", width=20)
        metrics_table.add_column("Improvement", width=20)

        key_metrics = {
            "final_balance": ("Final Balance", "money"),
            "net_pnl_pct": ("Net PnL %", "percent"),
            "win_rate": ("Win Rate", "percent"),
            "profit_factor": ("Profit Factor", "ratio"),
            "max_drawdown": ("Max Drawdown %", "percent_dd"),
            "sharpe_ratio": ("Sharpe Ratio", "ratio"),
            "sortino_ratio": ("Sortino Ratio", "ratio"),
            "sell_trades_count": ("Sell Trades", "integer"),
        }

        for key, (name, metric_type) in key_metrics.items():
            value = summary.get(key)
            value_str = self._format_metric(value, metric_type)

            improvement_str = ""
            # Use the correctly separated baseline_summary_metrics
            if not is_baseline and baseline_summary_metrics:
                baseline_value = baseline_summary_metrics.get(key)
                improvement_str = self._calculate_improvement(value, baseline_value, metric_type)

            metrics_table.add_row(name, value_str, improvement_str)

        if "score" in data:
            metrics_table.add_row("Score", f"{data['score']:.4f}", "")
        if "trial_number" in data:
            metrics_table.add_row("Trial #", str(data['trial_number']), "")

        # === Update Parameters Table ===
        params_table = self.query_one("#params_table", DataTable)
        params_table.clear()
        params_table.add_column("Parameter", width=30)
        params_table.add_column("Best Value", width=20)
        params_table.add_column("Baseline Value", width=20)


        if not params:
            params_table.add_row("[dim]Not applicable.[/dim]", "", "")
        else:
            # Use the correctly separated baseline_params
            all_keys = sorted(list(set(params.keys()) | set(baseline_params.keys())))

            for key in all_keys:
                best_val = params.get(key)
                baseline_val = baseline_params.get(key)

                # Format values
                best_val_str = f"{best_val:.6f}" if isinstance(best_val, float) else str(best_val) if best_val is not None else "[dim]N/A[/dim]"
                baseline_val_str = f"{baseline_val:.6f}" if isinstance(baseline_val, float) else str(baseline_val) if baseline_val is not None else "[dim]N/A[/dim]"

                key_str = key
                # Highlight if the value has changed
                if not is_baseline and str(best_val) != str(baseline_val):
                    key_str = f"[bold yellow]{key}[/bold yellow]"
                    best_val_str = f"[bold yellow]{best_val_str}[/bold yellow]"

                params_table.add_row(key_str, best_val_str, baseline_val_str)

    def _format_metric(self, value, metric_type):
        if value is None: return "[dim]N/A[/dim]"
        try:
            val = Decimal(str(value))
            if metric_type == "money": return f"${val:,.2f}"
            if metric_type == "percent": return f"{val:.2%}"
            if metric_type == "percent_dd": return f"{val * 100:.2f}%"
            if metric_type == "ratio": return f"{val:.2f}"
            if metric_type == "integer": return str(int(val))
            return str(value)
        except (InvalidOperation, TypeError):
            return str(value)

    def _calculate_improvement(self, current_val, baseline_val, metric_type):
        if current_val is None or baseline_val is None: return ""
        try:
            current = Decimal(str(current_val))
            baseline = Decimal(str(baseline_val))

            if baseline == 0 and current > 0: return "[bold green]∞[/]"
            if baseline == 0: return ""

            delta = current - baseline

            # Invert delta for drawdown, since lower is better
            if metric_type == "percent_dd":
                delta = -delta

            style = "bold green" if delta > 0 else "bold red" if delta < 0 else "dim"

            if metric_type in ["percent", "percent_dd"]:
                return f"[{style}]{delta:+.2%}[/{style}]"
            if metric_type in ["money", "ratio"]:
                return f"[{style}]{delta:+,.2f}[/{style}]"
            if metric_type == "integer":
                 return f"[{style}]{int(delta):+d}[/{style}]"
            return ""
        except (InvalidOperation, TypeError):
            return ""


class TradesComparisonWidget(Container):
    """A widget to display a side-by-side comparison of trades."""

    def compose(self) -> ComposeResult:
        with Container(classes="trades_main_container"):
            with Vertical(classes="trade_list_container"):
                yield Static("Baseline Trades", classes="widget_title")
                yield DataTable(id="baseline_trades_table")
            with Vertical(classes="trade_list_container"):
                yield Static("Best Performer Trades", classes="widget_title")
                yield DataTable(id="best_trades_table")

    def on_mount(self) -> None:
        for table_id in ["#baseline_trades_table", "#best_trades_table"]:
            table = self.query_one(table_id, DataTable)
            table.add_column("Time", width=20)
            table.add_column("Type", width=6)
            table.add_column("Price", width=12, key="price")
            table.add_column("Qty", width=15, key="qty")
            table.add_column("PnL ($)", width=12, key="pnl")
            table.add_row("[dim]Waiting for data...[/dim]", "", "", "", "")

    def update_data(self, baseline_data: dict, best_data: dict):
        baseline_trades = baseline_data.get("summary", {}).get("trades", [])
        best_trades = best_data.get("summary", {}).get("trades", [])

        self._update_table("#baseline_trades_table", baseline_trades)
        self._update_table("#best_trades_table", best_trades)

    def _update_table(self, table_id: str, trades: list):
        table = self.query_one(table_id, DataTable)
        table.clear()

        if not trades:
            table.add_row("[dim]No trades executed.[/dim]", "", "", "", "")
            return

        for trade in trades:
            ts = datetime.fromisoformat(trade.get("timestamp")).strftime("%Y-%m-%d %H:%M:%S")
            order_type = trade.get("order_type", "").upper()

            style = "green" if order_type == "BUY" else "red" if order_type == "SELL" else ""
            type_str = f"[{style}]{order_type}[/{style}]" if style else order_type

            price = Decimal(trade.get("price", 0))
            qty = Decimal(trade.get("quantity", 0))

            pnl_str = ""
            if order_type == "SELL":
                pnl = Decimal(trade.get("realized_pnl_usd", 0))
                pnl_style = "bold green" if pnl > 0 else "bold red" if pnl < 0 else "dim"
                pnl_str = f"[{pnl_style}]{pnl:+.2f}[/{pnl_style}]"

            table.add_row(
                ts,
                type_str,
                f"{price:,.4f}",
                f"{qty:.6f}",
                pnl_str
            )


class TopTrialsWidget(Container):
    """A widget to display a leaderboard of the top performing trials."""

    def compose(self) -> ComposeResult:
        yield Static("🏆 Top 5 Performing Trials 🏆", classes="widget_title")
        yield DataTable(id="top_trials_table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Rank", width=6)
        table.add_column("Score", width=12, key="score")
        table.add_column("Regime", width=8)
        table.add_column("Trial #", width=8)
        table.add_column("Key Params", width=100)
        table.add_row("[dim]Waiting for trials...[/dim]", "", "", "", "")

    def update_data(self, top_trials: list):
        table = self.query_one(DataTable)
        table.clear()

        if not top_trials:
            table.add_row("[dim]Waiting for trials...[/dim]", "", "", "", "")
            return

        for i, trial in enumerate(top_trials):
            rank = i + 1
            score = trial.get("score", 0)
            regime = trial.get("regime", "N/A")
            trial_num = trial.get("number", "N/A")

            params = trial.get("params", {})
            # Display a few key parameters to keep the table clean
            key_params = {
                k.replace("STRATEGY_RULES_", "").replace(f"REGIME_{regime}_", ""): v
                for k, v in params.items()
                if "PERCENTAGE" in k or "PROFIT" in k or "SCALING" in k
            }
            params_str = " | ".join([f"{k}: {v:.4f}" for k, v in key_params.items()])

            table.add_row(
                f"#{rank}",
                f"{score:.4f}",
                str(regime),
                str(trial_num),
                f"[dim]{params_str}[/dim]"
            )


class OptimizerDashboard(App):
    CSS = """
    Screen { background: $surface; }
    #main_container { padding: 0 1; width: 100%; height: 100%; layout: horizontal; grid-size: 2; grid-gutter: 1; }
    .main_container { border: round white; padding: 0 1; }
    .widget_title { width: 100%; text-align: center; padding-top: 1; text-style: bold; }
    .table_container { layout: vertical; height: 100%; padding-top: 1; }
    .summary_table { height: 12; margin-bottom: 1; }
    .params_table { height: 100%; }
    #status_bar { dock: top; height: 3; content-align: center middle; background: $panel; border: round white; }
    #progress_container { dock: top; height: 5; content-align: center middle; padding: 1; display: none; }
    #trial_log_container { height: 24; border: heavy white; padding: 1; margin: 1 0; }
    .log_header { width: 100%; text-align: center; text-style: bold; }
    .log_box { height: 100%; border: none; }
    .trades_main_container { layout: horizontal; grid-size: 2; grid-gutter: 1; height: 24; margin-top: 1; }
    .trade_list_container { border: round white; padding: 0 1; }
    TopTrialsWidget { height: 10; border: round white; margin-top: 1; padding: 0 1; }
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_timer: Timer = None
        self.processed_trial_files = set()
        self.baseline_data = {}
        self.best_trial_data = {}
        self.optimizer_process_found = False
        self.start_time = None

    def compose(self) -> ComposeResult:
        yield Header(name="⚡ Genius Optimizer Dashboard ⚡")
        yield Static("⚪ Waiting for optimization to begin...", id="status_bar")
        with Container(id="progress_container"):
            yield Static("", id="progress_label")
            yield ProgressBar(id="overall_progress", show_eta=False)
        with ScrollableContainer():
            with Container(id="main_container"):
                yield ComparisonWidget(title="📊 Baseline (.env)", id="baseline_widget")
                yield ComparisonWidget(title="🏆 Best Performer", id="best_performer_widget")
            yield TradesComparisonWidget(id="trades_comparison_widget")
            yield TopTrialsWidget()
            yield Vertical(
                Static("Live Trial Log", classes="log_header"),
                Log(id="live_trial_log", auto_scroll=True, classes="log_box"),
                id="trial_log_container"
            )
        yield Footer()

    def on_mount(self) -> None:
        TUI_FILES_DIR.mkdir(exist_ok=True)
        self.update_timer = self.set_interval(1.5, self.update_dashboard)

    def _is_optimizer_running(self) -> bool:
        try:
            for p in psutil.process_iter(['name', 'cmdline']):
                if p.info['cmdline'] and 'run_genius_optimizer.py' in ' '.join(p.info['cmdline']):
                    self.optimizer_process_found = True
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        return False

    def update_dashboard(self) -> None:
        # --- Status Bar Update ---
        status_bar = self.query_one("#status_bar", Static)
        is_running = self._is_optimizer_running()
        if is_running:
            status_bar.update("⚡ OPTIMIZING... ⚡")
            if self.start_time is None: self.start_time = time.time()
        elif self.optimizer_process_found and not is_running:
            status_bar.update("✅ OPTIMIZATION COMPLETED ✅")
        else:
            status_bar.update("⚪ Waiting for optimization to begin...")

        # --- Progress Bar Update ---
        progress_file = TUI_FILES_DIR / "progress_status.json"
        progress_container = self.query_one("#progress_container")
        if progress_file.exists():
            progress_container.styles.display = "block"
            try:
                with open(progress_file, "r") as f:
                    progress_data = json.load(f)

                completed = progress_data.get("completed_trials", 0)
                total = progress_data.get("total_trials", 1)

                progress_bar = self.query_one(ProgressBar)
                progress_bar.update(progress=completed, total=total)

                # Calculate ETA
                eta_str = "Calculating..."
                if self.start_time and completed > 0:
                    elapsed_time = time.time() - self.start_time
                    time_per_trial = elapsed_time / completed
                    remaining_trials = total - completed
                    eta_seconds = remaining_trials * time_per_trial

                    if eta_seconds > 3600:
                        eta_str = f"{eta_seconds / 3600:.1f} hours"
                    elif eta_seconds > 60:
                        eta_str = f"{eta_seconds / 60:.1f} minutes"
                    else:
                        eta_str = f"{eta_seconds:.0f} seconds"

                progress_label = self.query_one("#progress_label", Static)
                progress_label.update(f"Overall Progress (ETA: {eta_str})")

            except (json.JSONDecodeError, IOError):
                pass # Fail silently if file is being written or is corrupt

        # --- Baseline Widget Update ---
        if not self.baseline_data:
            baseline_file = TUI_FILES_DIR / "baseline_summary.json"
            if baseline_file.exists():
                try:
                    with open(baseline_file, "r") as f:
                        self.baseline_data = json.load(f)
                    baseline_widget = self.query_one("#baseline_widget", ComparisonWidget)
                    baseline_widget.update_data(self.baseline_data)
                except (json.JSONDecodeError, IOError, KeyError) as e:
                    self.log(f"Error processing baseline file: {e}")

        best_trial_file = TUI_FILES_DIR / "best_overall_trial.json"
        if best_trial_file.exists():
            try:
                with open(best_trial_file, "r") as f:
                    new_data = json.load(f)
                if new_data.get("trial_number") != self.best_trial_data.get("trial_number"):
                    self.best_trial_data = new_data
                    best_performer_widget = self.query_one("#best_performer_widget", ComparisonWidget)
                    best_performer_widget.update_data(self.best_trial_data, self.baseline_data)

                    # Update the trades comparison widget as well
                    if self.baseline_data:
                        trades_widget = self.query_one(TradesComparisonWidget)
                        trades_widget.update_data(self.baseline_data, self.best_trial_data)

            except (json.JSONDecodeError, IOError, KeyError) as e:
                self.log(f"Error processing best trial file: {e}")

        trial_files = glob.glob(str(TUI_FILES_DIR / "genius_trial_*.json"))

        # --- Top Trials Leaderboard Update ---
        # This part always re-reads all files to update the leaderboard.
        all_trials = []
        for file_path in trial_files:
            try:
                with open(file_path, "r") as f:
                    all_trials.append(json.load(f))
            except (IOError, json.JSONDecodeError):
                continue # Skip corrupted or currently being written files

        if all_trials:
            # Sort by score descending and take the top 5
            sorted_trials = sorted(all_trials, key=lambda t: t.get("score", -9999), reverse=True)
            top_5_trials = sorted_trials[:5]

            # Update the widget
            top_trials_widget = self.query_one(TopTrialsWidget)
            top_trials_widget.update_data(top_5_trials)

        # --- Live Log Update ---
        # This part only processes new files to append to the log.
        new_trial_files = sorted([f for f in trial_files if f not in self.processed_trial_files])

        trial_log = self.query_one("#live_trial_log", Log)
        for file_path in new_trial_files:
            self.processed_trial_files.add(file_path)
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                summary = data.get("summary", {})
                score = data.get('score', 0) or 0.0
                balance = summary.get('final_balance', 0)
                pnl_pct = summary.get('net_pnl_pct', 0)
                regime = data.get("regime", -1)
                trial_num = data.get('number', -1)
                params_str = ", ".join([f"{k.split('_')[-1]}={v:.3f}" if isinstance(v, float) else f"{k.split('_')[-1]}={v}" for k, v in data.get("params", {}).items()])

                log_line = (
                    f"[{datetime.now():%H:%M:%S}] [b]Regime {regime} | Trial {trial_num}[/b]\n"
                    f"  - [b]Score[/b]: {score:10.4f} | [b]Balance[/b]: ${float(balance):,.2f} | [b]PnL%[/b]: {float(pnl_pct):.2%}\n"
                    f"  - [b]Params[/b]: [dim]({params_str})[/dim]\n"
                )
                trial_log.write(log_line)

            except (json.JSONDecodeError, IOError, KeyError) as e:
                trial_log.write(f"[{datetime.now():%H:%M:%S}] Error processing file {Path(file_path).name}: {e}")
                continue

if __name__ == "__main__":
    app = OptimizerDashboard()
    app.run()
