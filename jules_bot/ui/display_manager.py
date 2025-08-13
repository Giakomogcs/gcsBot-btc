from datetime import datetime
import json
import sys
import os
import time
from decimal import Decimal, InvalidOperation
import httpx

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
    CSS_PATH = "jules_bot.css"
    COMMAND_DIR = "commands"
    API_URL = "http://localhost:8765/status/extended"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_timer: Timer | None = None
        self.selected_trade_id: str | None = None
        self.client = httpx.AsyncClient()
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
                    yield Static("Buy Signal: N/A", id="buy_signal_status")
                    yield Static("Buy Target: N/A", id="buy_target_price")
                    yield Static("Buy Progress: N/A", id="buy_target_progress")

                yield Static("Open Positions", classes="title")
                yield DataTable(id="positions_table")

                yield Static("Trade History", classes="title")
                yield DataTable(id="history_table")

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
        positions_table.add_columns("ID", "Entry Price", "Qty", "Value", "Unrealized PnL", "Sell Target", "Sell Progress")

        history_table = self.query_one("#history_table", DataTable)
        history_table.add_columns("ID", "Status", "Entry Price", "Exit Price", "Quantity", "PnL")

        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.add_columns("Asset", "Free", "Locked", "USD Value")

        self.update_timer = self.set_interval(2.0, self.update_dashboard) # Slower update for API calls
        self.query_one("#manual_buy_input").focus()
        self.log_display = self.query_one(RichLog)
        self.log_display.write("[bold green]UI mounted. Fetching data from API...[/]")

    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
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
                if validation_result.failures:
                    self.log_display.write(f"[bold red]UI ERROR: {validation_result.failures[0].description}[/]")
                else:
                    self.log_display.write(f"[bold red]UI ERROR: Validation failed with no description.[/]")
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

    async def update_dashboard(self) -> None:
        """Fetches data from the API and updates all UI widgets."""
        try:
            response = await self.client.get(self.API_URL, timeout=5.0)
            response.raise_for_status()
            state = response.json()
        except httpx.RequestError as e:
            self.log_display.write(f"[bold red]API Error: Could not connect to {self.API_URL}. Is the API running?[/]")
            return
        except Exception as e:
            self.log_display.write(f"[bold red]An unexpected error occurred: {e}[/]")
            return

        header = self.query_one(Header)
        header.sub_title = f"Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Update status bar
        current_price = Decimal(state.get('current_btc_price', '0'))
        self.query_one("#status_price").update(f"Price: ${current_price:,.2f}")
        self.query_one("#status_mode").update(f"Mode: {state.get('mode', 'N/A').upper()}")
        self.query_one("#status_symbol").update(f"Symbol: {state.get('symbol', 'N/A')}")

        # Update open positions table
        table = self.query_one("#positions_table", DataTable)
        table.clear()

        positions = state.get("open_positions_status", [])
        if not positions:
            table.add_row("No open positions.")
        else:
            for pos in positions:
                try:
                    entry_price = Decimal(pos.get('entry_price', '0'))
                    quantity = Decimal(pos.get('quantity', '0'))
                    pos_value = quantity * current_price
                    unrealized_pnl = Decimal(pos.get('unrealized_pnl', '0'))
                    pnl_color = "green" if unrealized_pnl >= 0 else "red"
                    sell_target = Decimal(pos.get('sell_target_price', '0'))
                    sell_progress = Decimal(pos.get('progress_to_sell_target_pct', '0'))
                    short_id = pos.get('trade_id', 'N/A').split('-')[0]

                    table.add_row(
                        short_id,
                        f"${entry_price:,.2f}",
                        f"{quantity:.8f}",
                        f"${pos_value:,.2f}",
                        f"[{pnl_color}]${unrealized_pnl:,.2f}[/]",
                        f"${sell_target:,.2f}",
                        f"{sell_progress:.1f}%",
                        key=pos.get('trade_id')
                    )
                except (InvalidOperation, TypeError) as e:
                    self.log_display.write(f"[bold red]Data Error parsing position: {pos}. Error: {e}[/]")
                    table.add_row(pos.get('trade_id', 'ERR'), "Data Error", "", "", "", "", "", key=pos.get('trade_id'))

        # Update buy signal status
        buy_status = state.get("buy_signal_status", {})
        should_buy = buy_status.get('should_buy', False)
        reason = buy_status.get('reason', 'N/A')
        buy_target = Decimal(buy_status.get('btc_purchase_target', '0'))
        buy_progress = Decimal(buy_status.get('btc_purchase_progress_pct', '0'))

        signal_color = "green" if should_buy else "yellow"
        self.query_one("#buy_signal_status").update(f"Buy Signal: [{signal_color}]{reason}[/]")

        if buy_target > 0:
            self.query_one("#buy_target_price").update(f"Buy Target: ${buy_target:,.2f}")
            self.query_one("#buy_target_progress").update(f"Buy Progress: {buy_progress:.1f}%")
        else:
            self.query_one("#buy_target_price").update("Buy Target: N/A")
            self.query_one("#buy_target_progress").update("Buy Progress: N/A")

        # Update history and wallet tables with data from API
        self.update_history_table(state.get("trade_history", []))
        self.update_wallet_table(state.get("wallet_balances", []))


    def update_history_table(self, history: list) -> None:
        """Updates the history table with the latest trade history."""
        history_table = self.query_one("#history_table", DataTable)
        history_table.clear()
        if not history:
            history_table.add_row("No trade history.")
            return

        processed_trades = {}
        history.sort(key=lambda x: x.get('timestamp', ''), reverse=False)

        for trade in history:
            trade_id = trade.get('trade_id')
            if not trade_id:
                continue

            if trade_id not in processed_trades:
                processed_trades[trade_id] = {'trade_id': trade_id}

            if trade.get('order_type') == 'buy':
                processed_trades[trade_id]['entry_price'] = trade.get('price')
                processed_trades[trade_id]['quantity'] = trade.get('quantity')
                processed_trades[trade_id]['status'] = trade.get('status', 'OPEN')
            elif trade.get('order_type') == 'sell':
                processed_trades[trade_id]['exit_price'] = trade.get('price')
                processed_trades[trade_id]['pnl'] = trade.get('realized_pnl_usd')
                processed_trades[trade_id]['status'] = trade.get('status', 'CLOSED')

        sorted_trades = sorted(processed_trades.values(), key=lambda x: x.get('entry_price', 0), reverse=True)

        for data in sorted_trades:
            short_id = data.get('trade_id', 'N/A').split('-')[0]
            status = data.get('status', 'N/A')
            entry_price = data.get('entry_price')
            exit_price = data.get('exit_price')
            quantity = data.get('quantity')
            pnl = data.get('pnl')

            entry_price_str = f"${Decimal(entry_price):,.2f}" if entry_price is not None else "N/A"
            exit_price_str = f"${Decimal(exit_price):,.2f}" if exit_price is not None else "N/A"
            quantity_str = f"{Decimal(quantity):.8f}" if quantity is not None else "N/A"
            pnl_str = f"${Decimal(pnl):,.2f}" if pnl is not None else "N/A"

            if pnl is not None:
                pnl_color = "green" if Decimal(pnl) >= 0 else "red"
                pnl_str = f"[{pnl_color}]{pnl_str}[/]"

            history_table.add_row(
                short_id, status, entry_price_str, exit_price_str, quantity_str, pnl_str, key=data.get('trade_id')
            )

    def update_wallet_table(self, balances: list) -> None:
        """Updates the wallet table with the latest balances."""
        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.clear()

        if not balances:
            wallet_table.add_row("No wallet data.")
            return

        for balance in balances:
            try:
                asset = balance.get('asset')
                free = Decimal(balance.get('free', '0'))
                locked = Decimal(balance.get('locked', '0'))
                usd_value = Decimal(balance.get('usd_value', '0'))
                value_str = f"${usd_value:,.2f}" if asset != 'USDT' else ''
                wallet_table.add_row(asset, f"{free:.8f}", f"{locked:.8f}", value_str)
            except (InvalidOperation, TypeError):
                wallet_table.add_row(balance.get('asset', 'ERR'), "Data Error", "", "")


if __name__ == '__main__':
    app = DisplayManager()
    app.run()
