import os
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal
from textual.widgets import (Header, Footer, DataTable, Input, Button, Label, Static, RichLog)
from textual.validation import Validator, ValidationResult

from jules_bot.bot.command_manager import CommandManager

if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

class NumberValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            if float(value) > 0:
                return self.success()
            return self.failure("Must be a positive number.")
        except ValueError:
            return self.failure("Invalid number format.")

class DisplayManager(App):
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    CSS_PATH = "jules_bot.css"

    def __init__(self, mode: str, command_manager: CommandManager, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.command_manager = command_manager
        self.selected_trade_id: str | None = None
        self.log_display = None

    def compose(self) -> ComposeResult:
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
                    yield Static(f"Mode: {self.mode.upper()}", id="status_mode")
                    yield Static("Symbol: N/A", id="status_symbol")
                    yield Static("Price: N/A", id="status_price")
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
        yield Footer()

    def on_mount(self) -> None:
        self.log_display = self.query_one(RichLog)
        self.log_display.write("[bold green]UI mounted.[/bold green] Waiting for first data update...")

        for table_id, columns in [
            ("#positions_table", ["ID", "Entry", "Qty", "Value", "PnL", "Sell Target", "Progress"]),
            ("#history_table", ["ID", "Status", "Entry", "Exit", "Qty", "PnL"]),
            ("#wallet_table", ["Asset", "Free", "Locked", "USD Value"])
        ]:
            table = self.query_one(table_id, DataTable)
            table.add_columns(*columns)

        self.query_one("#positions_table", DataTable).cursor_type = "row"

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        log_display = self.query_one(RichLog)

        if event.button.id == "force_buy_button":
            input_widget = self.query_one("#manual_buy_input", Input)
            amount_str = input_widget.value
            if not amount_str:
                log_display.write("[bold red]Please enter a USD amount to buy.[/bold red]")
                return

            try:
                amount_usd = Decimal(amount_str)
                if amount_usd <= 0:
                    raise ValueError("Amount must be positive.")

                log_display.write(f"[yellow]Executing force buy for ${amount_usd}...[/yellow]")
                # This is now a synchronous call to the command manager
                success, message = self.command_manager.force_buy(amount_usd)
                if success:
                    log_display.write(f"[bold green]{message}[/bold green]")
                    input_widget.value = "" # Clear input on success
                else:
                    log_display.write(f"[bold red]{message}[/bold red]")

            except (ValueError, InvalidOperation):
                log_display.write(f"[bold red]Invalid amount: '{amount_str}'. Please enter a valid number.[/bold red]")

        elif event.button.id == "force_sell_button":
            if self.selected_trade_id:
                log_display.write(f"[yellow]Executing force sell for trade {self.selected_trade_id[:8]}...[/yellow]")
                success, message = self.command_manager.force_sell(self.selected_trade_id)
                if success:
                    log_display.write(f"[bold green]{message}[/bold green]")
                    self.query_one("#action_bar").add_class("hidden")
                    self.selected_trade_id = None
                else:
                    log_display.write(f"[bold red]{message}[/bold red]")
            else:
                log_display.write("[bold red]No trade selected to sell.[/bold red]")

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """Handle row selection in the positions table."""
        # A None value for row_key means the table was cleared or lost focus
        if event.row_key.value is None:
            self.selected_trade_id = None
            self.query_one("#action_bar").add_class("hidden")
        else:
            self.selected_trade_id = event.row_key.value
            self.query_one("#action_bar").remove_class("hidden")
            self.query_one(RichLog).write(f"Selected trade: {self.selected_trade_id[:8]}")

    def update_data(self, state: dict):
        """Processes a state dictionary and updates all UI widgets."""
        if "error" in state:
            self.log_display.write(f"[bold red]Received error from bot: {state['error']}[/]")
            return

        header = self.query_one(Header)
        header.sub_title = f"Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        current_price = Decimal(state.get('current_btc_price', '0'))
        self.query_one("#status_price").update(f"Price: ${current_price:,.2f}")
        self.query_one("#status_symbol").update(f"Symbol: {state.get('symbol', 'N/A')}")

        self.update_positions_table(state.get("open_positions_status", []), current_price)
        self.update_buy_signal_status(state.get("buy_signal_status", {}))
        self.update_history_table(state.get("trade_history", []))
        self.update_wallet_table(state.get("wallet_balances", []))

    def update_positions_table(self, positions: list, current_price: Decimal):
        table = self.query_one("#positions_table", DataTable)
        table.clear()
        if not positions:
            table.add_row("No open positions.")
            return
        for pos in positions:
            try:
                entry_price = Decimal(pos.get('entry_price', '0'))
                quantity = Decimal(pos.get('quantity', '0'))
                pnl = Decimal(pos.get('unrealized_pnl', '0'))
                sell_target = Decimal(pos.get('sell_target_price', '0'))
                progress = Decimal(pos.get('progress_to_sell_target_pct', '0'))

                table.add_row(
                    pos.get('trade_id', 'N/A').split('-')[0],
                    f"${entry_price:,.2f}", f"{quantity:.8f}", f"${quantity * current_price:,.2f}",
                    f"[{'green' if pnl >= 0 else 'red'}]${pnl:,.2f}[/]",
                    f"${sell_target:,.2f}", f"{progress:.1f}%",
                    key=pos.get('trade_id')
                )
            except (InvalidOperation, TypeError) as e:
                self.log_display.write(f"[bold red]Data Error parsing position {pos.get('trade_id')}: {e}[/]")

    def update_buy_signal_status(self, buy_status: dict):
        reason = buy_status.get('reason', 'N/A')
        buy_target = Decimal(buy_status.get('btc_purchase_target', '0'))
        buy_progress = Decimal(buy_status.get('btc_purchase_progress_pct', '0'))

        self.query_one("#buy_signal_status").update(f"Buy Signal: [{'green' if buy_status.get('should_buy') else 'yellow'}]{reason}[/]")
        self.query_one("#buy_target_price").update(f"Buy Target: ${buy_target:,.2f}" if buy_target > 0 else "N/A")
        self.query_one("#buy_target_progress").update(f"Buy Progress: {buy_progress:.1f}%" if buy_target > 0 else "N/A")

    def update_history_table(self, history: list):
        table = self.query_one("#history_table", DataTable)
        table.clear()
        if not history:
            table.add_row("No trade history.")
            return
        for trade in history:
            pnl = trade.get('realized_pnl_usd')
            pnl_str = f"[{'green' if Decimal(pnl) >= 0 else 'red'}]${Decimal(pnl):,.2f}[/]" if pnl is not None else "N/A"
            table.add_row(
                trade.get('trade_id', 'N/A').split('-')[0], trade.get('status', 'N/A'),
                f"${Decimal(trade.get('price')):,.2f}", f"${Decimal(trade.get('sell_price', '0')):,.2f}",
                f"{Decimal(trade.get('quantity', '0')):.8f}", pnl_str, key=trade.get('trade_id')
            )

    def update_wallet_table(self, balances: list):
        table = self.query_one("#wallet_table", DataTable)
        table.clear()
        if not balances:
            table.add_row("No wallet data.")
            return
        for bal in balances:
            usd_val = Decimal(bal.get('usd_value', '0'))
            table.add_row(
                bal.get('asset'), f"{Decimal(bal.get('free', '0')):.8f}",
                f"{Decimal(bal.get('locked', '0')):.8f}",
                f"${usd_val:,.2f}" if usd_val > 0 else ""
            )

