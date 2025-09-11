import json
from pathlib import Path
from rich.pretty import Pretty
from datetime import datetime
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static
from textual.widgets._data_table import CellDoesNotExist
from textual.containers import Container, VerticalScroll
from textual.timer import Timer

TUI_FILES_DIR = Path(".tui_files")

class OptimizerDashboard(App):
    """A Textual app to monitor Optuna optimization runs."""

    CSS_PATH = "app.css"
    BINDINGS = [
        ("d", "toggle_dark", "Toggle dark mode"),
        ("q", "quit", "Quit")
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trial_data = {}
        self.update_timer: Timer = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Container(
            Static("Waiting for optimization to start...", id="best_trial_header"),
            VerticalScroll(Static(id="best_trial_content")),
            DataTable(id="trials_table"),
            id="main_container"
        )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Ensure the directory exists
        TUI_FILES_DIR.mkdir(exist_ok=True)

        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_column("Trial", key="trial")
        table.add_column("Status", key="status")
        table.add_column("Value ($)", key="value")
        table.add_column("Duration (s)", key="duration")

        # Start a timer to poll for file updates
        self.update_timer = self.set_interval(1, self.update_dashboard)
        self.update_dashboard() # Initial update

    def update_dashboard(self) -> None:
        """Polls the directory for JSON files and updates the dashboard."""
        # Update best trial
        best_trial_file = TUI_FILES_DIR / "best_trial_summary.json"
        if best_trial_file.exists():
            try:
                with open(best_trial_file, "r") as f:
                    best_trial_data = json.load(f)

                header = self.query_one("#best_trial_header", Static)
                header.update(f"🏆 Best Trial: #{best_trial_data.get('number')} | Final Balance: ${best_trial_data.get('value', 0):,.2f}")

                content = self.query_one("#best_trial_content", Static)
                content.update(Pretty(best_trial_data.get("params", {})))
            except (json.JSONDecodeError, IOError):
                pass # Ignore errors from partially written files

        # Update trials table
        table = self.query_one(DataTable)

        json_files = list(TUI_FILES_DIR.glob("trial_*.json"))

        for file_path in json_files:
            try:
                with open(file_path, "r") as f:
                    data = json.load(f)

                trial_num = data.get("number")
                if trial_num is None:
                    continue

                # Check if we have seen this trial before and if the data has changed
                if self.trial_data.get(trial_num) == data:
                    continue # Skip if data is the same

                self.trial_data[trial_num] = data

                row_key = f"trial-{trial_num}"
                status = data.get("state", "UNKNOWN")
                value = data.get("value")
                value_str = f"{value:,.2f}" if value is not None else "N/A"

                start_time = data.get("datetime_start")
                end_time = data.get("datetime_complete")
                duration_str = "N/A"
                if start_time and end_time:
                    duration = datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)
                    duration_str = f"{duration.total_seconds():.2f}"

                # Use a unique key for each row to update it in place
                try:
                    # update_cell will raise a CellDoesNotExist if the row doesn't exist.
                    table.update_cell(row_key, "status", status, update_width=True)
                    table.update_cell(row_key, "value", value_str, update_width=True)
                    table.update_cell(row_key, "duration", duration_str, update_width=True)
                except CellDoesNotExist:
                    # If the row does not exist, add it.
                    # The values must be in the same order as the columns were added.
                    table.add_row(
                        str(trial_num),
                        status,
                        value_str,
                        duration_str,
                        key=row_key
                    )
            except (json.JSONDecodeError, IOError):
                # Could be that the file is being written, just skip for now
                continue

if __name__ == "__main__":
    app = OptimizerDashboard()
    app.run()
