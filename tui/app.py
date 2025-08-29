import json
import subprocess
import sys
import os
from decimal import Decimal, InvalidOperation
import time
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.widgets import Footer, DataTable, Input, Button, Label, Static, RichLog, TabbedContent, TabPane
from textual.validation import Validator, ValidationResult
from textual.worker import Worker, get_current_worker
from textual import work
from textual.message import Message
from textual.reactive import reactive
from textual_plotext import PlotextPlot

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

class PortfolioData(Message):
    def __init__(self, data: dict | str, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

class TradeHistoryData(Message):
    def __init__(self, data: list | dict, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

class StatusIndicator(Static):
    status = reactive("OFF")
    def render(self) -> str:
        colors = {"RUNNING": "green", "ERROR": "red", "STOPPED": "gray", "OFF": "gray"}
        return f"[{colors.get(self.status, 'gray')}]●[/] {self.status}"
    def watch_status(self, new_status: str) -> None:
        self.refresh()

class CustomHeader(Static):
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("GCS Trading Bot Dashboard", id="header_title")
            yield StatusIndicator(id="status_indicator")

class TUIApp(App):
    BINDINGS = [("d", "toggle_dark", "Toggle Dark Mode"), ("q", "quit", "Quit")]
    CSS_PATH = "app.css"

    def __init__(self, mode: str = "test", container_id: str | None = None, bot_name: str = "jules_bot", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.container_id = container_id
        self.selected_trade_id: str | None = None
        self.log_display: RichLog | None = None
        self.bot_name = bot_name
        logger.info(f"TUI is initializing for bot: {self.bot_name} (Container: {self.container_id})")
        config_manager.initialize(self.bot_name)
        self.log_filter = ""
        self.open_positions_data = []
        self.trade_history_data = []
        self.positions_sort_column = "PnL"
        self.positions_sort_reverse = True
        self.history_sort_column = "Timestamp"
        self.history_sort_reverse = True

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
                            with Vertical(id="status_and_strategy"):
                                yield Static(f"Bot Status for {self.bot_name}", classes="title")
                                with Static(id="status_container"):
                                    yield Static(f"Mode: {self.mode.upper()}", id="status_mode")
                                    yield Static("Symbol: N/A", id="status_symbol")
                                    yield Static("Price: N/A", id="status_price")
                                    yield Static("Wallet Value: N/A", id="status_wallet_usd")
                                    yield Static("Total PnL: N/A", id="status_total_pnl")
                                    yield Static("Realized PnL: N/A", id="status_realized_pnl")
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
                        with Vertical(id="open_positions"):
                            yield Static("Open Positions", classes="title")
                            yield DataTable(id="positions_table")
            with TabPane("Trade History", id="history"):
                with Vertical():
                    with Horizontal(id="history_filter_bar"):
                        yield Input(placeholder="Start Date (YYYY-MM-DD)", id="start_date_input")
                        yield Input(placeholder="End Date (YYYY-MM-DD)", id="end_date_input")
                        yield Button("Filter", id="filter_history_button")
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
        positions_table.add_columns("ID", "Entry", "Value", "PnL", "Target", "To Target ($)", "Progress")
        wallet_table = self.query_one("#wallet_table", DataTable)
        wallet_table.add_columns("Asset", "Available", "Total", "USD Value")
        history_table = self.query_one("#history_table", DataTable)
        history_table.cursor_type = "row"
        history_table.add_columns("Timestamp", "Symbol", "Type", "Status", "Buy Price", "Sell Price", "Quantity", "USD Value", "PnL (USD)", "PnL (%)", "Trade ID")
        self.update_dashboard()
        self.set_interval(15.0, self.update_dashboard)
        self.update_portfolio_dashboard()
        self.set_interval(15.0, self.update_portfolio_dashboard)
        self.update_trade_history()
        self.set_interval(15.0, self.update_trade_history)
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
    def run_script_worker(self, command: list[str], message_type: type[Message]) -> None:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        try:
            docker_command = SUDO_PREFIX + ["docker", "run", "--rm", "--network", f"{PROJECT_NAME}-btc_default", "--env-file", ".env", "-e", f"BOT_NAME={self.bot_name}", "-v", f"{project_root}:/app", f"{PROJECT_NAME}-app"] + command
            process = subprocess.run(docker_command, capture_output=True, text=True, check=False, encoding='utf-8', errors='replace')
            output = process.stdout.strip() if process.returncode == 0 else process.stderr.strip()
            success = process.returncode == 0
            if not success:
                self.call_from_thread(self.log_display.write, f"[bold red]Script Error ({command[1]}):[/] {output}")
            try:
                data = json.loads(process.stdout.strip())
                self.post_message(message_type(data, success))
            except (json.JSONDecodeError, TypeError):
                self.post_message(message_type(output, success))
        except FileNotFoundError:
            self.post_message(message_type("Docker not found", False))
        except Exception as e:
            self.post_message(message_type(f"Worker error: {e}", False))

    def update_dashboard(self) -> None:
        self.run_script_worker(["python", "scripts/get_bot_data.py", self.mode], DashboardData)
    def update_portfolio_dashboard(self) -> None:
        self.run_script_worker(["python", "scripts/get_portfolio_data.py"], PortfolioData)
    def update_trade_history(self) -> None:
        start_date = self.query_one("#start_date_input", Input).value
        end_date = self.query_one("#end_date_input", Input).value
        command = ["python", "scripts/get_trade_history.py", self.bot_name]
        if start_date: command.extend(["--start-date", start_date])
        if end_date: command.extend(["--end-date", end_date])
        self.run_script_worker(command, TradeHistoryData)

    def on_dashboard_data(self, message: DashboardData) -> None:
        if not message.success or not isinstance(message.data, dict):
            self.query_one(StatusIndicator).status = "ERROR"
            return
        data = message.data
        self.query_one(StatusIndicator).status = data.get("bot_status", "OFF")
        self.query_one("#header_title").update(f"GCS Trading Bot Dashboard - {self.bot_name}")
        price = Decimal(data.get("current_btc_price", 0))
        self.query_one("#status_symbol").update(f"Symbol: {data.get('symbol', 'N/A')}")
        self.query_one("#status_price").update(f"Price: ${price:,.2f}")
        open_count = data.get('open_positions_count', 0)
        total_count = data.get('total_trades_count', 0)
        self.query_one("#status_positions_count").update(f"Positions: {open_count} Open / {total_count} Total")
        wallet_value = Decimal(data.get('total_wallet_usd_value', 0))
        self.query_one("#status_wallet_usd").update(f"Wallet Value: ${wallet_value:,.2f}")
        realized_pnl = Decimal(data.get("total_realized_pnl", 0))
        net_total_pnl = Decimal(data.get("net_total_pnl", 0))
        realized_color = "green" if realized_pnl >= 0 else "red"
        total_color = "green" if net_total_pnl >= 0 else "red"
        self.query_one("#status_realized_pnl").update(f"Realized PnL: [{realized_color}]${realized_pnl:,.2f}[/]")
        self.query_one("#status_total_pnl").update(f"Total PnL: [{total_color}]${net_total_pnl:,.2f}[/]")
        self.update_strategy_panel(data.get("buy_signal_status", {}), price)
        self.update_wallet_table(data.get("wallet_balances", []))
        self.open_positions_data = data.get("open_positions_status", [])
        self.update_positions_table()

    def on_portfolio_data(self, message: PortfolioData) -> None:
        if not message.success or not isinstance(message.data, dict): return
        self.update_portfolio_chart(message.data.get("history", []))

    def on_trade_history_data(self, message: TradeHistoryData) -> None:
        if not message.success or not isinstance(message.data, list): return
        self.trade_history_data = message.data
        self.update_history_table()

    def update_history_table(self):
        table = self.query_one("#history_table", DataTable)
        scroll_y, cursor_row = table.scroll_y, table.cursor_row
        table.clear()
        if not self.trade_history_data:
            table.add_row("No trade history found.")
            return
        sort_key_map = {"Timestamp": "timestamp", "Buy Price": "price", "Sell Price": "sell_price", "PnL (USD)": "realized_pnl_usd"}
        sort_key = sort_key_map.get(self.history_sort_column, "timestamp")
        def sort_func(trade):
            val = trade.get(sort_key)
            if val is None: return -float('inf') if self.history_sort_reverse else float('inf')
            if sort_key == "timestamp": return val
            try: return Decimal(val)
            except (InvalidOperation, TypeError): return -float('inf') if self.history_sort_reverse else float('inf')
        sorted_history = sorted(self.trade_history_data, key=sort_func, reverse=self.history_sort_reverse)
        for trade in sorted_history:
            pnl = trade.get('realized_pnl_usd')
            order_type = trade.get('order_type', 'N/A')
            pnl_str = f"${Decimal(pnl):,.2f}" if pnl is not None else "N/A"
            pnl_color = "green" if pnl is not None and Decimal(pnl) >= 0 else "red"
            pnl_cell = f"[{pnl_color}]{pnl_str}[/]" if order_type == 'sell' else "N/A"
            type_color = "green" if order_type == 'buy' else "red"
            type_cell = f"[{type_color}]{order_type.upper()}[/]"
            timestamp = datetime.fromisoformat(trade['timestamp']).strftime('%Y-%m-%d %H:%M')
            trade_id_short = trade.get('trade_id', 'N/A').split('-')[0]
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
            table.add_row(timestamp, trade.get('symbol'), type_cell, trade.get('status'), buy_price, sell_price, f"{Decimal(trade.get('quantity', 0)):.8f}", f"${Decimal(trade.get('usd_value', 0)):,.2f}", pnl_cell, pnl_pct_cell if order_type == 'sell' else "N/A", trade_id_short, key=trade.get('trade_id'))
        table.scroll_y = scroll_y
        if cursor_row < len(table.rows): table.cursor_row = cursor_row

    def on_command_output(self, message: CommandOutput) -> None:
        if message.success: self.log_display.write(f"[green]Command success:[/green] {message.output}")
        else: self.log_display.write(f"[bold red]Command failed:[/bold red] {message.output}")
        self.update_dashboard()
        self.update_trade_history()

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
        scroll_y = wallet_table.scroll_y
        wallet_table.clear()
        if not balances:
            wallet_table.add_row("No balance data.")
            return
        for bal in balances:
            asset, free, total, usd_value = bal.get('asset'), Decimal(bal.get('free','0')), Decimal(bal.get('total','0')), Decimal(bal.get('usd_value','0'))
            row_format = "{:,.8f}" if asset == 'BTC' else "{:,.2f}"
            wallet_table.add_row(asset, row_format.format(free), row_format.format(total), f"${usd_value:,.2f}")
        wallet_table.scroll_y = scroll_y

    def update_positions_table(self):
        pos_table = self.query_one("#positions_table", DataTable)
        scroll_y, cursor_row = pos_table.scroll_y, pos_table.cursor_row
        pos_table.clear()
        if not self.open_positions_data:
            pos_table.add_row("No open positions.")
            return
        sort_key_map = {"ID": "trade_id", "Entry": "entry_price", "Value": "current_value", "PnL": "unrealized_pnl", "Target": "sell_target_price"}
        sort_key = sort_key_map.get(self.positions_sort_column, "trade_id")
        for pos in self.open_positions_data:
            pos['current_value'] = Decimal(pos.get('quantity', 0)) * Decimal(pos.get('current_price', 0))
        sorted_positions = sorted(self.open_positions_data, key=lambda p: Decimal(p.get(sort_key, 0)), reverse=self.positions_sort_reverse)
        for pos in sorted_positions:
            pnl = Decimal(pos.get("unrealized_pnl", 0))
            pnl_color = "green" if pnl >= 0 else "red"
            progress = float(pos.get('progress_to_sell_target_pct', 0))
            progress_bar = "█" * int(progress / 10) + "░" * (10 - int(progress / 10))
            progress_str = f"[{progress_bar}] {progress:.1f}%"
            current_value = Decimal(pos.get('quantity', 0)) * Decimal(pos.get('current_price', 0))
            pos_table.add_row(pos.get("trade_id", "N/A").split('-')[0], f"${Decimal(pos.get('entry_price', 0)):,.2f}", f"${current_value:,.2f}", f"[{pnl_color}]${pnl:,.2f}[/]", f"${Decimal(pos.get('sell_target_price', 0)):,.2f}", f"${Decimal(pos.get('usd_to_target', 0)):,.2f}", progress_str, key=pos.get("trade_id"))
        pos_table.scroll_y = scroll_y
        if cursor_row < len(pos_table.rows): pos_table.cursor_row = cursor_row

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
        try:
            log_entry = json.loads(line)
            level, message = log_entry.get("level", "INFO"), log_entry.get("message", "")
            if self.log_filter.lower() in message.lower() or self.log_filter.upper() in level:
                color = {"INFO": "green", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold red"}.get(level, "white")
                self.log_display.write(f"[[{color}]{level}[/{color}]] {message}")
        except json.JSONDecodeError:
            if self.log_filter == "": self.log_display.write(f"[dim]{line.strip()}[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "force_buy_button":
            input_widget = self.query_one("#manual_buy_input", Input)
            if input_widget.is_valid:
                self.run_script_worker(["python", "scripts/force_buy.py", input_widget.value], CommandOutput)
                input_widget.value = ""
            else: self.log_display.write("[bold red]Invalid buy amount.[/bold red]")
        elif event.button.id == "force_sell_button" and self.selected_trade_id:
            self.run_script_worker(["python", "scripts/force_sell.py", self.selected_trade_id, "100"], CommandOutput)
            self.query_one("#force_sell_button").disabled = True
            self.selected_trade_id = None
        elif event.button.id == "filter_history_button":
            self.update_trade_history()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control.id == "positions_table":
            self.selected_trade_id = event.row_key.value
            self.query_one("#force_sell_button").disabled = False

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "log_filter_input":
            self.log_filter = event.value
            self.log_display.clear()
            self.log_display.write("[bold green]Log filter applied. Tailing new logs...[/bold green]")

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        table_id, column_label = event.control.id, event.column_label.plain
        if table_id == "positions_table":
            if self.positions_sort_column == column_label: self.positions_sort_reverse = not self.positions_sort_reverse
            else: self.positions_sort_column, self.positions_sort_reverse = column_label, True
            self.update_positions_table()
        elif table_id == "history_table":
            if self.history_sort_column == column_label: self.history_sort_reverse = not self.history_sort_reverse
            else: self.history_sort_column, self.history_sort_reverse = column_label, True
            self.update_history_table()

def run_tui():
    import argparse
    parser = argparse.ArgumentParser(description="Run the Jules Bot TUI Dashboard.")
    parser.add_argument("--mode", type=str, choices=["trade", "test"], default="test", help="Trading mode to monitor.")
    parser.add_argument("--container-id", type=str, required=True, help="The container ID of the running bot for log streaming.")
    parser.add_argument("--bot-name", type=str, default=os.getenv("BOT_NAME", "jules_bot"), help="The name of the bot to monitor.")
    args = parser.parse_args()
    app = TUIApp(mode=args.mode, container_id=args.container_id, bot_name=args.bot_name)
    app.run()

if __name__ == "__main__":
    run_tui()
