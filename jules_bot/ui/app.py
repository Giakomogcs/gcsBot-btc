import datetime
import json
import sys
import os
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Input, Button, Label
from textual.containers import Horizontal
from textual.timer import Timer
import time

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

class JulesBotApp(App):
    """A Textual app to display the trading bot's status."""

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    STATE_FILE = "/tmp/bot_state.json"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_timer: Timer = None
        self.selected_trade_id: str | None = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Horizontal(
            Label("Manual Buy (USD):"),
            Input(placeholder="e.g., 100.00", id="manual_buy_input"),
            Button("FORCE BUY", id="force_buy_button", variant="primary"),
        )
        yield DataTable(id="positions_table")
        yield Horizontal(
            Button("Force Sell Selected", id="force_sell_button", variant="error", classes="hidden"),
            Button("Convert to Treasury", id="to_treasury_button", variant="success", classes="hidden"),
            id="action_bar"
        )
        yield Footer()

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        # Assumes the trade_id is stored as the row key
        self.selected_trade_id = event.row_key.value
        self.query_one("#action_bar").remove_class("hidden")

    def write_command_file(self, command: dict):
        """Writes a command to a uniquely named JSON file."""
        filename = f"cmd_{int(time.time() * 1000)}.json"
        filepath = os.path.join("commands", filename)
        with open(filepath, "w") as f:
            json.dump(command, f)
        self.log(f"UI: Sent command {command}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "force_buy_button":
            amount_str = self.query_one("#manual_buy_input").value
            try:
                amount_usd = float(amount_str)
                command = {"type": "force_buy", "amount_usd": amount_usd}
                self.write_command_file(command)
                self.query_one("#manual_buy_input").value = ""
            except ValueError:
                self.log("UI ERROR: Invalid amount.")

        if self.selected_trade_id:
            if event.button.id == "force_sell_button":
                command = {"type": "force_sell", "trade_id": self.selected_trade_id}
                self.write_command_file(command)
            elif event.button.id == "to_treasury_button":
                command = {"type": "to_treasury", "trade_id": self.selected_trade_id}
                self.write_command_file(command)

            # Hide buttons and clear selection after sending command
            self.query_one("#action_bar").add_class("hidden")
            self.selected_trade_id = None

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
                        pos.get('status', 'N/A'),
                        key=pos.get('trade_id')
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
