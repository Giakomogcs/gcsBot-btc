import json
import glob
from pathlib import Path
from rich.text import Text
from datetime import datetime
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static, Log
from textual.containers import Container, Vertical
from textual.timer import Timer
import time

TUI_FILES_DIR = Path(".tui_files")
REGIME_NAMES = {
    0: "RANGING",
    1: "UPTREND",
    2: "HIGH_VOLATILITY",
    3: "DOWNTREND"
}

class OptimizerDashboard(App):
    """A Textual app to monitor the multi-regime Genius Optimizer."""

    CSS_PATH = "app.css"
    BINDINGS = [
        ("d", "toggle_dark", "Toggle Dark Mode"),
        ("q", "quit", "Quit")
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_timer: Timer = None
        self.processed_files = set()
        self.regime_summaries = {}

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(name="🧠 Genius Optimizer Dashboard")
        yield Container(
            Static("Starting...", id="overall_status", classes="box"),
            DataTable(id="regime_summary_table", classes="box"),
            Vertical(
                Static("Live Trial Log", classes="log_header"),
                Log(id="live_trial_log", auto_scroll=True, classes="log_box"),
                id="trial_log_container"
            ),
            id="main_container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        TUI_FILES_DIR.mkdir(exist_ok=True)

        summary_table = self.query_one("#regime_summary_table", DataTable)
        summary_table.cursor_type = "row"
        summary_table.add_column("Regime", key="regime", width=20)
        summary_table.add_column("Status", key="status", width=15)
        summary_table.add_column("Best Score", key="score", width=15)
        summary_table.add_column("Trials", key="trials", width=10)
        summary_table.add_column("Best Balance", key="balance", width=20)
        summary_table.add_column("Best Drawdown", key="drawdown", width=15)

        # Initialize rows for all regimes
        for i in range(4):
            regime_name = REGIME_NAMES.get(i, f"Unknown ({i})")
            summary_table.add_row(regime_name, "PENDING", "N/A", "0", "N/A", "N/A", key=f"regime-{i}")

        self.update_timer = self.set_interval(0.5, self.update_dashboard)

    def update_dashboard(self) -> None:
        """Polls the directory for JSON files and updates the dashboard."""
        json_files = glob.glob(str(TUI_FILES_DIR / "genius_trial_*.json"))

        new_files = sorted([f for f in json_files if f not in self.processed_files])

        if not new_files and not self.processed_files:
             # Check for old files if we are just starting
             if list(TUI_FILES_DIR.glob("*.json")):
                 status_widget = self.query_one("#overall_status", Static)
                 status_widget.update(Text("⚠️ Found old data files. Please clear the '.tui_files' directory before starting a new run.", style="bold yellow"))

        trial_log = self.query_one("#live_trial_log", Log)
        for file_path in new_files:
            self.processed_files.add(file_path)
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                regime = data.get("regime", -1)
                
                # Atualiza o status geral para refletir a execução paralela
                status_widget = self.query_one("#overall_status", Static)
                if "OPTIMIZING IN PARALLEL" not in str(status_widget.renderable):
                    status_widget.update("⚡ OPTIMIZING IN PARALLEL ACROSS ALL REGIMES ⚡")

                score = data.get('score', 0) or 0.0
                state = data.get('state', 'UNKNOWN')
                trial_num = data.get('number', -1)

                log_line = f"Regime {regime} | Trial {trial_num:<4} | Score: {score:10.4f} | Status: {state}"
                trial_log.write_line(log_line)

            except (json.JSONDecodeError, IOError, KeyError):
                continue # Ignore partially written files or malformed data

        # Update summary table from summary files
        summary_files = glob.glob(str(TUI_FILES_DIR / "genius_summary_regime_*.json"))
        summary_table = self.query_one("#regime_summary_table", DataTable)

        for file_path in summary_files:
            try:
                with open(file_path, "r") as f:
                    summary_data = json.load(f)

                regime = summary_data.get("regime")
                if regime is None: continue

                # Update the table if new data is available
                if self.regime_summaries.get(regime) != summary_data:
                    self.regime_summaries[regime] = summary_data

                    score = summary_data.get('score', 0) or 0.0
                    balance = summary_data.get('final_balance', 0.0)
                    drawdown = summary_data.get('max_drawdown', 0.0) * 100

                    # Get number of trials completed for this regime
                    trial_count = len(glob.glob(str(TUI_FILES_DIR / f"genius_trial_{regime}_*.json")))

                    summary_table.update_cell(f"regime-{regime}", "status", "RUNNING", update_width=False)
                    summary_table.update_cell(f"regime-{regime}", "score", f"{score:.4f}", update_width=False)
                    summary_table.update_cell(f"regime-{regime}", "trials", str(trial_count), update_width=False)
                    summary_table.update_cell(f"regime-{regime}", "balance", f"${balance:,.2f}", update_width=False)
                    summary_table.update_cell(f"regime-{regime}", "drawdown", f"{drawdown:.2f}%", update_width=False)

            except (json.JSONDecodeError, IOError, KeyError):
                continue

if __name__ == "__main__":
    # This part is important for the `run.py` script to be able to launch it
    # We add a small delay to ensure the directory can be cleaned up first if needed.
    time.sleep(1)
    app = OptimizerDashboard()
    app.run()
