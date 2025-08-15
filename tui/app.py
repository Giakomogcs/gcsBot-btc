import json
import subprocess
import sys
import os
from decimal import Decimal
import time

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal, Vertical, Container
from textual.widgets import Header, Footer, DataTable, Input, Button, Label, Static, RichLog, ProgressBar
from textual.validation import Validator, ValidationResult
from textual.worker import Worker, get_current_worker
from textual import work
from textual.message import Message

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

class DashboardData(Message):
    """A message to transport dashboard data."""
    def __init__(self, data: dict | str, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

class CommandOutput(Message):
    """A message to transport the output of a command."""
    def __init__(self, output: str, success: bool) -> None:
        self.output = output
        self.success = success
        super().__init__()

class TUIApp(App):
    """A Textual app to display and control the trading bot's status via command-line scripts."""

    BINDINGS = [("d", "toggle_dark", "Toggle Dark Mode"), ("q", "quit", "Quit")]
    CSS = """
    Screen {
        background: $surface-darken-1;
        color: $text;
    }

    #main_container {
        layout: horizontal;
        padding: 1;
    }

    #left_pane {
        width: 40%;
        padding-right: 1;
        border-right: solid $primary;
    }

    #right_pane {
        width: 60%;
        padding-left: 1;
    }

    .title {
        background: $primary;
        color: $text;
        width: 100%;
        padding: 0 1;
        margin-bottom: 1;
        text-style: bold;
    }

    .container {
        border: solid $primary-lighten-2;
        padding: 1;
        margin-bottom: 1;
    }

    #positions_table, #wallet_table {
        margin-top: 1;
        border: solid $primary-lighten-2;
        height: 1fr;
    }

    #log_display {
        border: solid $primary-lighten-2;
        padding: 1;
        height: 1fr;
    }

    #action_bar, #log_filter_bar {
        height: auto;
        align: right middle;
    }

    #force_buy_button {
        width: 100%;
        margin-top: 1;
    }

    .hidden {
        display: none;
    }

    #status_bar {
        align: center middle;
        height: auto;
    }

    #status_bar > Static {
        margin-right: 2;
    }

    #next_buy_container {
        padding: 1;
        border: round $primary;
        margin-top: 1;
    }

    #terminal_note {
        margin-top: 1;
        text-align: center;
        color: $text-muted;
    }

    .progress-complete {
        background: $success;
    }
    """

    def __init__(self, mode: str = "test", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.selected_trade_id: str | None = None
        self.log_display: RichLog | None = None
        self.log_file_path = os.path.join("logs", "jules_bot.jsonl")
        self.log_file_handle = None
        self.log_filter = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main_container"):
            with VerticalScroll(id="left_pane"):
                with Container(classes="container"):
                    yield Static("Bot Control", classes="title")
                    yield Label("Manual Buy (USD):")
                    yield Input(placeholder="e.g., 50.00", id="manual_buy_input", validators=[NumberValidator()])
                    yield Button("🚀 FORCE BUY", id="force_buy_button", variant="success")

                with Container(id="selected_trade_container", classes="container"):
                    yield Static("Selected Trade Actions", classes="title")
                    with Horizontal(id="action_bar", classes="hidden"):
                        yield Button("💸 Sell 90%", id="force_sell_button", variant="warning")

                with Container(classes="container"):
                    yield Static("Live Log", classes="title")
                    with Horizontal(id="log_filter_bar"):
                        yield Label("Filter:", id="log_filter_label")
                        yield Input(placeholder="e.g., ERROR", id="log_filter_input")
                    yield RichLog(id="log_display", wrap=True, markup=True, min_width=0)

            with VerticalScroll(id="right_pane"):
                with Container(classes="container"):
                    yield Static("Bot Status", classes="title")
                    with Horizontal(id="status_bar"):
                        yield Static(f"Mode: {self.mode.upper()}", id="status_mode")
                        yield Static("Symbol: N/A", id="status_symbol")
                        yield Static("Price: N/A", id="status_price")
                    yield DataTable(id="wallet_table")

                with Container(id="next_buy_container"):
                    yield Static("Next Buy Opportunity", classes="title")
                    yield Label("Target Price: N/A", id="next_buy_target")
                    yield ProgressBar(total=100, show_eta=False, show_percentage=True, id="next_buy_progress")

                with Container(classes="container"):
                    yield Static("Open Positions", classes="title")
                    yield DataTable(id="positions_table")

                yield Static("Tip: For best results, use a modern terminal emulator.", id="terminal_note")

        yield Footer()

    def on_mount(self) -> None:
        self.log_display = self.query_one(RichLog)
        self.log_display.write("[bold green]TUI Initialized.[/bold green]")

        positions_table = self.query_one("#positions_table", DataTable)
        positions_table.cursor_type = "row"
        positions_table.add_columns("ID", "Entry", "Value", "$ to Trg", "PnL", "Sell Target", "Progress")

        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.add_columns("Asset", "USD Value")

        self.update_dashboard()
        self.set_interval(30.0, self.update_dashboard)
        self.query_one("#manual_buy_input").focus()

        self.tail_log_file()

    def on_unmount(self) -> None:
        if self.log_file_handle:
            self.log_file_handle.close()

    @work(group="log_tailer", thread=True)
    def tail_log_file(self) -> None:
        self.log_display.write(f"Tailing log file: [yellow]{self.log_file_path}[/]")
        try:
            if not os.path.exists(self.log_file_path):
                self.log_display.write(f"[dim]Log file not found. Creating...[/dim]")
                os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)
                with open(self.log_file_path, 'w') as f:
                    pass

            self.log_file_handle = open(self.log_file_path, 'r')
            self.log_file_handle.seek(0, 2)

            worker = get_current_worker()
            while not worker.is_cancelled:
                line = self.log_file_handle.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                self.call_from_thread(self.process_log_line, line)

        except Exception as e:
            self.call_from_thread(self.log_display.write, f"[bold red]Error tailing log file: {e}[/]")

    def process_log_line(self, line: str) -> None:
        try:
            log_entry = json.loads(line)
            level = log_entry.get("level", "INFO")
            message = log_entry.get("message", "")

            if self.log_filter.lower() in message.lower() or self.log_filter.upper() in level:
                color = "white"
                if level == "INFO": color = "green"
                elif level == "WARNING": color = "yellow"
                elif level == "ERROR": color = "red"
                elif level == "CRITICAL": color = "bold red"
                self.log_display.write(f"[[{color}]{level}[/{color}]] {message}")
        except json.JSONDecodeError:
            if self.log_filter == "":
                self.log_display.write(f"[dim]{line.strip()}[/dim]")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "log_filter_input":
            self.log_filter = event.value
            self.log_display.clear()
            self.log_display.write("[bold green]Log filter applied. Tailing new logs...[/bold green]")

    @work(thread=True)
    def run_script_worker(self, command: list[str], message_type: type[Message]) -> None:
        self.call_from_thread(self.log_display.write, f"Executing: [yellow]{' '.join(command)}[/]")
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                encoding='utf-8',
                errors='replace'
            )

            if process.returncode != 0:
                output = process.stderr.strip()
                success = False
                self.call_from_thread(self.log_display.write, f"[bold red]Script Error:[/bold red] {output}")
            else:
                output = process.stdout.strip()
                success = True
            
            try:
                data = json.loads(output)
                self.post_message(message_type(data, success))
            except (json.JSONDecodeError, TypeError):
                self.post_message(message_type(output, success))

        except FileNotFoundError:
            self.post_message(message_type("Script not found", False))
            self.call_from_thread(self.log_display.write, f"[bold red]Error: Script not found.[/bold red]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "force_buy_button":
            input_widget = self.query_one("#manual_buy_input", Input)
            if not input_widget.is_valid:
                self.log_display.write("[bold red]Invalid buy amount.[/bold red]")
                return
            amount = input_widget.value
            command = ["python", "scripts/force_buy.py", amount]
            self.run_script_worker(command, CommandOutput)
            input_widget.value = ""

        elif event.button.id == "force_sell_button":
            if not self.selected_trade_id:
                self.log_display.write("[bold red]No trade selected for selling.[/bold red]")
                return

            percentage = "90"
            command = ["python", "scripts/force_sell.py", self.selected_trade_id, percentage]
            self.run_script_worker(command, CommandOutput)

            self.query_one("#action_bar").add_class("hidden")
            self.query_one("#positions_table").move_cursor(row=-1)
            self.selected_trade_id = None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control.id == "positions_table":
            self.selected_trade_id = event.row_key.value
            self.query_one("#action_bar").remove_class("hidden")
    
    def update_dashboard(self) -> None:
        command = ["python", "scripts/get_bot_data.py", self.mode]
        self.run_script_worker(command, DashboardData)

    def on_dashboard_data(self, message: DashboardData) -> None:
        if not message.success or not isinstance(message.data, dict):
            self.log_display.write(f"[bold red]Failed to get dashboard data: {message.data}[/]")
            return
        
        data = message.data
        
        price = Decimal(data.get("current_btc_price", 0))
        self.query_one("#status_symbol").update(f"Symbol: {data.get('symbol', 'N/A')}")
        self.query_one("#status_price").update(f"Price: ${price:,.2f}")

        # Update Next Buy Info
        buy_signal_info = data.get("buy_signal_status", {})
        buy_target = Decimal(buy_signal_info.get("btc_purchase_target", 0))
        buy_progress = float(buy_signal_info.get("btc_purchase_progress_pct", 0))
        self.query_one("#next_buy_target").update(f"Target Price: ${buy_target:,.2f}")
        self.query_one("#next_buy_progress", ProgressBar).progress = buy_progress

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
                usd_to_target = Decimal(pos.get("usd_to_target", 0))
                pnl_color = "green" if pnl >= 0 else "red"
                
                progress_bar = ProgressBar(total=100, show_eta=False, show_percentage=True)
                progress_bar.progress = min(progress, 100) # Cap progress at 100 for display
                if progress >= 100:
                    progress_bar.add_class("progress-complete")

                pos_table.add_row(
                    pos_id.split('-')[0],
                    f"${entry_price:,.2f}",
                    f"${current_value:,.2f}",
                    f"${usd_to_target:,.2f}",
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
                if asset in ["USDT", "BTC"]:
                    usd_val = Decimal(bal.get("usd_value", 0))
                    wallet_table.add_row(asset, f"${usd_val:,.2f}")
        else:
            wallet_table.add_row("No wallet data.")

    def on_command_output(self, message: CommandOutput) -> None:
        if message.success:
            self.log_display.write(f"[green]Command success:[/green] {message.output}")
        else:
            self.log_display.write(f"[bold red]Command failed:[/bold red] {message.output}")
        self.update_dashboard()

def run_tui():
    import argparse
    parser = argparse.ArgumentParser(description="Executa o dashboard do Jules Bot.")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["trade", "test"],
        default="test",
        help="O modo de negociação a ser monitorado ('trade' ou 'test')."
    )
    args = parser.parse_args()

    app = TUIApp(mode=args.mode)
    app.run()

if __name__ == "__main__":
    run_tui()