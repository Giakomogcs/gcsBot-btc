import json
import glob
import time
from pathlib import Path
from rich.text import Text
from rich.panel import Panel
from datetime import datetime
import psutil

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Log, DataTable
from textual.containers import Container, Vertical, ScrollableContainer
from textual.timer import Timer

# Directory where the optimizer drops its progress files
TUI_FILES_DIR = Path(".tui_files")

class ComparisonWidget(Container):
    """A widget to display a side-by-side comparison of a backtest result."""

    def __init__(self, title: str, **kwargs):
        super().__init__(**kwargs)
        self.title_text = title

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
        metrics_table.add_row("[dim]Waiting for data...[/dim]", "")

        params_table = self.query_one("#params_table", DataTable)
        params_table.add_column("Parameter", width=30)
        params_table.add_column("Value", width=25)
        params_table.add_row("[dim]Waiting for data...[/dim]", "")

    def update_data(self, data: dict):
        """Updates the widget's tables with new data."""
        if not data:
            return

        summary = data.get("summary", data) # Handle both baseline and best trial structures
        params = data.get("params")

        # === Update Metrics Table ===
        metrics_table = self.query_one("#metrics_table", DataTable)
        metrics_table.clear()
        metrics_table.add_column("Metric", width=25)
        metrics_table.add_column("Value", width=20)

        key_metrics = {
            "final_balance": "Final Balance",
            "net_pnl_pct": "Net PnL %",
            "win_rate": "Win Rate",
            "profit_factor": "Profit Factor",
            "max_drawdown": "Max Drawdown %",
            "sharpe_ratio": "Sharpe Ratio",
            "sortino_ratio": "Sortino Ratio",
            "total_trades": "Total Trades",
            "sell_trades_count": "Sell Trades" # Added for clarity
        }

        for key, name in key_metrics.items():
            value = summary.get(key)
            if value is None:
                value_str = "[dim]N/A[/dim]"
            else:
                try:
                    float_value = float(value)
                    if "pct" in key or "drawdown" in key:
                        value_str = f"{float_value:.2%}"
                    elif "balance" in key:
                        value_str = f"${float_value:,.2f}"
                    elif "ratio" in key or "factor" in key:
                        value_str = f"{float_value:.2f}"
                    else:
                        value_str = str(int(float_value)) # For total_trades
                except (ValueError, TypeError):
                    value_str = str(value)
            metrics_table.add_row(name, value_str)

        # Add score and trial number if available
        if "score" in data:
            metrics_table.add_row("Score", f"{data['score']:.4f}")
        if "trial_number" in data:
            metrics_table.add_row("Trial #", str(data['trial_number']))


        # === Update Parameters Table ===
        params_table = self.query_one("#params_table", DataTable)
        params_table.clear()
        params_table.add_column("Parameter", width=30)
        params_table.add_column("Value", width=25)

        if not params:
            params_table.add_row("[dim]Not applicable.[/dim]", "")
        else:
            # Highlight changed parameters if original params are provided
            original_params = getattr(self, 'original_params', None)

            for key, value in sorted(params.items()):
                value_str = f"{value:.6f}" if isinstance(value, float) else str(value)

                # Compare as strings to handle different types gracefully
                if original_params and str(original_params.get(key)) != str(value):
                    key = f"[bold yellow]{key}[/bold yellow]"
                    value_str = f"[bold yellow]{value_str}[/bold yellow]"

                params_table.add_row(key, value_str)


class OptimizerDashboard(App):
    """A Textual app to monitor the Genius Optimizer."""

    CSS = """
    Screen {
        background: $surface;
    }
    #main_container {
        padding: 0 1;
        width: 100%;
        height: 100%;
        layout: horizontal;
        grid-size: 2;
        grid-gutter: 1;
    }
    .main_container {
        border: round white;
        padding: 0 1;
    }
    .widget_title {
        width: 100%;
        text-align: center;
        padding-top: 1;
        text-style: bold;
    }
    .table_container {
        layout: vertical;
        height: 100%;
        padding-top: 1;
    }
    .summary_table {
        height: 12;
        margin-bottom: 1;
    }
    .params_table {
        height: 100%;
    }
    #status_bar {
        dock: top;
        height: 3;
        content-align: center middle;
        background: $panel;
        border: round white;
    }
    #trial_log_container {
        height: 18;
        border: heavy white;
        padding: 1;
        margin: 1 0;
    }
    .log_header {
        width: 100%;
        text-align: center;
        text-style: bold;
    }
    .log_box {
        height: 100%;
        border: none;
    }
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_timer: Timer = None
        self.processed_trial_files = set()
        self.baseline_data = {}
        self.best_trial_data = {}
        self.optimizer_process_found = False # Track if we've ever seen the process

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(name="⚡ Genius Optimizer Dashboard ⚡")
        yield Static("⚪ Waiting for optimization to begin...", id="status_bar")

        with ScrollableContainer():
            with Container(id="main_container"):
                yield ComparisonWidget(title="📊 Baseline (.env)", id="baseline_widget")
                yield ComparisonWidget(title="🏆 Best Performer", id="best_performer_widget")

            yield Vertical(
                Static("Live Trial Log", classes="log_header"),
                Log(id="live_trial_log", auto_scroll=True, classes="log_box"),
                id="trial_log_container"
            )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        TUI_FILES_DIR.mkdir(exist_ok=True)
        self.update_timer = self.set_interval(1.5, self.update_dashboard)

    def _is_optimizer_running(self) -> bool:
        """Check if the optimizer script is currently running using psutil."""
        for p in psutil.process_iter(['name', 'cmdline']):
            if p.info['cmdline'] and 'run_genius_optimizer.py' in ' '.join(p.info['cmdline']):
                self.optimizer_process_found = True
                return True
        return False

    def update_dashboard(self) -> None:
        """Polls the directory for JSON files and updates the dashboard."""
        status_bar = self.query_one("#status_bar", Static)

        # --- Update Overall Status ---
        is_running = self._is_optimizer_running()
        if is_running:
             status_bar.update("⚡ OPTIMIZING... ⚡")
        elif self.optimizer_process_found and not is_running:
            # If we've seen the process before but now it's gone, it's completed.
            status_bar.update("✅ OPTIMIZATION COMPLETED ✅")
        else:
            # Haven't seen the process yet.
            status_bar.update("⚪ Waiting for optimization to begin...")

        # --- Load Baseline Summary (once) ---
        if not self.baseline_data:
            baseline_file = TUI_FILES_DIR / "baseline_summary.json"
            if baseline_file.exists():
                try:
                    with open(baseline_file, "r") as f:
                        self.baseline_data = json.load(f)
                    baseline_widget = self.query_one("#baseline_widget", ComparisonWidget)
                    baseline_widget.update_data(self.baseline_data)

                    # Store original params in the best performer widget for comparison
                    best_performer_widget = self.query_one("#best_performer_widget", ComparisonWidget)
                    best_performer_widget.original_params = self.baseline_data.get("params")

                except (json.JSONDecodeError, IOError, KeyError) as e:
                    self.log(f"Error processing baseline file: {e}")

        # --- Load Best Overall Trial (continuously) ---
        best_trial_file = TUI_FILES_DIR / "best_overall_trial.json"
        if best_trial_file.exists():
            try:
                with open(best_trial_file, "r") as f:
                    new_data = json.load(f)

                # Update only if the data is new
                if new_data.get("trial_number") != self.best_trial_data.get("trial_number"):
                    self.best_trial_data = new_data
                    best_performer_widget = self.query_one("#best_performer_widget", ComparisonWidget)
                    best_performer_widget.update_data(self.best_trial_data)
                    # Status bar is now handled by the running check above
                    # status_bar.update(f"🏆 New best trial found! Score: {self.best_trial_data.get('score', 0):.4f}")

            except (json.JSONDecodeError, IOError, KeyError) as e:
                self.log(f"Error processing best trial file: {e}")

        # --- Update Live Trial Log ---
        trial_files = glob.glob(str(TUI_FILES_DIR / "genius_trial_*.json"))
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
                regime = data.get("regime", -1)
                trial_num = data.get('number', -1)

                log_line = (
                    f"[{datetime.now():%H:%M:%S}] "
                    f"[Regime {regime}] "
                    f"Trial {trial_num:<4} | "
                    f"Score: {score:10.4f} | "
                    f"Balance: ${float(balance):9,.2f}"
                )
                trial_log.write(log_line)

            except (json.JSONDecodeError, IOError, KeyError) as e:
                trial_log.write(f"[{datetime.now():%H:%M:%S}] Error processing file {Path(file_path).name}: {e}")
                continue


if __name__ == "__main__":
    app = OptimizerDashboard()
    app.run()
