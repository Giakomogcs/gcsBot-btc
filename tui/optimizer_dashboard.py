import json
import glob
import time
from pathlib import Path
from rich.text import Text
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from datetime import datetime

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Log, DataTable
from textual.containers import Container, Horizontal, Vertical
from textual.timer import Timer

# Directory where the optimizer drops its progress files
TUI_FILES_DIR = Path(".tui_files")

# Mapping from regime index to a human-readable name
REGIME_NAMES = {
    0: "RANGING",
    1: "UPTREND",
    2: "HIGH_VOLATILITY",
    3: "DOWNTREND"
}
# A simple color cycle for the regime panels
REGIME_COLORS = ["cyan", "green", "magenta", "red"]


class RegimeSummaryWidget(Container):
    """A widget to display the summary for a single optimization regime."""

    def __init__(self, regime_id: int, **kwargs):
        super().__init__(**kwargs)
        self.regime_id = regime_id
        self.regime_name = REGIME_NAMES.get(regime_id, f"UNKNOWN_{regime_id}")
        # Set a default border title, which will be updated
        self.border_title = f" [bold]{self.regime_name}[/] [dim](PENDING)[/] "

    def compose(self) -> ComposeResult:
        """Compose the widget's layout."""
        yield Static(self.border_title, classes="regime_title")
        yield Vertical(
            Static(f"Best Parameters for {self.regime_name}", classes="param_header"),
            DataTable(id=f"params_table_{self.regime_id}", classes="params_table"),
            id=f"regime_params_container_{self.regime_id}"
        )

    def on_mount(self) -> None:
        """Called when the widget is mounted."""
        table = self.query_one(DataTable)
        table.add_column("Parameter", width=35)
        table.add_column("Value", width=20)
        table.add_row("[dim]Waiting for data...[/dim]", "")
        # Add a class for default border color and specific regime styling
        self.add_class("regime_widget_panel", f"regime-color-{self.regime_id}")

    def update_panel(self, summary_data: dict, status: str, trials_completed: int, total_trials: int):
        """Updates the widget's display with new summary data."""
        score = summary_data.get('score', 0) or 0.0
        best_params = summary_data.get('params', {})
        progress = f"{trials_completed}/{total_trials or '?'}"

        # Update title and subtitle in the Static header
        title = f"[bold]{self.regime_name}[/]"
        status_text = f"[dim]({status})[/]"
        details = f"Best Score: [bold]{score:.4f}[/] | Trials: {progress}"
        self.query_one(".regime_title").update(f"{title} {status_text} - {details}")

        # Update border style by managing classes
        self.remove_class("status-running", "status-completed", "status-pending")
        if status == "RUNNING":
            self.add_class("status-running")
        elif status == "COMPLETED":
            self.add_class("status-completed")
        else:
            self.add_class("status-pending")

        # Update Parameters Table
        params_table = self.query_one(DataTable)
        params_table.clear()
        params_table.add_column("Parameter", width=35)
        params_table.add_column("Value", width=20)

        if not best_params:
            params_table.add_row("[dim]Waiting for first trial...[/dim]", "")
        else:
            for key, value in sorted(best_params.items()):
                if isinstance(value, float):
                    value_str = f"{value:.6f}"
                else:
                    value_str = str(value)
                params_table.add_row(key, value_str)

class BaselineSummaryWidget(Container):
    """A widget to display the summary of the baseline backtest."""

    def compose(self) -> ComposeResult:
        yield Static("[b]📊 Baseline Performance (from .env)[/b]", classes="baseline_title")
        yield DataTable(id="baseline_table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Metric", width=25)
        table.add_column("Value", width=20)
        table.add_row("[dim]Waiting for data...[/dim]", "")

    def update_panel(self, summary_data: dict):
        table = self.query_one(DataTable)
        table.clear()
        table.add_column("Metric", width=25)
        table.add_column("Value", width=20)

        if not summary_data:
            table.add_row("[dim]Baseline run failed or not found.[/dim]", "")
            return

        # Key metrics to display from the backtest summary
        key_metrics = {
            "final_balance": "Final Balance",
            "net_pnl_pct": "Net PnL %",
            "win_rate": "Win Rate %",
            "profit_factor": "Profit Factor",
            "max_drawdown": "Max Drawdown %",
            "sharpe_ratio": "Sharpe Ratio",
            "sortino_ratio": "Sortino Ratio",
            "sell_trades_count": "Total Trades",
        }
        
        for key, name in key_metrics.items():
            value = summary_data.get(key)
            if value is None:
                value_str = "[dim]N/A[/dim]"
            else:
                try:
                    # Attempt to convert to float for formatting
                    float_value = float(value)
                    if "pct" in key or "win_rate" in key:
                        value_str = f"{float_value:.2f}%"
                    elif "balance" in key:
                        value_str = f"${float_value:,.2f}"
                    elif "drawdown" in key:
                        value_str = f"{float_value * 100:.2f}%"
                    elif "ratio" in key or "factor" in key:
                        value_str = f"{float_value:.2f}"
                    else:
                        value_str = str(value)
                except (ValueError, TypeError):
                    value_str = str(value)
            
            table.add_row(name, value_str)


class EvolvingStrategyWidget(Container):
    """A widget to display the aggregated best parameters found so far."""

    def compose(self) -> ComposeResult:
        yield Static("[b]🧬 Evolving Best Strategy[/b]", classes="evolving_title")
        yield DataTable(id="evolving_table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Parameter", width=35)
        # Add columns for each regime
        for i in range(4):
            regime_name = REGIME_NAMES.get(i, f"R{i}")
            table.add_column(regime_name, width=18)
        
        table.add_row("[dim]Waiting for first trial...[/dim]", "", "", "", "")

    def update_panel(self, best_params_by_regime: dict):
        table = self.query_one(DataTable)
        table.clear()
        table.add_column("Parameter", width=35)
        for i in range(4):
            regime_name = REGIME_NAMES.get(i, f"R{i}")
            table.add_column(regime_name, width=18)

        if not best_params_by_regime:
            table.add_row("[dim]Waiting for first trial...[/dim]", "", "", "", "")
            return

        # Aggregate all unique parameter keys from all regimes
        all_keys = set()
        for regime_id, data in best_params_by_regime.items():
            all_keys.update(data.get("params", {}).keys())
        
        sorted_keys = sorted(list(all_keys))

        for key in sorted_keys:
            row = [key]
            for i in range(4):
                regime_data = best_params_by_regime.get(i)
                if regime_data and "params" in regime_data:
                    value = regime_data["params"].get(key)
                    if value is None:
                        value_str = "[dim]-[/dim]"
                    elif isinstance(value, float):
                        value_str = f"{value:.4f}"
                    else:
                        value_str = str(value)
                    row.append(value_str)
                else:
                    row.append("[dim]Pending...[/dim]")
            table.add_row(*row)


class OptimizerDashboard(App):
    """A Textual app to monitor the multi-regime Genius Optimizer."""

    CSS = """
    #baseline_container, #evolving_container {
        border: round white;
        margin: 1 0;
    }
    #baseline_container { height: 12; }
    #evolving_container { height: 14; }

    .baseline_title, .evolving_title {
        width: 100%;
        text-align: center;
        padding-top: 1;
    }
    #main_container {
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1;
        padding: 1;
    }
    .regime_widget_panel {
        height: 100%;
        padding: 0 1;
        border: heavy gray; /* Default border for pending/completed */
    }
    .regime_title {
        width: 100%;
        text-align: center;
        padding: 1 0;
        text-style: bold;
    }
    .regime_widget_panel.status-running.regime-color-0 { border: heavy cyan; }
    .regime_widget_panel.status-running.regime-color-1 { border: heavy green; }
    .regime_widget_panel.status-running.regime-color-2 { border: heavy magenta; }
    .regime_widget_panel.status-running.regime-color-3 { border: heavy red; }
    .param_header {
        width: 100%;
        text-align: center;
        text-style: bold underline;
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
        column-span: 2;
        height: 15;
        border: heavy white;
        padding: 1;
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
        self.regime_summaries = {}
        self.total_trials_per_regime = 0

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(name="⚡ Genius Optimizer Dashboard ⚡")
        yield Static("⚪ Waiting for optimization to begin...", id="status_bar")

        # Baseline and Evolving Strategy widgets
        yield BaselineSummaryWidget(id="baseline_container")
        yield EvolvingStrategyWidget(id="evolving_container")

        # Main grid for regime summaries
        yield Container(
            *[
                RegimeSummaryWidget(regime_id=i, id=f"regime_panel_{i}")
                for i in range(4)
            ],
            id="main_container",
        )

        # Log for individual trial updates
        yield Vertical(
            Static("Live Trial Log", classes="log_header"),
            Log(id="live_trial_log", auto_scroll=True, classes="log_box"),
            id="trial_log_container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Create the directory if it doesn't exist to prevent errors
        TUI_FILES_DIR.mkdir(exist_ok=True)

        # Start polling for updates
        self.update_timer = self.set_interval(1.5, self.update_dashboard)
        self.update_baseline() # Initial check for baseline file

    def _get_total_trials(self) -> int:
        """
        A bit of a hack to find the total number of trials by inspecting
        the optimizer process arguments if available.
        """
        try:
            import psutil
            for p in psutil.process_iter(['name', 'cmdline']):
                if p.info['cmdline'] and 'run_genius_optimizer.py' in ' '.join(p.info['cmdline']):
                    cmd = p.info['cmdline']
                    # Expected command: ['python', 'scripts/run_genius_optimizer.py', bot, days, n_trials, json_params]
                    if len(cmd) >= 5 and cmd[-2].isdigit():
                        return int(cmd[-2])
        except (ImportError, psutil.Error):
            pass # psutil not available or permission error
        return 0 # Fallback

    def update_dashboard(self) -> None:
        """Polls the directory for JSON files and updates the dashboard."""
        status_bar = self.query_one("#status_bar", Static)

        if not self.total_trials_per_regime:
            self.total_trials_per_regime = self._get_total_trials()

        # --- Update Summaries for Each Regime ---
        summary_files = glob.glob(str(TUI_FILES_DIR / "genius_summary_regime_*.json"))
        if summary_files:
            status_bar.update("⚡ OPTIMIZING IN PARALLEL ACROSS ALL REGIMES ⚡")

        for file_path in summary_files:
            try:
                with open(file_path, "r") as f:
                    summary_data = json.load(f)

                regime_id = summary_data.get("regime")
                if regime_id is None:
                    continue

                # Update widget if data is new
                if self.regime_summaries.get(regime_id) != summary_data:
                    self.regime_summaries[regime_id] = summary_data

                    # --- Get widget ---
                    try:
                        summary_widget = self.query_one(f"#regime_panel_{regime_id}", RegimeSummaryWidget)
                    except Exception:
                        continue # Widget might not be mounted yet

                    # --- Calculate new status ---
                    trial_files = glob.glob(str(TUI_FILES_DIR / f"genius_trial_{regime_id}_*.json"))
                    trials_completed = len(trial_files)
                    status = "COMPLETED" if self.total_trials_per_regime and trials_completed >= self.total_trials_per_regime else "RUNNING"

                    # --- Update the summary widget's content and appearance ---
                    summary_widget.update_panel(
                        summary_data=summary_data,
                        status=status,
                        trials_completed=trials_completed,
                        total_trials=self.total_trials_per_regime,
                    )

            except (json.JSONDecodeError, IOError, KeyError):
                continue

        # --- Update Evolving Strategy Widget ---
        if self.regime_summaries:
            try:
                evolving_widget = self.query_one(EvolvingStrategyWidget)
                evolving_widget.update_panel(self.regime_summaries)
            except Exception as e:
                self.log(f"Error updating evolving strategy widget: {e}")

        # --- Update Live Trial Log ---
        trial_files = glob.glob(str(TUI_FILES_DIR / "genius_trial_*.json"))
        new_trial_files = sorted([f for f in trial_files if f not in self.processed_trial_files])

        trial_log = self.query_one("#live_trial_log", Log)
        for file_path in new_trial_files:
            self.processed_trial_files.add(file_path)
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                regime = data.get("regime", -1)
                regime_name = REGIME_NAMES.get(regime, "N/A")
                score = data.get('score', 0) or 0.0
                state = data.get('state', 'UNKNOWN')
                trial_num = data.get('number', -1)
                balance = data.get('final_balance', 0)
                params_str = ", ".join([f"{k.split('_')[-1]}={v:.3f}" if isinstance(v, float) else f"{k.split('_')[-1]}={v}" for k, v in data.get("params", {}).items()])

                log_line = (
                    f"[{datetime.now():%H:%M:%S}] "
                    f"[[{REGIME_COLORS[regime]}]]{regime_name:<15}[/]] "
                    f"Trial {trial_num:<4} | "
                    f"Score: {score:10.4f} | "
                    f"Balance: ${balance:9,.2f} | "
                    f"Params: [dim]({params_str})[/dim]"
                )
                trial_log.write(log_line)

            except (json.JSONDecodeError, IOError, KeyError) as e:
                trial_log.write(f"[{datetime.now():%H:%M:%S}] Error processing file {Path(file_path).name}: {e}")
                continue
    
    def update_baseline(self) -> None:
        """Checks for the baseline summary file and updates the widget."""
        baseline_file = TUI_FILES_DIR / "baseline_summary.json"
        try:
            if baseline_file.exists():
                with open(baseline_file, "r") as f:
                    summary_data = json.load(f)
                
                baseline_widget = self.query_one(BaselineSummaryWidget)
                baseline_widget.update_panel(summary_data)
                # No need to poll for this file, so we don't set a timer for it.
        except (json.JSONDecodeError, IOError, KeyError) as e:
            self.log(f"Error processing baseline file: {e}")


if __name__ == "__main__":
    time.sleep(1)
    app = OptimizerDashboard()
    app.run()
