import json
import sys
import os
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable
from textual.timer import Timer

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

class JulesBotApp(App):
    """A Textual app to display the trading bot's status."""

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    STATE_FILE = "/tmp/bot_state.json"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_timer: Timer = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield DataTable(id="positions_table")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is first mounted."""
        table = self.query_one(DataTable)
        table.add_columns("Trade ID", "Entry Price", "Quantity", "Status")
        self.update_timer = self.set_interval(1.0, self.update_dashboard, pause=False)

    def update_dashboard(self) -> None:
        """Reads the state file and updates all UI widgets."""
        try:
            with open(self.STATE_FILE, "r") as f:
                state = json.load(f)

            header = self.query_one(Header)
            header.title = f"Jules Bot - {state.get('mode', 'N/A').upper()} Mode"
            header.sub_title = f"Last Update: {datetime.fromtimestamp(state.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S')}"

            table = self.query_one(DataTable)
            table.clear()

            positions = state.get("open_positions", [])
            if not positions:
                table.add_row("No open positions.")
            else:
                for pos in positions:
                    table.add_row(
                        pos.get('trade_id', 'N/A'),
                        f"${pos.get('entry_price', 0):,.2f}",
                        f"{pos.get('quantity_btc', 0):.8f}",
                        pos.get('status', 'N/A')
                    )

        except FileNotFoundError:
            self.query_one(Header).sub_title = f"Waiting for state file: {self.STATE_FILE}"
        except json.JSONDecodeError:
            # Handle case where file is being written at the same time we read it
            pass

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

if __name__ == '__main__':
    app = JulesBotApp()
    app.run()
