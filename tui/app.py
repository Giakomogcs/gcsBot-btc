import json
import subprocess
import sys
import os
from decimal import Decimal
import time
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal, Vertical, Container
from textual.widgets import Header, Footer, DataTable, Input, Button, Label, Static, RichLog, TabbedContent, TabPane
from textual.validation import Validator, ValidationResult
from textual.worker import Worker, get_current_worker
from textual import work
from textual.message import Message
from textual.reactive import reactive

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

class NumberValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            if float(value) > 0:
                return self.success()
            else:
                return self.failure("Must be a positive number.")
        except ValueError:
            return self.failure("Invalid number format.")

# --- Custom Messages for Worker Communication ---

class DashboardData(Message):
    def __init__(self, data: dict | str, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

class CommandOutput(Message):
    def __init__(self, output: str, success: bool) -> None:
        self.output = output
        self.success = success
        super().__init__()

class PortfolioData(Message):
    def __init__(self, data: dict | str, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

class PerformanceSummaryData(Message):
    def __init__(self, data: dict | str, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

class TradeHistoryData(Message):
    def __init__(self, data: list | dict, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

# --- Status Indicator Widget ---
class StatusIndicator(Static):
    """A widget to display a colored status circle."""
    status = reactive("OFF")

    def render(self) -> str:
        status_colors = {
            "RUNNING": "green",
            "ERROR": "red",
            "STOPPED": "gray",
            "OFF": "gray"
        }
        color = status_colors.get(self.status, "gray")
        return f"[{color}]●[/] {self.status}"

    def watch_status(self, new_status: str) -> None:
        self.refresh()

class TUIApp(App):
    """A Textual app to display and control the trading bot's status."""

    BINDINGS = [("d", "toggle_dark", "Toggle Dark Mode"), ("q", "quit", "Quit")]
    CSS_PATH = "app.css"

    def __init__(self, mode: str = "test", container_id: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.container_id = container_id
        self.selected_trade_id: str | None = None
        self.log_display: RichLog | None = None
        
        self.bot_name = os.getenv("BOT_NAME", "jules_bot")
        logger.info(f"TUI is initializing for bot: {self.bot_name} (Container: {self.container_id})")

        config_manager.initialize(self.bot_name)
        self.log_filter = ""

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with TabbedContent(initial="dashboard"):
            with TabPane("Dashboard", id="dashboard"):
                with Horizontal(id="main_container"):
                    with VerticalScroll(id="left_pane"):
                        yield Static("Bot Control", classes="title")
                        yield Label("Manual Buy (USD):")
                        yield Input(placeholder="e.g., 50.00", id="manual_buy_input", validators=[NumberValidator()])
                        with Horizontal():
                            yield Button("FORCE BUY", id="force_buy_button", variant="primary")
                            yield Button("FORCE SELL", id="force_sell_button", variant="error", disabled=True)

                        yield Static(f"Live Log for {self.bot_name}", classes="title")
                        with Horizontal(id="log_filter_bar"):
                            yield Label("Filter:", id="log_filter_label")
                            yield Input(placeholder="e.g., ERROR", id="log_filter_input")
                        yield RichLog(id="log_display", wrap=True, markup=True, min_width=0)

                    with VerticalScroll(id="middle_pane"):
                        yield Static(f"Bot Status for {self.bot_name}", classes="title")
                        with Static(id="status_container"):
                            yield Static(f"Mode: {self.mode.upper()}", id="status_mode")
                            yield Static("Symbol: N/A", id="status_symbol")
                            yield Static("BTC Price: N/A", id="status_price")
                            yield Static("Open Positions: N/A", id="status_open_positions")
                            yield Static("Wallet Value: N/A", id="status_wallet_usd")

                        yield Static("Strategy Status", classes="title")
                        with Static(id="strategy_container"):
                            yield Static("Operating Mode: N/A", id="strategy_operating_mode")
                            yield Static("Market Regime: N/A", id="strategy_market_regime")
                            yield Static("Status: N/A", id="strategy_buy_reason")
                            yield Static("Next Buy Target: N/A", id="strategy_buy_target")
                            yield Static("Drop Needed: N/A", id="strategy_buy_target_percentage")
                            yield Static("Buy Progress: N/A", id="strategy_buy_progress")

                        yield Static("Wallet Balances", classes="title")
                        yield DataTable(id="wallet_table")

                        yield Static("Open Positions", classes="title")
                        yield DataTable(id="positions_table")

                    with VerticalScroll(id="right_pane"):
                        yield Static("Performance Summary", classes="title")
                        with Static(id="performance_summary_container"):
                            yield Label("Total Realized PnL (USD): N/A", id="perf_pnl_usd")
                            yield Label("Total Realized PnL (BTC): N/A", id="perf_pnl_btc")
                            yield Label("Total Treasury (BTC): N/A", id="perf_treasury_btc")

                        yield Static("Portfolio Evolution", classes="title")
                        yield Static("Total Portfolio Value: N/A", id="portfolio_total_value")
                        yield Static("Evolution (Total): N/A", id="portfolio_evolution_total")
                        yield Static("Realized Profit/Loss: N/A", id="portfolio_realized_pnl")
                        yield Static("Evolution (24h): N/A", id="portfolio_evolution_24h")
                        yield Static("BTC Treasury: N/A", id="portfolio_btc_treasury")
                        yield Static("Accumulated BTC: N/A", id="portfolio_accumulated_btc")

                        yield Static("DCOM Status", classes="title")
                        yield Static("Total Equity: N/A", id="dcom_total_equity")
                        yield Static("Working Capital: N/A", id="dcom_working_capital")
                        yield Static("Strategic Reserve: N/A", id="dcom_strategic_reserve")
                        yield Static("Operating Mode: N/A", id="dcom_operating_mode")

                        yield Static("Portfolio Value History", classes="title")
                        with Vertical(id="chart_container"):
                            yield Static(id="portfolio_chart")

            with TabPane("Trade History", id="history"):
                yield DataTable(id="history_table")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Add status indicator to header
        header = self.query_one(Header)
        header.tall = False
        header.add_child(StatusIndicator(id="status_indicator"))

        self.log_display = self.query_one(RichLog)
        self.log_display.write(f"[bold green]TUI Initialized for {self.bot_name}.[/bold green]")

        # Setup tables
        positions_table = self.query_one("#positions_table", DataTable)
        positions_table.cursor_type = "row"
        positions_table.add_columns("ID", "Entry", "Value", "PnL", "Sell Target", "Target Status")

        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.add_columns("Asset", "Free", "Locked", "Total", "USD Value")

        history_table = self.query_one("#history_table", DataTable)
        history_table.add_columns("Timestamp", "Symbol", "Type", "Status", "Price", "Quantity", "USD Value", "PnL (USD)")

        # Start background workers
        self.update_dashboard()
        self.set_interval(20.0, self.update_dashboard)
        self.update_portfolio_dashboard()
        self.set_interval(30.0, self.update_portfolio_dashboard)
        self.update_performance_summary()
        self.set_interval(60.0, self.update_performance_summary)
        self.update_trade_history()
        self.set_interval(120.0, self.update_trade_history)

        self.query_one("#manual_buy_input").focus()
        self.stream_docker_logs()

    # --- Worker Methods ---

    @work(group="log_streamer", thread=True)
    def stream_docker_logs(self) -> None:
        if not self.container_id:
            self.log_display.write("[bold red]Error: Container ID not provided to TUI.[/]")
            return
        self.log_display.write(f"Streaming logs from container [yellow]{self.container_id[:12]}[/]")
        try:
            process = subprocess.Popen(["docker", "logs", "-f", self.container_id], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            worker = get_current_worker()
            while not worker.is_cancelled:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None: break
                    time.sleep(0.1)
                    continue
                self.call_from_thread(self.process_log_line, line)
            if not worker.is_cancelled:
                self.call_from_thread(self.log_display.write, "[bold yellow]Log stream ended.[/]")
        except FileNotFoundError:
             self.call_from_thread(self.log_display.write, f"[bold red]Error: 'docker' command not found.[/]")
        except Exception as e:
            self.call_from_thread(self.log_display.write, f"[bold red]Error streaming logs: {e}[/]")

    @work(thread=True)
    def run_script_worker(self, command: list[str], message_type: type[Message]) -> None:
        # This function now only handles the subprocess execution part.
        # The logging of the command execution is removed to avoid clutter.
        try:
            script_env = os.environ.copy()
            script_env["BOT_NAME"] = self.bot_name
            process = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='replace', env=script_env)

            if process.returncode != 0:
                output = process.stderr.strip() or process.stdout.strip()
                success = False
                self.call_from_thread(self.log_display.write, f"[bold red]Script Error ({' '.join(command)}):[/] {output}")
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
            self.call_from_thread(self.log_display.write, f"[bold red]Error: Script '{command[1]}' not found.[/]")
        except Exception as e:
            self.post_message(message_type(f"Worker error: {e}", False))

    # --- Data Update Initiators ---

    def update_dashboard(self) -> None:
        command = ["python", "scripts/get_bot_data.py", self.mode, self.bot_name]
        self.run_script_worker(command, DashboardData)

    def update_portfolio_dashboard(self) -> None:
        command = ["python", "scripts/get_portfolio_data.py", self.bot_name]
        self.run_script_worker(command, PortfolioData)

    def update_performance_summary(self) -> None:
        command = ["python", "scripts/get_tui_performance_data.py", self.bot_name]
        self.run_script_worker(command, PerformanceSummaryData)

    def update_trade_history(self) -> None:
        command = ["python", "scripts/get_trade_history.py", self.bot_name]
        self.run_script_worker(command, TradeHistoryData)

    # --- Message Handlers (UI Updates) ---

    def on_dashboard_data(self, message: DashboardData) -> None:
        if not message.success or not isinstance(message.data, dict):
            self.query_one(StatusIndicator).status = "ERROR"
            self.log_display.write(f"[bold red]Failed to get dashboard data: {message.data}[/]")
            return
        
        data = message.data
        self.query_one(StatusIndicator).status = data.get("bot_status", "OFF")
        
        price = Decimal(data.get("current_btc_price", 0))
        self.query_one("#status_symbol").update(f"Symbol: {data.get('symbol', 'N/A')}")
        self.query_one("#status_price").update(f"Price: ${price:,.2f}")
        self.query_one("#status_open_positions").update(f"Open Positions: {data.get('open_positions_count', 0)}")
        self.query_one("#status_wallet_usd").update(f"Wallet Value: ${Decimal(data.get('total_wallet_usd_value', 0)):,.2f}")

        self.update_strategy_panel(data.get("buy_signal_status", {}), price)
        self.update_wallet_table(data.get("wallet_balances", []))
        self.update_positions_table(data.get("open_positions_status", []), price)

    def on_portfolio_data(self, message: PortfolioData) -> None:
        if not message.success or not isinstance(message.data, dict):
            self.log_display.write(f"[bold red]Failed to get portfolio data: {message.data}[/]")
            return
        # Dummy implementation for now
        pass

    def on_performance_summary_data(self, message: PerformanceSummaryData) -> None:
        if not message.success or not isinstance(message.data, dict):
            self.log_display.write(f"[bold red]Failed to get performance summary data: {message.data}[/]")
            return
        # Dummy implementation for now
        pass

    def on_trade_history_data(self, message: TradeHistoryData) -> None:
        if not message.success or not isinstance(message.data, list):
            self.log_display.write(f"[bold red]Failed to get trade history: {message.data}[/]")
            return
        table = self.query_one("#history_table", DataTable)
        table.clear()
        for trade in message.data:
            pnl = trade.get('realized_pnl_usd')
            pnl_str = f"${Decimal(pnl):,.2f}" if pnl is not None else "N/A"
            pnl_color = "green" if pnl is not None and Decimal(pnl) >= 0 else "red"

            timestamp = datetime.fromisoformat(trade['timestamp']).strftime('%Y-%m-%d %H:%M:%S')

            table.add_row(
                timestamp,
                trade.get('symbol'),
                trade.get('order_type'),
                trade.get('status'),
                f"${Decimal(trade.get('price', 0)):,.2f}",
                f"{Decimal(trade.get('quantity', 0)):.8f}",
                f"${Decimal(trade.get('usd_value', 0)):,.2f}",
                f"[{pnl_color}]{pnl_str}[/]",
                key=trade.get('trade_id')
            )

    def on_command_output(self, message: CommandOutput) -> None:
        if message.success:
            self.log_display.write(f"[green]Command success:[/green] {message.output}")
        else:
            self.log_display.write(f"[bold red]Command failed:[/bold red] {message.output}")
        self.update_dashboard()
        self.update_trade_history()

    # --- UI Update Helpers ---

    def update_strategy_panel(self, status: dict, price: Decimal):
        # Placeholder for brevity
        self.query_one("#strategy_operating_mode").update(f"Operating Mode: {status.get('operating_mode', 'N/A')}")

    def update_wallet_table(self, balances: list):
        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.clear()
        if not balances:
            wallet_table.add_row("No balance data.")
            return
        for bal in balances:
            asset = bal.get('asset')
            free = Decimal(bal.get('free', '0'))
            locked = Decimal(bal.get('locked', '0'))
            total = free + locked
            usd_value = Decimal(bal.get('usd_value', '0'))
            if asset == 'BTC':
                wallet_table.add_row(asset, f"{free:.8f}", f"{locked:.8f}", f"{total:.8f}", f"${usd_value:,.2f}")
            else:
                wallet_table.add_row(asset, f"${free:,.2f}", f"${locked:,.2f}", f"${total:,.2f}", f"${usd_value:,.2f}")

    def update_positions_table(self, positions: list, price: Decimal):
        pos_table = self.query_one("#positions_table", DataTable)
        pos_table.clear()
        if not positions:
            pos_table.add_row("No open positions.")
            return
        for pos in positions:
            pnl = Decimal(pos.get("unrealized_pnl", 0))
            pnl_color = "green" if pnl >= 0 else "red"
            progress_text = f"{float(pos.get('progress_to_sell_target_pct', 0)):.1f}%"
            pos_table.add_row(
                pos.get("trade_id", "N/A").split('-')[0],
                f"${Decimal(pos.get('entry_price', 0)):,.2f}",
                f"${Decimal(pos.get('quantity', 0)) * price:,.2f}",
                f"[{pnl_color}]${pnl:,.2f}[/]",
                f"${Decimal(pos.get('sell_target_price', 0)):,.2f}",
                progress_text,
                key=pos.get("trade_id")
            )

    def process_log_line(self, line: str) -> None:
        try:
            log_entry = json.loads(line)
            level = log_entry.get("level", "INFO")
            message = log_entry.get("message", "")
            if self.log_filter.lower() in message.lower() or self.log_filter.upper() in level:
                color_map = {"INFO": "green", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold red"}
                color = color_map.get(level, "white")
                self.log_display.write(f"[[{color}]{level}[/{color}]] {message}")
        except json.JSONDecodeError:
            if self.log_filter == "":
                self.log_display.write(f"[dim]{line.strip()}[/dim]")

    # --- Event Handlers ---

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "force_buy_button":
            input_widget = self.query_one("#manual_buy_input", Input)
            if input_widget.is_valid:
                amount = input_widget.value
                command = ["python", "scripts/force_buy.py", amount, self.bot_name]
                self.run_script_worker(command, CommandOutput)
                input_widget.value = ""
            else:
                self.log_display.write("[bold red]Invalid buy amount.[/bold red]")
        elif event.button.id == "force_sell_button":
            if self.selected_trade_id:
                command = ["python", "scripts/force_sell.py", self.selected_trade_id, "100", self.bot_name]
                self.run_script_worker(command, CommandOutput)
                self.query_one("#force_sell_button").disabled = True
                self.selected_trade_id = None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control.id == "positions_table":
            self.selected_trade_id = event.row_key.value
            self.query_one("#force_sell_button").disabled = False

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "log_filter_input":
            self.log_filter = event.value
            self.log_display.clear()
            self.log_display.write("[bold green]Log filter applied. Tailing new logs...[/bold green]")

def run_tui():
    """Command-line entry point for the TUI."""
    import argparse
    parser = argparse.ArgumentParser(description="Run the Jules Bot TUI Dashboard.")
    parser.add_argument("--mode", type=str, choices=["trade", "test"], default="test", help="Trading mode to monitor.")
    parser.add_argument("--container-id", type=str, required=True, help="The container ID of the running bot for log streaming.")
    args = parser.parse_args()

    app = TUIApp(mode=args.mode, container_id=args.container_id)
    app.run()

if __name__ == "__main__":
    run_tui()
