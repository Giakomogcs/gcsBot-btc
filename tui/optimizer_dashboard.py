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


class RegimeSummaryWidget(Static):
    """A widget to display the summary for a single optimization regime."""

    def __init__(self, regime_id: int, **kwargs):
        super().__init__(**kwargs)
        self.regime_id = regime_id
        self.regime_name = REGIME_NAMES.get(regime_id, f"UNKNOWN_{regime_id}")

        # Internal state
        self.trials_total = 0
        self.best_params = {}

    def compose(self) -> ComposeResult:
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

    def update_summary(self, summary_data: dict, total_trials: int):
        """Updates the widget's display with new summary data."""
        self.best_params = summary_data.get('params', {})
        self.trials_total = total_trials

        # --- Update Parameters Table ---
        params_table = self.query_one(f"#params_table_{self.regime_id}", DataTable)
        params_table.clear()
        params_table.add_column("Parameter", width=35)
        params_table.add_column("Value", width=20)

        if not self.best_params:
            params_table.add_row("[dim]Waiting for first trial...[/dim]", "")
        else:
            for key, value in sorted(self.best_params.items()):
                if isinstance(value, float):
                    value_str = f"{value:.6f}"
                else:
                    value_str = str(value)
                params_table.add_row(key, value_str)

class OptimizerDashboard(App):
    """A Textual app to monitor the multi-regime Genius Optimizer."""

    CSS = """
    #main_container {
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1;
        padding: 1;
    }
    .regime_widget {
        height: 100%;
    }
    Panel {
        height: 100%;
        border: heavy;
    }
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
        self.regime_widgets = {}

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(name="⚡ Genius Optimizer Dashboard ⚡")
        yield Static("⚪ Waiting for optimization to begin...", id="status_bar")

        # Main grid for regime summaries
        yield Container(
            *[Static(
                Panel(
                    RegimeSummaryWidget(regime_id=i),
                    title=f" [bold]{REGIME_NAMES.get(i)}[/] [dim](PENDING)[/] ",
                    border_style="grey50"
                ),
                id=f"regime_panel_{i}"
            ) for i in range(4)],
            id="main_container"
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

        # Store references to the summary widgets
        self.regime_widgets = {
            widget.regime_id: widget for widget in self.query(RegimeSummaryWidget)
        }

        # Start polling for updates
        self.update_timer = self.set_interval(1.5, self.update_dashboard)

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
                if regime_id is None: continue

                # Update widget if data is new
                if self.regime_summaries.get(regime_id) != summary_data:
                    self.regime_summaries[regime_id] = summary_data

                    # --- Get widgets ---
                    panel_static = self.query_one(f"#regime_panel_{regime_id}", Static)
                    summary_widget = self.regime_widgets[regime_id]

                    # --- Calculate new style and status ---
                    regime_name = REGIME_NAMES.get(regime_id)
                    trial_files = glob.glob(str(TUI_FILES_DIR / f"genius_trial_{regime_id}_*.json"))
                    trials_completed = len(trial_files)
                    status = "COMPLETED" if self.total_trials_per_regime and trials_completed >= self.total_trials_per_regime else "RUNNING"
                    score = summary_data.get('score', 0) or 0.0
                    progress = f"{trials_completed}/{self.total_trials_per_regime or '?'}"
                    title = f" [bold]{regime_name}[/] [dim]({status})[/] "
                    subtitle = f" Best Score: [bold]{score:.4f}[/] | Trials: {progress} "
                    border_style = REGIME_COLORS[regime_id % len(REGIME_COLORS)] if status == "RUNNING" else "grey50"

                    # --- IMPORTANT: Remove widget from its parent before re-attaching ---
                    summary_widget.remove()

                    # --- Create a new Panel with updated style and update the Static widget ---
                    new_panel = Panel(
                        summary_widget,
                        title=title,
                        subtitle=subtitle,
                        border_style=border_style
                    )
                    panel_static.update(new_panel)

                    # --- Update the summary widget's content ---
                    summary_widget.update_summary(summary_data, self.total_trials_per_regime)

            except (json.JSONDecodeError, IOError, KeyError):
                continue

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

                log_line = Text.from_markup(
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

if __name__ == "__main__":
    time.sleep(1)
    app = OptimizerDashboard()
    app.run()
