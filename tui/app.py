import json
import subprocess
import sys
import os
from decimal import Decimal, InvalidOperation
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal
from textual.widgets import Header, Footer, DataTable, Input, Button, Label, Static, RichLog, ProgressBar
from textual.timer import Timer
from textual.validation import Validator, ValidationResult

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class NumberValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            if float(value) > 0:
                return self.success()
            else:
                return self.failure("Must be a positive number.")
        except ValueError:
            return self.failure("Invalid number format.")

class TUIApp(App):
    """A Textual app to display and control the trading bot's status via command-line scripts."""

    BINDINGS = [("d", "toggle_dark", "Toggle Dark Mode"), ("q", "quit", "Quit")]
    CSS = """
    #main_container {
        layout: horizontal;
    }
    #left_pane {
        width: 30%;
        padding: 1;
        border-right: solid $accent;
    }
    #right_pane {
        width: 70%;
        padding: 1;
    }
    .title {
        background: $accent;
        color: $text;
        width: 100%;
        padding: 0 1;
        margin-top: 1;
    }
    #positions_table {
        margin-top: 1;
        height: 15;
    }
    #action_bar {
        margin-top: 1;
    }
    .hidden {
        display: none;
    }
    """

    def __init__(self, mode: str = "test", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.update_timer: Timer | None = None
        self.selected_trade_id: str | None = None
        self.log_display: RichLog | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main_container"):
            with VerticalScroll(id="left_pane"):
                yield Static("Bot Control", classes="title")
                yield Label("Manual Buy (USD):")
                yield Input(placeholder="e.g., 50.00", id="manual_buy_input", validators=[NumberValidator()])
                yield Button("FORCE BUY", id="force_buy_button", variant="primary")

                yield Static("Selected Trade Actions", classes="title")
                with Horizontal(id="action_bar", classes="hidden"):
                    yield Button("Sell 100%", id="force_sell_100_button", variant="error")
                    yield Button("Sell 90%", id="force_sell_90_button", variant="warning")

                yield Static("Live Log", classes="title", id="log_title")
                yield RichLog(id="log_display", wrap=True, markup=True)

            with VerticalScroll(id="right_pane"):
                yield Static("Bot Status", classes="title")
                with Horizontal(id="status_bar"):
                    yield Static(f"Mode: {self.mode.upper()}", id="status_mode")
                    yield Static("Symbol: N/A", id="status_symbol")
                    yield Static("Price: N/A", id="status_price")

                yield Static("Open Positions", classes="title")
                yield DataTable(id="positions_table")

                yield Static("Wallet Balances", classes="title")
                yield DataTable(id="wallet_table")

        yield Footer()

    def on_mount(self) -> None:
        self.log_display = self.query_one(RichLog)
        self.log_display.write("[bold green]TUI Initialized.[/bold green]")
        self.log_display.write(f"Mode: [bold]{self.mode}[/bold]")
        self.log_display.write("Starting data refresh timer...")

        positions_table = self.query_one("#positions_table", DataTable)
        positions_table.cursor_type = "row"
        positions_table.add_columns("ID", "Entry", "Value", "PnL", "Sell Target", "Progress")

        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.add_columns("Asset", "Free", "Locked", "USD Value")

        self.update_timer = self.set_interval(5.0, self.update_dashboard)
        self.query_one("#manual_buy_input").focus()

    def run_script(self, command: list[str]) -> tuple[bool, str | dict]:
        self.log_display.write(f"Executing: [yellow]{' '.join(command)}[/]")
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True
            )
            output = process.stdout.strip()
            # Try to parse as JSON, otherwise return raw output
            try:
                return True, json.loads(output)
            except json.JSONDecodeError:
                return True, output
        except subprocess.CalledProcessError as e:
            error_message = e.stderr.strip()
            self.log_display.write(f"[bold red]Script Error:[/bold red] {error_message}")
            return False, error_message
        except FileNotFoundError:
            self.log_display.write(f"[bold red]Error: Script not found at {command[1]}[/]")
            return False, f"Script not found at {command[1]}"

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "force_buy_button":
            input_widget = self.query_one("#manual_buy_input", Input)
            if not input_widget.is_valid:
                self.log_display.write("[bold red]Invalid buy amount.[/bold red]")
                return
            amount = input_widget.value
            self.run_script(["python", "scripts/force_buy.py", amount])
            input_widget.value = ""

        elif event.button.id in ["force_sell_100_button", "force_sell_90_button"]:
            if not self.selected_trade_id:
                self.log_display.write("[bold red]No trade selected for selling.[/bold red]")
                return

            percentage = "100" if event.button.id == "force_sell_100_button" else "90"
            self.run_script(["python", "scripts/force_sell.py", self.selected_trade_id, percentage])

            self.query_one("#action_bar").add_class("hidden")
            self.query_one("#positions_table").cursor_row = -1
            self.selected_trade_id = None

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control.id == "positions_table":
            self.selected_trade_id = event.row_key.value
            self.query_one("#action_bar").remove_class("hidden")

    async def update_dashboard(self) -> None:
        success, data = self.run_script(["python", "scripts/get_bot_data.py", self.mode])
        if not success:
            return

        # Update status bar
        price = Decimal(data.get("current_btc_price", 0))
        self.query_one("#status_symbol").update(f"Symbol: {data.get('symbol', 'N/A')}")
        self.query_one("#status_price").update(f"Price: ${price:,.2f}")

        # Update positions table
        pos_table = self.query_one("#positions_table", DataTable)
        pos_table.clear()
        positions = data.get("open_positions_status", [])
        if positions:
            for pos in positions:
                pos_id = pos.get("trade_id", "N/A")
                entry_price = Decimal(pos.get("entry_price", 0))
                current_value = Decimal(pos.get("quantity", 0)) * price
                pnl = Decimal(pos.get("unrealized_pnl", 0))
                sell_target = Decimal(pos.get("sell_target_price", 0))
                progress = float(pos.get("progress_to_sell_target_pct", 0))
                pnl_color = "green" if pnl >= 0 else "red"

                progress_bar = ProgressBar(total=100, show_eta=False, show_value=True)
                progress_bar.progress = progress

                pos_table.add_row(
                    pos_id.split('-')[0],
                    f"${entry_price:,.2f}",
                    f"${current_value:,.2f}",
                    f"[{pnl_color}]${pnl:,.2f}[/]",
                    f"${sell_target:,.2f}",
                    progress_bar,
                    key=pos_id,
                )
        else:
            pos_table.add_row("No open positions.")

        # Update wallet table
        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.clear()
        balances = data.get("wallet_balances", [])
        if balances:
            for bal in balances:
                asset = bal.get("asset")
                if asset in ["USDT", "BTC"]: # Only show relevant assets
                    free = Decimal(bal.get("free", 0))
                    locked = Decimal(bal.get("locked", 0))
                    usd_val = Decimal(bal.get("usd_value", 0))
                    wallet_table.add_row(asset, f"{free:.8f}", f"{locked:.8f}", f"${usd_val:,.2f}")
        else:
            wallet_table.add_row("No wallet data.")


def run_tui():
    """CLI entry point for the TUI."""
    import argparse
    parser = argparse.ArgumentParser(description="Run the Jules Bot TUI.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["trade", "test"],
        default="test",
        help="The trading mode to monitor ('trade' or 'test')."
    )
    args = parser.parse_args()

    app = TUIApp(mode=args.mode)
    app.run()

if __name__ == "__main__":
    run_tui()
