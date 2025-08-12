from datetime import datetime
import json
import sys
import os
import time
from decimal import Decimal, InvalidOperation

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal
from textual.widgets import Header, Footer, DataTable, Input, Button, Label, Static, RichLog
from textual.timer import Timer
from textual.validation import Validator, ValidationResult

# Add project root to path for imports if running as a script
if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

class NumberValidator(Validator):
    """A validator to ensure the input is a positive number."""
    def validate(self, value: str) -> ValidationResult:
        try:
            if float(value) > 0:
                return self.success()
            else:
                return self.failure("Must be a positive number.")
        except ValueError:
            return self.failure("Invalid number format.")

class DisplayManager(App):
    """A Textual app to display and control the trading bot's status."""

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    CSS_PATH = "jules_bot.css" # Assumes CSS is in the same directory
    STATE_FILE = "/tmp/bot_state.json"
    COMMAND_DIR = "commands"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_timer: Timer | None = None
        self.selected_trade_id: str | None = None
        self.current_btc_price: Decimal = Decimal(0)
        os.makedirs(self.COMMAND_DIR, exist_ok=True)

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Horizontal(id="main_container"):
            with VerticalScroll(id="left_pane"):
                yield Static("Bot Control", classes="title")
                yield Label("Manual Buy (USD):")
                yield Input(placeholder="e.g., 100.00", id="manual_buy_input", validators=[NumberValidator()])
                yield Button("FORCE BUY", id="force_buy_button", variant="primary")
                yield Static("Live Log", classes="title", id="log_title")
                yield RichLog(id="log_display", wrap=True, markup=True)

            with VerticalScroll(id="right_pane"):
                yield Static("Bot Status", classes="title")
                with Horizontal(id="status_bar"):
                    yield Static("Mode: N/A", id="status_mode")
                    yield Static("Symbol: N/A", id="status_symbol")
                    yield Static("Price: N/A", id="status_price")

                yield Static("Portfolio", classes="title")
                with Horizontal(id="portfolio_bar"):
                    yield Static("Total Investment: $0.00", id="total_investment")
                    yield Static("Current Value: $0.00", id="current_value")
                    yield Static("Unrealized PnL: $0.00", id="unrealized_pnl")

                yield Static("Strategy", classes="title")
                with VerticalScroll(id="strategy_bar"):
                    yield Static("Total Realized Profit: $0.00", id="total_realized_pnl")
                    yield Static("BTC Saved (HODL): 0.00000000", id="total_btc_saved")
                    yield Static("Next Buy Target: N/A", id="price_to_buy")
                    yield Static("Next Sell Target: N/A", id="price_to_sell")

                yield Static("Open Positions", classes="title")
                yield DataTable(id="positions_table")

                yield Static("Binance Wallet", classes="title")
                yield DataTable(id="wallet_table")

                with Horizontal(id="action_bar", classes="hidden"):
                    yield Button("Force Sell Selected", id="force_sell_button", variant="error")
                    yield Button("Mark as Treasury", id="to_treasury_button", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is first mounted."""
        positions_table = self.query_one("#positions_table", DataTable)
        positions_table.cursor_type = "row"
        positions_table.add_columns("ID", "Entry Price", "Quantity", "Value", "Status")

        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.add_columns("Asset", "Free", "Locked", "USD Value")

        self.update_timer = self.set_interval(1.0, self.update_dashboard)
        self.query_one("#manual_buy_input").focus()
        self.log_display = self.query_one(RichLog)
        self.log_display.write("[bold green]UI mounted. Waiting for bot state...[/]")

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        self.selected_trade_id = event.row_key.value
        self.query_one("#action_bar").remove_class("hidden")

    def write_command_file(self, command: dict):
        """Writes a command to a uniquely named JSON file."""
        filename = f"cmd_{int(time.time() * 1000)}.json"
        filepath = os.path.join(self.COMMAND_DIR, filename)
        try:
            with open(filepath, "w") as f:
                json.dump(command, f)
            self.log_display.write(f"[blue]UI: Sent command -> {command}[/]")
        except IOError as e:
            self.log_display.write(f"[bold red]UI ERROR: Could not write command file: {e}[/]")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "force_buy_button":
            input_widget = self.query_one("#manual_buy_input", Input)
            validation_result = input_widget.validate(input_widget.value)

            if not validation_result.is_valid:
                self.log_display.write(f"[bold red]UI ERROR: {validation_result.failure_description}[/]")
                return

            try:
                amount_usd = float(input_widget.value)
                command = {"type": "force_buy", "amount_usd": amount_usd}
                self.write_command_file(command)
                input_widget.value = ""
            except ValueError:
                self.log_display.write("[bold red]UI ERROR: Invalid amount for buy command.[/]")

        elif self.selected_trade_id:
            if event.button.id == "force_sell_button":
                command = {"type": "force_sell", "trade_id": self.selected_trade_id}
                self.write_command_file(command)
            elif event.button.id == "to_treasury_button":
                command = {"type": "to_treasury", "trade_id": self.selected_trade_id}
                self.write_command_file(command)

            self.query_one("#action_bar").add_class("hidden")
            self.query_one(DataTable).cursor_row = -1
            self.selected_trade_id = None

    def update_dashboard(self) -> None:
        """Reads the state file and updates all UI widgets."""
        try:
            with open(self.STATE_FILE, "r") as f:
                state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        header = self.query_one(Header)
        header.sub_title = f"Last Update: {datetime.fromtimestamp(state.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S')}"
        
        self.query_one("#status_mode").update(f"Mode: {state.get('mode', 'N/A').upper()}")
        self.query_one("#status_symbol").update(f"Symbol: {state.get('symbol', 'N/A')}")

        try:
            self.current_btc_price = Decimal(state.get('current_price', '0'))
            self.query_one("#status_price").update(f"Price: ${self.current_btc_price:,.2f}")
        except (InvalidOperation, TypeError):
            self.current_btc_price = Decimal(0)

        table = self.query_one(DataTable)
        current_selection = self.selected_trade_id
        table.clear()

        total_investment = Decimal(0)
        current_value = Decimal(0)

        positions = state.get("open_positions", [])
        if not positions:
            table.add_row("No open positions.")
        else:
            for pos in positions:
                try:
                    entry_price = Decimal(pos.get('price', '0'))
                    quantity = Decimal(pos.get('quantity', '0'))
                    pos_value = quantity * self.current_btc_price

                    total_investment += Decimal(pos.get('usd_value', '0'))
                    current_value += pos_value

                    short_id = pos.get('trade_id', 'N/A').split('-')[0]

                    table.add_row(
                        short_id,
                        f"${entry_price:,.2f}",
                        f"{quantity:.8f}",
                        f"${pos_value:,.2f}",
                        pos.get('status', 'OPEN'),
                        key=pos.get('trade_id')
                    )
                except (InvalidOperation, TypeError):
                    table.add_row(pos.get('trade_id', 'ERR'), "Data Error", "", "", "", key=pos.get('trade_id'))

        unrealized_pnl = current_value - total_investment
        pnl_color = "green" if unrealized_pnl >= 0 else "red"

        self.query_one("#total_investment").update(f"Total Investment: ${total_investment:,.2f}")
        self.query_one("#current_value").update(f"Current Value: ${current_value:,.2f}")
        self.query_one("#unrealized_pnl").update(f"Unrealized PnL: [bold {pnl_color}]${unrealized_pnl:,.2f}[/]")

        # Update Strategy section
        total_pnl = Decimal(state.get("total_realized_pnl", 0))
        pnl_color = "green" if total_pnl >= 0 else "red"
        self.query_one("#total_realized_pnl").update(f"Total Realized Profit: [bold {pnl_color}]${total_pnl:,.2f}[/]")

        total_btc_saved = Decimal(state.get("total_btc_saved", 0))
        self.query_one("#total_btc_saved").update(f"BTC Saved (HODL): {total_btc_saved:.8f}")

        next_buy_price = Decimal(state.get("next_buy_price", 0))
        if next_buy_price > 0 and self.current_btc_price > 0:
            diff = self.current_btc_price - next_buy_price
            diff_percent = (diff / self.current_btc_price) * 100
            color = "red" if diff > 0 else "green"
            self.query_one("#price_to_buy").update(f"Next Buy Target: ${next_buy_price:,.2f} ([{color}]{diff:,.2f} / {diff_percent:,.2f}%[/])")
        else:
            self.query_one("#price_to_buy").update("Next Buy Target: N/A")

        next_sell_price = Decimal(state.get("next_sell_price", 0))
        if next_sell_price > 0 and self.current_btc_price > 0:
            diff = next_sell_price - self.current_btc_price
            diff_percent = (diff / self.current_btc_price) * 100
            color = "green" if diff > 0 else "red"
            self.query_one("#price_to_sell").update(f"Next Sell Target: ${next_sell_price:,.2f} ([{color}]{diff:,.2f} / {diff_percent:,.2f}%[/])")
        else:
            self.query_one("#price_to_sell").update("Next Sell Target: N/A")

        # Restore selection if it still exists
        if current_selection in table.rows:
            self.selected_trade_id = current_selection
            table.cursor_row = table.get_row_index(current_selection)
            self.query_one("#action_bar").remove_class("hidden")
        else:
            self.selected_trade_id = None
            self.query_one("#action_bar").add_class("hidden")

        self.update_wallet_table(state.get("wallet_balances", []))

    def update_wallet_table(self, balances: list) -> None:
        """Updates the wallet table with the latest balances."""
        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.clear()
        if not balances:
            wallet_table.add_row("No wallet data.")
        else:
            for balance in balances:
                try:
                    asset = balance.get('asset')
                    free = Decimal(balance.get('free', '0'))
                    locked = Decimal(balance.get('locked', '0'))
                    usd_value = Decimal(balance.get('usd_value', '0'))
                    wallet_table.add_row(asset, f"{free:.8f}", f"{locked:.8f}", f"${usd_value:,.2f}")
                except (InvalidOperation, TypeError):
                    wallet_table.add_row(balance.get('asset', 'ERR'), "Data Error", "", "")


if __name__ == '__main__':
    app = DisplayManager()
    app.run()
