import json
import subprocess
import sys
import os
import tempfile
from decimal import Decimal, InvalidOperation
import time
from datetime import datetime
import requests

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.widgets.data_table import CellDoesNotExist, RowDoesNotExist
from textual.widgets import Footer, DataTable, Input, Button, Label, Static, RichLog, TabbedContent, TabPane
from textual.validation import Validator, ValidationResult
from textual.worker import Worker, get_current_worker
from textual import work
from textual.coordinate import Coordinate
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from rich.text import Text
from textual_plotext import PlotextPlot
from textual_timepiece.pickers import DatePicker
from whenever import Date
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
SUDO_PREFIX = ["sudo"] if os.name != "nt" else []

from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

class NumberValidator(Validator):
    def validate(self, value: str) -> ValidationResult:
        try:
            if float(value) > 0: return self.success()
            else: return self.failure("Must be a positive number.")
        except ValueError:
            return self.failure("Invalid number format.")

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

class ProcessedPositionsData(Message):
    """Carries processed positions data from the worker."""
    def __init__(self, sorted_positions: list, summary_text: str) -> None:
        self.sorted_positions = sorted_positions
        self.summary_text = summary_text
        super().__init__()

class ProcessedHistoryData(Message):
    """Carries processed trade history data from the worker."""
    def __init__(self, sorted_history: list, summary_text: str) -> None:
        self.sorted_history = sorted_history
        self.summary_text = summary_text
        super().__init__()

class StatusIndicator(Static):
    status = reactive("OFF")
    def render(self) -> str:
        colors = {"RUNNING": "green", "ERROR": "red", "STOPPED": "gray", "OFF": "gray", "SYNCHRONIZING...": "yellow"}
        return f"[{colors.get(self.status, 'gray')}]●[/] {self.status}"
    def watch_status(self, new_status: str) -> None:
        self.refresh()

class CustomHeader(Static):
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("GCS Trading Bot Dashboard", id="header_title")
            yield StatusIndicator(id="status_indicator")

class DatePickerModal(Screen[Date]):
    """A modal screen for the date picker."""
    def compose(self) -> ComposeResult:
        yield Vertical(
            DatePicker(id="date_picker"),
            id="date_picker_dialog",
        )

    def on_mount(self) -> None:
        self.query_one(DatePicker).focus()

    def on_date_picker_date_changed(self, event) -> None:
        """Called when the date is changed in the date picker."""
        self.dismiss(event.date)

class TUIApp(App):
    BINDINGS = [("d", "toggle_dark", "Toggle Dark Mode"), ("q", "quit", "Quit")]
    CSS_PATH = "app.css"

    def __init__(self, mode: str = "test", container_id: str | None = None, bot_name: str = "jules_bot", host_port: int = 8000, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.container_id = container_id
        self.host_port = host_port
        self.selected_trade_id: str | None = None
        self.log_display: RichLog | None = None
        self.bot_name = bot_name
        logger.info(f"TUI is initializing for bot: {self.bot_name} (Container: {self.container_id}, Port: {self.host_port})")
        # The TUI runs in its own process and the bot_name is passed as an argument.
        # We must manually update the config_manager singleton's state to ensure
        # any components it uses (none currently, but good practice) have the right context.
        config_manager.bot_name = self.bot_name
        self.log_filter = ""
        self.open_positions_data = []
        self._last_positions_data: str | None = None
        self.trade_history_data = []
        self._last_history_data: str | None = None
        self.positions_sort_column = "Unrealized PnL"
        self.positions_sort_reverse = True
        self.history_sort_column = "Timestamp"
        self.history_sort_reverse = True
        self.history_filter = "all"

    def compose(self) -> ComposeResult:
        yield CustomHeader()
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
                    with Vertical(id="middle_pane"):
                        with Horizontal(id="top_middle_pane"):
                            with VerticalScroll(id="status_and_strategy"):
                                yield Static(f"Bot Status for {self.bot_name}", classes="title")
                                with Static(id="status_container"):
                                    yield Static(f"Mode: {self.mode.upper()}", id="status_mode")
                                    yield Static("Symbol: N/A", id="status_symbol")
                                    yield Static("Price: N/A", id="status_price")
                                    yield Static("Wallet Value: N/A", id="status_wallet_usd")
                                    yield Static("Realized PnL: N/A", id="status_realized_pnl")
                                    yield Static("Unrealized PnL: N/A", id="status_unrealized_pnl")
                                    yield Static("Total PnL: N/A", id="status_total_pnl")
                                    yield Static("Positions: N/A", id="status_positions_count")
                                yield Static("Strategy Status", classes="title")
                                with Static(id="strategy_container"):
                                    yield Static("Operating Mode: N/A", id="strategy_operating_mode")
                                    yield Static("Market Regime: N/A", id="strategy_market_regime")
                                    yield Static("Status: N/A", id="strategy_buy_reason")
                                    yield Static("Next Buy Target: N/A", id="strategy_buy_target")
                                    yield Static("Drop Needed: N/A", id="strategy_buy_target_percentage")
                                    yield Static("Buy Progress: N/A", id="strategy_buy_progress")
                               
                            with VerticalScroll(id="portfolio_and_positions"):
                                yield Static("Wallet Balances", classes="title")
                                yield DataTable(id="wallet_table")
                                yield Static("Positions Summary", classes="title")
                                yield Label("Summary: N/A", id="positions_summary_label")
                                yield Static("Capital Allocation", classes="title")
                                with Static(id="capital_container"):
                                    yield Static("Working Capital: $0 | Used: $0 | Free: $0", id="info_working_capital")
                                    yield Static("USDT Strategic Reserve: $0", id="info_strategic_reserve")
                                    yield Static("Unmanaged BTC Reserve: $0", id="info_unmanaged_btc_reserve") # New line
                                    yield Static("Operating Mode: N/A", id="info_operating_mode")
                        with VerticalScroll(id="open_positions"):
                            yield Static("Open Positions", classes="title")
                            yield DataTable(id="positions_table")
            with TabPane("Trade History", id="history"):
                with Vertical():
                    with Horizontal(id="history_filter_bar"):
                        yield Button("All", id="filter_all_button", variant="primary")
                        yield Button("Open", id="filter_open_button")
                        yield Button("Closed", id="filter_closed_button")
                        yield Input(placeholder="Start (YYYY-MM-DD)", id="start_date_input", classes="date_input")
                        yield Input(placeholder="End (YYYY-MM-DD)", id="end_date_input", classes="date_input")
                        yield Button("Filter", id="filter_date_button")
                    yield Label("Summary: N/A", id="history_summary_label")
                    with Horizontal():
                        yield DataTable(id="history_table", classes="history_table")
                        with Vertical(id="portfolio_chart_container"):
                            yield Static("Portfolio Value History", classes="title", id="portfolio_title")
                            yield PlotextPlot(id="portfolio_chart")
        yield Footer()

    def on_mount(self) -> None:
        self.log_display = self.query_one(RichLog)
        self.log_display.write(f"[bold green]TUI Initialized for {self.bot_name}.[/bold green]")
        positions_table = self.query_one("#positions_table", DataTable)
        positions_table.cursor_type = "row"
        positions_table.add_columns("TS", "ID", "Date", "Entry", "Value", "Unrealized PnL", "PnL %", "Peak PnL", "Trail %", "Target", "Target PnL", "Progress")
        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.add_columns("Asset", "Available", "Total", "USD Value")
        history_table = self.query_one("#history_table", DataTable)
        history_table.cursor_type = "row"
        history_table.add_columns("Timestamp", "Symbol", "Type", "Status", "Buy Price", "Sell Price", "Quantity", "USD Value", "PnL (USD)", "PnL (%)", "Trade ID")
        
        # Start the new, unified update worker
        self.update_from_status_file()
        self.set_interval(2.0, self.update_from_status_file)

        self.query_one("#manual_buy_input").focus()
        self.stream_docker_logs()

    @work(group="log_streamer", thread=True)
    def stream_docker_logs(self) -> None:
        if not self.container_id:
            self.log_display.write("[bold red]Error: Container ID not provided.[/]")
            return
        self.log_display.write(f"Streaming logs from container [yellow]{self.container_id[:12]}[/]")
        try:
            process = subprocess.Popen(SUDO_PREFIX + ["docker", "logs", "-f", self.container_id], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
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
             self.call_from_thread(self.log_display.write, "[bold red]Error: 'docker' command not found.[/]")
        except Exception as e:
            self.call_from_thread(self.log_display.write, f"[bold red]Error streaming logs: {e}[/]")

    @work(thread=True)
    def api_call_worker(self, endpoint: str, payload: dict) -> None:
        """
        Makes a direct API call to the bot's API server.
        """
        url = f"http://localhost:{self.host_port}/api/{endpoint}"
        try:
            self.log_display.write(f"Sending POST request to {url} with payload: {json.dumps(payload)}")
            response = requests.post(url, json=payload, timeout=15)
            
            if response.status_code == 200:
                self.post_message(CommandOutput(json.dumps(response.json()), success=True))
            else:
                try:
                    # Try to parse the JSON error from the server
                    error_detail = response.json().get("detail", response.text)
                except json.JSONDecodeError:
                    error_detail = response.text
                output = f"API Error (HTTP {response.status_code}): {error_detail}"
                self.post_message(CommandOutput(output, success=False))

        except requests.exceptions.RequestException as e:
            self.post_message(CommandOutput(f"Failed to connect to bot API: {e}", success=False))
        except Exception as e:
            self.post_message(CommandOutput(f"An unexpected error occurred: {e}", success=False))

    @work(thread=True)
    def process_positions_worker(self, positions_data: list, sort_column: str, sort_reverse: bool) -> None:
        """Processes and sorts open positions data in a background thread."""
        try:
            # --- Perform expensive calculations ---
            for pos in positions_data:
                pos['current_value'] = Decimal(pos.get('quantity', 0)) * Decimal(pos.get('current_price', 0))
            
            open_positions_count = len(positions_data)
            if open_positions_count > 0:
                total_invested = sum(Decimal(p.get('entry_price', 0)) * Decimal(p.get('quantity', 0)) for p in positions_data)
                current_market_value = sum(p['current_value'] for p in positions_data)
                total_unrealized_pnl = sum(Decimal(p.get('unrealized_pnl', 0)) for p in positions_data)
                pnl_color = "green" if total_unrealized_pnl >= 0 else "red"
                summary_text = (
                    f"Open Positions: {open_positions_count}\n\n"
                    f"  Total Invested: ${total_invested:,.2f}\n"
                    f"  Market Value:   ${current_market_value:,.2f}\n"
                    f"  Unrealized PnL: [{pnl_color}]${total_unrealized_pnl:,.2f}[/]"
                )
            else:
                summary_text = "No open positions."

            # --- Perform sorting ---
            sort_key_map = {
                "ID": "trade_id", "Date": "timestamp", "Entry": "entry_price", "Value": "current_value",
                "Unrealized PnL": "unrealized_pnl", "PnL %": "unrealized_pnl_pct",
                "Peak PnL": "smart_trailing_highest_profit", "Trail %": "current_trail_percentage",
                "Target": "sell_target_price", "Target PnL": "target_pnl",
                "Progress": "progress_to_sell_target_pct"
            }
            sort_key = sort_key_map.get(sort_column, "unrealized_pnl")
            numeric_keys = [
                "entry_price", "current_value", "unrealized_pnl", "unrealized_pnl_pct",
                "smart_trailing_highest_profit", "current_trail_percentage",
                "sell_target_price", "target_pnl", "progress_to_sell_target_pct"
            ]

            def sort_func(p):
                val = p.get(sort_key)
                if val is None: return -float('inf') if sort_reverse else float('inf')
                if sort_key in numeric_keys:
                    try: return Decimal(val)
                    except (InvalidOperation, TypeError): return -float('inf') if sort_reverse else float('inf')
                else: return str(val)

            sorted_positions = sorted(positions_data, key=sort_func, reverse=sort_reverse)
            
            self.post_message(ProcessedPositionsData(sorted_positions, summary_text))
        except Exception as e:
            # Log the error or post an error message back to the main thread
            self.call_from_thread(self.log_display.write, f"[bold red]Error in positions worker: {e}[/]")

    @work(thread=True)
    def process_history_worker(self, history_data: list, history_filter: str, start_date_str: str, end_date_str: str, sort_column: str, sort_reverse: bool) -> None:
        """Processes, filters, and sorts trade history data in a background thread."""
        try:
            # --- Filtering ---
            if history_filter == 'open':
                status_filtered_trades = [t for t in history_data if t.get('status') == 'OPEN']
            elif history_filter == 'closed':
                status_filtered_trades = [t for t in history_data if t.get('status') == 'CLOSED']
            else:
                status_filtered_trades = history_data
            
            # --- Additional Filtering for Closed Buys ---
            # Remove closed buy orders as they are represented by the sell record
            status_filtered_trades = [
                t for t in status_filtered_trades
                if not (t.get('order_type') == 'buy' and t.get('status') == 'CLOSED')
            ]

            final_filtered_history = []
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else None
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else None
            for trade in status_filtered_trades:
                trade_date = datetime.fromisoformat(trade['timestamp']).date()
                if (start_date and trade_date < start_date) or (end_date and trade_date > end_date):
                    continue
                final_filtered_history.append(trade)

            # --- Summary Calculation ---
            total_trades = len(final_filtered_history)
            if total_trades > 0:
                buy_trades = [t for t in final_filtered_history if t.get('order_type') == 'buy']
                closed_sells = [t for t in final_filtered_history if t.get('order_type') == 'sell' and t.get('status') == 'CLOSED']
                total_invested = sum(Decimal(t.get('usd_value', 0)) for t in buy_trades if t.get('usd_value') is not None)
                total_returned = sum(Decimal(t.get('sell_usd_value', 0)) for t in closed_sells if t.get('sell_usd_value') is not None)
                total_realized_pnl = sum(Decimal(t.get('realized_pnl_usd', 0)) for t in closed_sells if t.get('realized_pnl_usd') is not None)
                roi_pct = (total_realized_pnl / total_invested * 100) if total_invested > 0 else 0
                pnl_color = "green" if total_realized_pnl >= 0 else "red"
                roi_color = "green" if roi_pct >= 0 else "red"
                summary_text = (
                    f"Filtered Trades: {total_trades} (Buys: {len(buy_trades)}, Sells: {len(closed_sells)})\n\n"
                    f"  Total Invested (in view): ${total_invested:,.2f}\n"
                    f"  Total Returned (in view): ${total_returned:,.2f}\n"
                    f"  Realized PnL (in view):   [{pnl_color}]${total_realized_pnl:,.2f}[/]\n"
                    f"  ROI (of closed in view):  [{roi_color}]{roi_pct:.2f}%[/]"
                )
            else:
                summary_text = "No trades match the current filter."

            # --- Sorting ---
            sort_key_map = {
                "Timestamp": "timestamp", "Symbol": "symbol", "Type": "order_type", "Status": "status",
                "Buy Price": "price", "Sell Price": "sell_price", "Quantity": "quantity",
                "USD Value": "usd_value", "PnL (USD)": "realized_pnl_usd", "PnL (%)": "pnl_percentage",
                "Trade ID": "trade_id"
            }
            sort_key = sort_key_map.get(sort_column, "timestamp")
            numeric_keys = ["price", "sell_price", "quantity", "usd_value", "realized_pnl_usd", "pnl_percentage"]

            def sort_func(trade):
                if sort_key == 'pnl_percentage': val = trade.get('decision_context', {}).get('pnl_percentage')
                else: val = trade.get(sort_key)
                if val is None: return -float('inf') if sort_reverse else float('inf')
                if sort_key in numeric_keys:
                    try: return Decimal(val)
                    except (InvalidOperation, TypeError): return -float('inf') if sort_reverse else float('inf')
                else: return str(val)
            
            sorted_history = sorted(final_filtered_history, key=sort_func, reverse=sort_reverse)

            self.post_message(ProcessedHistoryData(sorted_history, summary_text))
        except ValueError:
            self.call_from_thread(self.log_display.write, "[bold red]Invalid date format. Please use YYYY-MM-DD.[/bold red]")
        except Exception as e:
            self.call_from_thread(self.log_display.write, f"[bold red]Error in history worker: {e}[/]")


    @work(thread=True)
    def read_status_file_worker(self) -> None:
        """Worker to read the bot status from the JSON file."""
        # Use a simple relative path, assuming TUI is run from the project root.
        status_file_path = os.path.join(".tui_files", f".bot_status_{self.bot_name}.json")
        try:
            if os.path.exists(status_file_path):
                with open(status_file_path, "r") as f:
                    content = f.read()
                    if not content:
                        self.post_message(DashboardData("Bot is starting, waiting for status file...", success=False))
                        return
                    data = json.loads(content)
                self.post_message(DashboardData(data, success=True))
            else:
                self.post_message(DashboardData(f"Status file not found for bot '{self.bot_name}'. Is the bot running?", success=False))
        except json.JSONDecodeError:
            self.post_message(DashboardData("Error decoding status file. It might be corrupted or being written.", success=False))
        except Exception as e:
            self.post_message(DashboardData(f"Error reading status file: {e}", success=False))

    def update_from_status_file(self) -> None:
        """Triggers the worker to read the status file."""
        self.read_status_file_worker()

    def on_dashboard_data(self, message: DashboardData) -> None:
        """The single entry point for all data updates from the live status file."""
        if not message.success or not isinstance(message.data, dict):
            # Display a generic error or status message if data loading fails
            self.query_one(StatusIndicator).status = "ERROR"
            # You might want to display the error message from message.data somewhere in the UI
            return

        data = message.data
        self.query_one(StatusIndicator).status = data.get("bot_status", "OFF")
        self.query_one("#header_title").update(f"GCS Trading Bot Dashboard - {self.bot_name}")

        # --- Main Status Panel ---
        price = Decimal(data.get("current_btc_price", 0))
        self.query_one("#status_symbol").update(f"Symbol: {data.get('symbol', 'N/A')}")
        self.query_one("#status_price").update(f"Price: ${price:,.2f}")
        open_count = data.get('open_positions_count', 0)
        total_count = data.get('total_trades_count', 0)
        self.query_one("#status_positions_count").update(f"Positions: {open_count} Open / {total_count} Total")
        wallet_value = Decimal(data.get('total_wallet_usd_value', 0))
        self.query_one("#status_wallet_usd").update(f"Wallet Value: ${wallet_value:,.2f}")
        realized_pnl = Decimal(data.get("total_realized_pnl", 0))
        unrealized_pnl = Decimal(data.get("total_unrealized_pnl", 0))
        net_total_pnl = Decimal(data.get("net_total_pnl", 0))
        realized_color = "green" if realized_pnl >= 0 else "red"
        unrealized_color = "green" if unrealized_pnl >= 0 else "red"
        total_color = "green" if net_total_pnl >= 0 else "red"
        self.query_one("#status_realized_pnl").update(f"Realized PnL: [{realized_color}]${realized_pnl:,.2f}[/]")
        self.query_one("#status_unrealized_pnl").update(f"Unrealized PnL: [{unrealized_color}]${unrealized_pnl:,.2f}[/]")
        self.query_one("#status_total_pnl").update(f"Total PnL: [{total_color}]${net_total_pnl:,.2f}[/]")

        # --- Update All UI Components from the Single Data Source ---
        self.update_strategy_panel(data.get("buy_signal_status", {}), price)
        self.update_capital_panel(data.get("capital_allocation", {}), data.get("buy_signal_status", {}))
        self.update_wallet_table(data.get("wallet_balances", []))

        # --- Trigger background workers to process and render table data ---
        new_positions_data = data.get("open_positions_status", [])
        new_positions_str = json.dumps(new_positions_data)
        if new_positions_str != self._last_positions_data:
            self.log_display.write("Change in positions data detected, updating table...")
            self._last_positions_data = new_positions_str
            self.open_positions_data = new_positions_data
            self.process_positions_worker(self.open_positions_data, self.positions_sort_column, self.positions_sort_reverse)

        new_history_data = data.get("trade_history", [])
        new_history_str = json.dumps(new_history_data)
        if new_history_str != self._last_history_data:
            self.log_display.write("Change in history data detected, updating table...")
            self._last_history_data = new_history_str
            self.trade_history_data = new_history_data
            self.update_history_table() # This will call the worker

        # Update portfolio chart
        self.update_portfolio_chart(data.get("portfolio_history", []))

    def update_history_table(self) -> None:
        """Triggers the history processing worker with the current filters."""
        start_date_str = self.query_one("#start_date_input", Input).value
        end_date_str = self.query_one("#end_date_input", Input).value
        self.process_history_worker(
            self.trade_history_data,
            self.history_filter,
            start_date_str,
            end_date_str,
            self.history_sort_column,
            self.history_sort_reverse
        )

    def on_processed_history_data(self, message: ProcessedHistoryData) -> None:
        """Renders the processed trade history data received from the worker,
        preserving scroll position."""
        table = self.query_one("#history_table", DataTable)
        self.query_one("#history_summary_label").update(message.summary_text)
        self._update_table_headers(table, self.history_sort_column, self.history_sort_reverse)

        # --- Preserve scroll position ---
        cursor_row_key = None
        if table.row_count > 0 and table.is_valid_coordinate(table.cursor_coordinate):
            try:
                cursor_row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            except CellDoesNotExist:
                cursor_row_key = None

        table.clear()

        if not message.sorted_history:
            table.add_row("No trades match the current filter.", key="placeholder_history")
            return

        # --- Repopulate the table with new data ---
        for trade in message.sorted_history:
            trade_id = trade.get("trade_id")
            if not trade_id: continue

            pnl = trade.get('realized_pnl_usd')
            order_type = trade.get('order_type', 'N/A')
            pnl_str = f"${Decimal(pnl):,.2f}" if pnl is not None else "N/A"
            pnl_color = "green" if pnl is not None and Decimal(pnl) >= 0 else "red"
            pnl_cell = f"[{pnl_color}]{pnl_str}[/]" if order_type == 'sell' else "N/A"
            type_color = "green" if order_type == 'buy' else "red"
            type_cell = f"[{type_color}]{order_type.upper()}[/]"
            local_timestamp = datetime.fromisoformat(trade['timestamp'])
            timestamp = local_timestamp.strftime('%Y-%m-%d %H:%M')
            trade_id_short = trade_id.split('-')[0]
            buy_price = f"${Decimal(trade.get('price', 0)):,.2f}"
            sell_price = f"${Decimal(trade.get('sell_price', 0)):,.2f}" if trade.get('sell_price') else "N/A"
            pnl_pct_str = trade.get('decision_context', {}).get('pnl_percentage', 'N/A')
            pnl_pct_cell = "N/A"
            if pnl_pct_str != 'N/A':
                try:
                    pnl_pct_val = Decimal(pnl_pct_str)
                    pct_color = "green" if pnl_pct_val >= 0 else "red"
                    pnl_pct_cell = f"[{pct_color}]{pnl_pct_val:.2f}%[/]"
                except InvalidOperation: pnl_pct_cell = "err"
            
            row_data = (
                timestamp, trade.get('symbol'), type_cell, trade.get('status'), buy_price, sell_price, 
                f"{Decimal(trade.get('quantity', 0)):.8f}", f"${Decimal(trade.get('usd_value', 0)):.2f}", 
                pnl_cell, pnl_pct_cell if order_type == 'sell' else "N/A", trade_id_short
            )
            # Add row with key to allow scroll restoration
            table.add_row(*row_data, key=trade_id)
        
        # --- Restore scroll position ---
        if cursor_row_key:
            try:
                new_row_index = table.get_row_index(cursor_row_key)
                table.move_cursor(row=new_row_index, animate=False)
            except RowDoesNotExist:
                pass # The previously selected row might no longer be in view

    def on_command_output(self, message: CommandOutput) -> None:
        if message.success:
            self.log_display.write(f"[green]Command success:[/green] {message.output}")
            self.log_display.write("[yellow]Command sent. Forcing UI refresh in 1, 2, and 3 seconds...[/yellow]")
            # Trigger multiple refreshes to catch the state update from the bot
            self.set_timer(1.0, self.update_from_status_file)
            self.set_timer(2.0, self.update_from_status_file)
            self.set_timer(3.0, self.update_from_status_file)
        else:
            self.log_display.write(f"[bold red]Command failed:[/bold red] {message.output}")
        # Also trigger one immediate refresh just in case
        self.update_from_status_file()

    def update_capital_panel(self, capital: dict, strategy: dict):
        wc_total = Decimal(capital.get("working_capital_total", 0))
        wc_used = Decimal(capital.get("working_capital_used", 0))
        wc_free = Decimal(capital.get("working_capital_free", 0))
        sr_usdt = Decimal(capital.get("strategic_reserve", 0))
        sr_btc = Decimal(capital.get("unmanaged_btc_reserve", 0))
        op_mode = strategy.get("operating_mode", "N/A")

        self.query_one("#info_working_capital").update(f"Working Capital: ${wc_total:,.0f} | Used: ${wc_used:,.0f} | Free: ${wc_free:,.0f}")
        self.query_one("#info_strategic_reserve").update(f"USDT Strategic Reserve: ${sr_usdt:,.0f}")
        self.query_one("#info_unmanaged_btc_reserve").update(f"Unmanaged BTC Reserve: ${sr_btc:,.0f}")
        self.query_one("#info_operating_mode").update(f"Operating Mode: {op_mode}")

    def update_strategy_panel(self, status: dict, current_price: Decimal):
        operating_mode, market_regime, reason, condition_target_str = status.get("operating_mode", "N/A"), status.get("market_regime", -1), status.get("reason", "N/A"), status.get("condition_target", "N/A")
        self.query_one("#strategy_operating_mode").update(f"Operating Mode: {operating_mode}")
        self.query_one("#strategy_market_regime").update(f"Market Regime: {market_regime}")
        self.query_one("#strategy_buy_reason").update(f"Status: {reason}")
        try:
            target_price = Decimal(condition_target_str.replace('$', '').replace(',', ''))
            price_drop_needed = current_price - target_price
            percentage_drop_needed = (price_drop_needed / current_price * 100) if current_price > 0 else 0
            self.query_one("#strategy_buy_target").update(f"Buy Target: ${target_price:,.2f}")
            self.query_one("#strategy_buy_target_percentage").update(f"Price Drop Needed: ${price_drop_needed:,.2f} ({percentage_drop_needed:.2f}%)")
            progress = float(status.get("condition_progress", 0))
            progress_bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
            self.query_one("#strategy_buy_progress").update(f"Progress: [{progress_bar}] {progress:.1f}%")
        except (ValueError, InvalidOperation):
            self.query_one("#strategy_buy_target").update(f"Buy Target: {condition_target_str}")
            self.query_one("#strategy_buy_target_percentage").update("Price Drop Needed: N/A")
            self.query_one("#strategy_buy_progress").update("Progress: N/A")

    def update_wallet_table(self, balances: list):
        wallet_table = self.query_one("#wallet_table", DataTable)
        
        existing_assets = set(wallet_table.rows.keys())
        new_assets = {bal.get('asset') for bal in balances}

        # Remove assets no longer in the balance list
        for asset in existing_assets - new_assets:
            wallet_table.remove_row(asset)

        # Add or update assets
        for bal in balances:
            asset = bal.get('asset')
            if not asset: continue

            free, total, usd_value = Decimal(bal.get('free','0')), Decimal(bal.get('total','0')), Decimal(bal.get('usd_value','0'))
            row_format = "{:,.8f}" if asset == 'BTC' else "{:,.2f}"
            
            row_data = (
                asset, 
                row_format.format(free), 
                row_format.format(total), 
                f"${usd_value:,.2f}"
            )

            if asset in existing_assets:
                # Update existing row - note we update all cells for simplicity
                row_index = wallet_table.get_row_index(asset)
                for i, cell_value in enumerate(row_data):
                    wallet_table.update_cell_at(Coordinate(row_index, i), cell_value)
            else:
                # Add new row
                wallet_table.add_row(*row_data, key=asset)

        # Handle placeholder for empty table
        has_placeholder = "placeholder_wallet" in wallet_table.rows
        if not balances:
            if not has_placeholder and len(wallet_table.rows) == 0:
                wallet_table.add_row("No balance data.", key="placeholder_wallet")
        elif has_placeholder:
            wallet_table.remove_row("placeholder_wallet")

    def update_positions_table(self) -> None:
        """Triggers the positions processing worker."""
        self.process_positions_worker(self.open_positions_data, self.positions_sort_column, self.positions_sort_reverse)

    def on_processed_positions_data(self, message: ProcessedPositionsData) -> None:
        """Renders the processed open positions data received from the worker,
        preserving scroll position."""
        pos_table = self.query_one("#positions_table", DataTable)
        self.query_one("#positions_summary_label").update(message.summary_text)
        self._update_table_headers(pos_table, self.positions_sort_column, self.positions_sort_reverse)

        # --- Preserve scroll position by saving the key of the row at the cursor ---
        cursor_row_key = None
        if pos_table.row_count > 0 and pos_table.is_valid_coordinate(pos_table.cursor_coordinate):
            try:
                # coordinate_to_cell_key can fail if the cursor is on a header
                cursor_row_key, _ = pos_table.coordinate_to_cell_key(pos_table.cursor_coordinate)
            except CellDoesNotExist:
                cursor_row_key = None # Cursor isn't on a cell, so we can't save the key

        pos_table.clear()

        if not message.sorted_positions:
            pos_table.add_row("No open positions.", key="placeholder_positions")
            return

        # --- Repopulate the table with new data ---
        for pos in message.sorted_positions:
            trade_id = pos.get("trade_id")
            if trade_id is None: continue

            pnl = Decimal(pos.get("unrealized_pnl", 0))
            pnl_color = "green" if pnl >= 0 else "red"
            pnl_pct = Decimal(pos.get("unrealized_pnl_pct", 0))
            pnl_pct_color = "green" if pnl_pct >= 0 else "red"
            pnl_pct_str = f"[{pnl_pct_color}]{pnl_pct:,.2f}%[/]"
            target_pnl = Decimal(pos.get("target_pnl", 0))
            target_pnl_color = "green" if target_pnl >= 0 else "red"
            target_pnl_str = f"[{target_pnl_color}]${target_pnl:,.2f}[/]"
            is_trailing_active = pos.get("is_smart_trailing_active")

            if is_trailing_active:
                final_trigger_profit = Decimal(pos.get('final_trigger_profit', 0))
                progress_str = f"Sell at ${final_trigger_profit:,.2f}"
            else:
                progress = float(pos.get('progress_to_sell_target_pct', 0))
                progress_bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
                progress_str = f"[{progress_bar}] {progress:.1f}%"

            current_value = pos['current_value']
            local_timestamp = datetime.fromisoformat(pos['timestamp'])
            timestamp = local_timestamp.strftime('%Y-%m-%d %H:%M')
            trailing_icon = "🛡️" if pos.get("is_smart_trailing_active") else ""
            peak_pnl = Decimal(pos.get('smart_trailing_highest_profit', 0))
            peak_pnl_str = f"${peak_pnl:,.2f}" if peak_pnl > 0 else "N/A"
            trail_pct = Decimal(pos.get('current_trail_percentage', 0))
            trail_pct_str = f"{trail_pct:.2%}" if trail_pct > 0 else "N/A"

            row_data = (
                trailing_icon, trade_id.split('-')[0], timestamp,
                f"${Decimal(pos.get('entry_price', 0)):,.2f}", f"${current_value:,.2f}",
                f"[{pnl_color}]${pnl:,.2f}[/]", pnl_pct_str, peak_pnl_str,
                trail_pct_str, f"${Decimal(pos.get('sell_target_price', 0)):,.2f}",
                target_pnl_str, progress_str,
            )
            pos_table.add_row(*row_data, key=trade_id)
        
        # --- Restore scroll position ---
        if cursor_row_key:
            try:
                new_row_index = pos_table.get_row_index(cursor_row_key)
                pos_table.move_cursor(row=new_row_index, animate=False)
            except RowDoesNotExist:
                # The row we were on might have been closed/removed.
                # In this case, we can't restore the position, which is acceptable.
                pass

    def update_portfolio_chart(self, history: list):
        chart = self.query_one("#portfolio_chart", PlotextPlot)
        plt = chart.plt
        plt.clear_data()
        if not history:
            chart.refresh()
            return
        dates = [datetime.fromisoformat(item['timestamp']).strftime("%m-%d %H:%M") for item in reversed(history)]
        values = [float(item['value']) for item in reversed(history)]
        plt.plot(values)
        plt.xticks(range(len(dates)), dates)
        plt.title("Portfolio Value (USD)")
        plt.xlabel("Timestamp")
        plt.ylabel("USD Value")
        chart.refresh()

    def process_log_line(self, line: str) -> None:
        """Processes a log line, applying default or user-specified filters."""
        try:
            log_entry = json.loads(line)
            level = log_entry.get("level", "INFO")
            message = log_entry.get("message", "")

            show_log = False
            # If the user has an active filter, it takes precedence.
            if self.log_filter:
                if self.log_filter.lower() in message.lower() or self.log_filter.upper() in level:
                    show_log = True
            # Otherwise, apply the default filter to reduce noise.
            else:
                if level in ["WARNING", "ERROR", "CRITICAL"]:
                    show_log = True
                elif level == "INFO":
                    # Keywords for important INFO messages
                    keywords = ["sell", "buy", "comprou", "vendeu", "position", "trigger", "shutdown", "started"]
                    if any(keyword in message.lower() for keyword in keywords):
                        show_log = True
            
            if show_log:
                color = {"INFO": "green", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold red"}.get(level, "white")
                self.log_display.write(f"[[{color}]{level}[/{color}]] {message}")

        except json.JSONDecodeError:
            # For non-JSON lines (e.g., from docker-compose), only show if there's no filter.
            if not self.log_filter:
                self.log_display.write(f"[dim]{line.strip()}[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "force_buy_button":
            input_widget = self.query_one("#manual_buy_input", Input)
            if input_widget.is_valid:
                payload = {"amount_usd": input_widget.value}
                self.api_call_worker("force_buy", payload)
                input_widget.value = ""
            else:
                self.log_display.write("[bold red]Invalid buy amount.[/bold red]")

        elif event.button.id == "force_sell_button" and self.selected_trade_id:
            event.button.disabled = True
            self.log_display.write(f"[yellow]Initiating force sell for trade ID: {self.selected_trade_id}...[/]")
            payload = {"trade_id": self.selected_trade_id, "percentage": "100"}
            self.api_call_worker("force_sell", payload)
            self.selected_trade_id = None

        elif event.button.id in ["filter_all_button", "filter_open_button", "filter_closed_button"]:
            # Update filter state
            self.history_filter = event.button.id.split('_')[1] # e.g., "all", "open", "closed"

            # Update button variants for visual feedback
            self.query_one("#filter_all_button", Button).variant = "primary" if self.history_filter == "all" else "default"
            self.query_one("#filter_open_button", Button).variant = "primary" if self.history_filter == "open" else "default"
            self.query_one("#filter_closed_button", Button).variant = "primary" if self.history_filter == "closed" else "default"
            
            # Refresh the table
            self.update_history_table()
        elif event.button.id == "filter_date_button":
            self.update_history_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control.id == "positions_table":
            self.selected_trade_id = event.row_key.value
            self.query_one("#force_sell_button").disabled = False

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "log_filter_input":
            self.log_filter = event.value
            self.log_display.clear()
            self.log_display.write("[bold green]Log filter applied. Tailing new logs...[/bold green]")

    def _update_table_headers(self, table: DataTable, sort_column: str, is_reverse: bool):
        """Adds sort indicators (▲/▼) to the table headers, ensuring labels are Text objects."""
        for column in table.columns.values():
            # Safely convert the column label (which could be str or Text) to a string
            label_str = str(column.label)
            # Strip any existing indicator to get the base label
            base_label = label_str.rstrip(" ▲▼")
            
            if base_label == sort_column:
                # Append the correct indicator
                indicator = " ▼" if is_reverse else " ▲"
                new_label_str = f"{base_label}{indicator}"
            else:
                new_label_str = base_label
            
            # Always assign a Text object back to the label to avoid type errors
            column.label = Text(new_label_str)


    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handles sorting when a table header is clicked."""
        table = event.control
        # The event label can be a str or Text object, so convert to str to be safe.
        column_label = str(event.label).rstrip(" ▲▼")

        if table.id == "positions_table":
            if self.positions_sort_column == column_label:
                self.positions_sort_reverse = not self.positions_sort_reverse
            else:
                self.positions_sort_column = column_label
                self.positions_sort_reverse = True  # Default to descending for new column
            self._update_table_headers(table, self.positions_sort_column, self.positions_sort_reverse)
            self.update_positions_table()
        elif table.id == "history_table":
            if self.history_sort_column == column_label:
                self.history_sort_reverse = not self.history_sort_reverse
            else:
                self.history_sort_column = column_label
                self.history_sort_reverse = True # Default to descending for new column
            self._update_table_headers(table, self.history_sort_column, self.history_sort_reverse)
            self.update_history_table()

def run_tui():
    import argparse
    parser = argparse.ArgumentParser(description="Run the Jules Bot TUI Dashboard.")
    parser.add_argument("--mode", type=str, choices=["trade", "test"], default="test", help="Trading mode to monitor.")
    parser.add_argument("--container-id", type=str, required=True, help="The container ID of the running bot for log streaming.")
    parser.add_argument("--bot-name", type=str, default=os.getenv("BOT_NAME", "jules_bot"), help="The name of the bot to monitor.")
    parser.add_argument("--host-port", type=int, required=True, help="The host port the bot's API is mapped to.")
    args = parser.parse_args()
    app = TUIApp(mode=args.mode, container_id=args.container_id, bot_name=args.bot_name, host_port=args.host_port)
    app.run()

if __name__ == "__main__":
    run_tui()
