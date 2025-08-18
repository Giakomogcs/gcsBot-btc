import json
import subprocess
import sys
import os
from decimal import Decimal
import time

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.widgets import Header, Footer, DataTable, Input, Button, Label, Static, RichLog, ProgressBar
from textual.validation import Validator, ValidationResult
from textual.worker import Worker, get_current_worker
from textual import work
from textual.message import Message # NOVO

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

# NOVO: Mensagens personalizadas para comunicação entre workers e a UI
class DashboardData(Message):
    """Uma mensagem para transportar dados do dashboard."""
    def __init__(self, data: dict | str, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

class CommandOutput(Message):
    """Uma mensagem para transportar a saída de um comando."""
    def __init__(self, output: str, success: bool) -> None:
        self.output = output
        self.success = success
        super().__init__()

class PortfolioData(Message):
    """A message to transport portfolio evolution data."""
    def __init__(self, data: dict | str, success: bool) -> None:
        self.data = data
        self.success = success
        super().__init__()

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
    #middle_pane {
        width: 45%;
        padding: 1;
        border-right: solid $accent;
    }
    #right_pane {
        width: 25%;
        padding: 1;
    }
    .title {
        background: $accent;
        color: $text;
        width: 100%;
        padding: 0 1;
        margin-top: 1;
    }
    #status_container, #strategy_container {
        layout: grid;
        grid-gutter: 1;
        height: auto;
    }
    #status_container {
        grid-size: 3;
    }
    #strategy_container {
        grid-size: 2;
    }
    #positions_table {
        margin-top: 1;
        height: 20;
    }
    #log_display {
        height: 1fr;
    }
    #chart_container {
        height: 12;
        border: round $primary;
        padding: 0 1;
    }
    #action_bar, #log_filter_bar {
        margin-top: 1;
        height: auto;
        align: right middle;
    }
    .hidden {
        display: none;
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
                yield Static("Bot Control", classes="title")
                yield Label("Manual Buy (USD):")
                yield Input(placeholder="e.g., 50.00", id="manual_buy_input", validators=[NumberValidator()])
                with Horizontal():
                    yield Button("FORCE BUY", id="force_buy_button", variant="primary")
                    yield Button("Sell 100%", id="force_sell_100_button", variant="error", disabled=True)
                    yield Button("Sell 90%", id="force_sell_90_button", variant="warning", disabled=True)

                yield Static("Live Log", classes="title")
                with Horizontal(id="log_filter_bar"):
                    yield Label("Filter:", id="log_filter_label")
                    yield Input(placeholder="e.g., ERROR", id="log_filter_input")
                yield RichLog(id="log_display", wrap=True, markup=True, min_width=0)

            with VerticalScroll(id="middle_pane"):
                yield Static("Bot Status", classes="title")
                with Static(id="status_container"):
                    yield Static(f"Mode: {self.mode.upper()}", id="status_mode")
                    yield Static("Symbol: N/A", id="status_symbol")
                    yield Static("BTC Price: N/A", id="status_price")
                    yield Static("BTC: N/A", id="status_btc")
                    yield Static("USD: N/A", id="status_usdt")
                    yield Static("Wallet: N/A", id="status_wallet_usd")

                yield Static("Strategy Status", classes="title")
                with Static(id="strategy_container"):
                    yield Static("Current Price: N/A", id="strategy_current_price")
                    yield Static("Buy Signal: N/A", id="strategy_buy_signal")
                    yield Static("Buy Target: N/A", id="strategy_buy_target")
                    yield Static("Buy Progress: N/A", id="strategy_buy_progress")

                yield Static("Open Positions", classes="title")
                yield DataTable(id="positions_table")

            with VerticalScroll(id="right_pane"):
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

        yield Footer()

    def on_mount(self) -> None:
        self.log_display = self.query_one(RichLog)
        self.log_display.write("[bold green]TUI Initialized.[/bold green]")

        positions_table = self.query_one("#positions_table", DataTable)
        positions_table.cursor_type = "row"
        positions_table.add_columns("ID", "Entry", "Value", "PnL", "Sell Target", "Target Status")


        # MODIFICADO: Chama o update_dashboard uma vez e depois define o intervalo de 30s
        self.update_dashboard()
        self.set_interval(30.0, self.update_dashboard) # Atualiza a cada 30 segundos

        self.update_portfolio_dashboard()
        self.set_interval(60.0, self.update_portfolio_dashboard) # Update portfolio every 60 seconds

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

            # MODIFICADO: Usa um método para checar se o worker deve parar
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

    # --- Workers & Background Tasks ---

    @work(thread=True)
    def run_script_worker(self, command: list[str], message_type: type[Message]) -> None:
        """
        Executa um script de longa duração em um 'worker' para não bloquear a UI.
        Isso é crucial para a responsividade do dashboard. O worker executa a tarefa
        em um thread separado e, quando concluído, posta uma 'Message' com o resultado.
        A UI principal então lida com essa mensagem em seu próprio thread.
        """
        self.log_display.write(f"Executing: [yellow]{' '.join(command)}[/]")
        try:
            # Executa o subprocesso de forma robusta e compatível com Windows/Linux.
            # - `encoding='utf-8'`: Garante que o output seja lido como UTF-8.
            # - `errors='replace'`: Previne falhas se o script gerar caracteres inválidos.
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
                # `call_from_thread` é necessário para atualizar widgets de um worker.
                self.call_from_thread(self.log_display.write, f"[bold red]Script Error:[/bold red] {output}")
            else:
                output = process.stdout.strip()
                success = True
            
            # Tenta decodificar o JSON, se falhar, envia como texto bruto.
            try:
                data = json.loads(output)
                self.post_message(message_type(data, success))
            except (json.JSONDecodeError, TypeError):
                self.post_message(message_type(output, success))

        except FileNotFoundError:
            self.post_message(message_type("Script not found", False))
            self.call_from_thread(self.log_display.write, f"[bold red]Error: Script not found.[/bold red]")

    # MODIFICADO: on_button_pressed agora chama um worker em vez de executar o script diretamente
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Lida com cliques de botão de forma não-bloqueante."""
        if event.button.id == "force_buy_button":
            input_widget = self.query_one("#manual_buy_input", Input)
            if not input_widget.is_valid:
                self.log_display.write("[bold red]Invalid buy amount.[/bold red]")
                return
            amount = input_widget.value
            command = ["python", "scripts/force_buy.py", amount]
            self.run_script_worker(command, CommandOutput) # Executa em segundo plano
            input_widget.value = ""

        elif event.button.id in ["force_sell_100_button", "force_sell_90_button"]:
            if not self.selected_trade_id:
                self.log_display.write("[bold red]No trade selected for selling.[/bold red]")
                return

            percentage = "100" if event.button.id == "force_sell_100_button" else "90"
            command = ["python", "scripts/force_sell.py", self.selected_trade_id, percentage]
            self.run_script_worker(command, CommandOutput) # Executa em segundo plano

            self.query_one("#force_sell_100_button").disabled = True
            self.query_one("#force_sell_90_button").disabled = True
            self.query_one("#positions_table").move_cursor(row=-1)
            self.selected_trade_id = None

    def on_click(self, event) -> None:
        # If the click is not on the datatable, deselect row and disable buttons
        try:
            if not self.query_one("#positions_table").hit(event.x, event.y):
                self.query_one("#force_sell_100_button").disabled = True
                self.query_one("#force_sell_90_button").disabled = True
                self.query_one("#positions_table").cursor_type = 'row'
                self.query_one("#positions_table").move_cursor(row=-1, animate=True)
                self.selected_trade_id = None
        except Exception:
            pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control.id == "positions_table":
            self.selected_trade_id = event.row_key.value
            self.query_one("#force_sell_100_button").disabled = False
            self.query_one("#force_sell_90_button").disabled = False
    
    # MODIFICADO: update_dashboard agora chama um worker
    def update_dashboard(self) -> None:
        """Inicia a atualização do dashboard em um worker."""
        command = ["python", "scripts/get_bot_data.py", self.mode]
        self.run_script_worker(command, DashboardData)

    def update_portfolio_dashboard(self) -> None:
        """Initiates the portfolio dashboard update in a worker."""
        command = ["python", "scripts/get_portfolio_data.py"]
        self.run_script_worker(command, PortfolioData)

    # NOVO: Handler para a mensagem DashboardData, que atualiza a UI
    def on_dashboard_data(self, message: DashboardData) -> None:
        """Atualiza a UI com os dados recebidos do worker."""
        if not message.success or not isinstance(message.data, dict):
            self.log_display.write(f"[bold red]Failed to get dashboard data: {message.data}[/]")
            return
        
        data = message.data
        
        # Update status bar
        price = Decimal(data.get("current_btc_price", 0))
        self.query_one("#status_symbol").update(f"Symbol: {data.get('symbol', 'N/A')}")
        self.query_one("#status_price").update(f"Price: ${price:,.2f}")
        self.query_one("#strategy_current_price").update(f"Current Price: ${price:,.2f}")

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
                
                progress_pct = float(pos.get("progress_to_sell_target_pct", 0))
                # price_to_target = Decimal(pos.get("price_to_target", 0))
                usd_to_target = Decimal(pos.get("usd_to_target", 0))
                
                pnl_color = "green" if pnl >= 0 else "red"
                
                # Format the progress to be more informative
                progress_text = f"{progress_pct:.1f}% (${usd_to_target:,.2f})"

                pos_table.add_row(
                    pos_id.split('-')[0],
                    f"${entry_price:,.2f}",
                    f"${current_value:,.2f}",
                    f"[{pnl_color}]${pnl:,.2f}[/]",
                    f"${sell_target:,.2f}",
                    progress_text,
                    key=pos_id,
                )
        else:
            pos_table.add_row("No open positions.")

        # Update wallet balances in status bar
        balances = data.get("wallet_balances", [])
        btc_balance = next((bal for bal in balances if bal.get("asset") == "BTC"), None)
        usdt_balance = next((bal for bal in balances if bal.get("asset") == "USDT"), None)
        total_wallet_usd = Decimal(data.get("total_wallet_usd_value", 0))

        if btc_balance:
            free_btc = Decimal(btc_balance.get("free", 0))
            usd_value_btc = Decimal(btc_balance.get("usd_value", 0))
            self.query_one("#status_btc").update(f"BTC: {free_btc:.8f} (${usd_value_btc:,.2f})")
        else:
            self.query_one("#status_btc").update("BTC: N/A")

        if usdt_balance:
            free_usdt = Decimal(usdt_balance.get("free", 0))
            self.query_one("#status_usdt").update(f"USD: ${free_usdt:,.2f}")
        else:
            self.query_one("#status_usdt").update("USD: N/A")
            
        self.query_one("#status_wallet_usd").update(f"Wallet: ${total_wallet_usd:,.2f}")

        # Update strategy status
        buy_signal_status = data.get("buy_signal_status", {})
        should_buy = buy_signal_status.get("should_buy", False)
        reason = buy_signal_status.get("reason", "N/A")
        buy_target = Decimal(buy_signal_status.get("btc_purchase_target", 0))
        buy_progress = float(buy_signal_status.get("btc_purchase_progress_pct", 0))

        buy_signal_text = f"Buy Signal: {'YES' if should_buy else 'NO'} ({reason})"
        buy_target_text = f"Buy Target: ${buy_target:,.2f}"
        buy_progress_text = f"Buy Progress: {buy_progress:.1f}%"
        
        self.query_one("#strategy_buy_signal").update(buy_signal_text)
        self.query_one("#strategy_buy_target").update(buy_target_text)
        self.query_one("#strategy_buy_progress").update(buy_progress_text)

    def _render_text_chart(self, history: list[dict], width: int = 50, height: int = 10) -> str:
        """Renders a simple text-based bar chart from portfolio history."""
        if not history:
            return "[dim]Not enough data to render chart.[/dim]"

        values = [Decimal(item['value']) for item in history]

        # Sample data to fit the specified width
        if len(values) > width:
            indices = [int(i * (len(values) - 1) / (width - 1)) for i in range(width)]
            sampled_values = [values[i] for i in indices]
        else:
            sampled_values = values
            width = len(sampled_values)

        if not sampled_values or width == 0:
            return "[dim]Not enough data to render chart.[/dim]"

        min_val = min(sampled_values)
        max_val = max(sampled_values)
        value_range = max_val - min_val

        # Initialize grid
        grid = [[' '] * width for _ in range(height)]

        # Populate grid with bars
        if value_range > 0:
            for i, value in enumerate(sampled_values):
                # Normalize value to the height of the chart
                bar_height = int(((value - min_val) / value_range) * (height - 1))
                for j in range(bar_height + 1):
                    grid[height - 1 - j][i] = '█'
        else:  # If all values are the same, draw a flat line
            mid_line = height // 2
            for i in range(width):
                grid[mid_line][i] = '█'

        # Convert grid to a list of strings and add a title
        lines = ["".join(row) for row in grid]
        top_label = f"Portfolio Value (Range: ${min_val:,.2f} - ${max_val:,.2f})"

        return f"{top_label}\n" + "\n".join(lines)

    def on_portfolio_data(self, message: PortfolioData) -> None:
        """Updates the TUI with portfolio evolution data."""
        if not message.success or not isinstance(message.data, dict):
            self.log_display.write(f"[bold red]Failed to get portfolio data: {message.data}[/]")
            return

        data = message.data
        snapshot = data.get("latest_snapshot")

        if snapshot:
            total_value = Decimal(snapshot.get("total_portfolio_value_usd", "0"))
            realized_pnl = Decimal(snapshot.get("realized_pnl_usd", "0"))
            btc_treasury_amount = Decimal(snapshot.get("btc_treasury_amount", "0"))
            btc_treasury_value = Decimal(snapshot.get("btc_treasury_value_usd", "0"))

            self.query_one("#portfolio_total_value").update(f"Total Portfolio Value: ${total_value:,.2f} USD")
            self.query_one("#portfolio_realized_pnl").update(f"Realized Profit/Loss: ${realized_pnl:,.2f} USD")
            self.query_one("#portfolio_btc_treasury").update(f"BTC Treasury: ₿{btc_treasury_amount:.8f} (${btc_treasury_value:,.2f} USD)")

        evolution_total = Decimal(data.get("evolution_total", "0"))
        evolution_24h = Decimal(data.get("evolution_24h", "0"))

        self.query_one("#portfolio_evolution_total").update(f"Evolution (Total): {evolution_total:+.2f}%")
        self.query_one("#portfolio_evolution_24h").update(f"Evolution (24h): {evolution_24h:+.2f}%")
        self.query_one("#portfolio_accumulated_btc").update("Accumulated BTC: +0.0%") # Placeholder

        # --- DCOM Status Panel Update ---
        dcom_status = data.get("dcom_status", {})
        if dcom_status:
            total_equity = Decimal(dcom_status.get("total_equity", "0"))
            wc_target = Decimal(dcom_status.get("working_capital_target", "0"))
            wc_in_use = Decimal(dcom_status.get("working_capital_in_use", "0"))
            wc_remaining = Decimal(dcom_status.get("working_capital_remaining", "0"))
            reserve = Decimal(dcom_status.get("strategic_reserve", "0"))
            mode = dcom_status.get("operating_mode", "N/A")

            self.query_one("#dcom_total_equity").update(f"Total Equity: ${total_equity:,.2f}")
            wc_text = f"Working Capital: ${wc_target:,.2f} | Used: ${wc_in_use:,.2f} | Free: ${wc_remaining:,.2f}"
            self.query_one("#dcom_working_capital").update(wc_text)
            self.query_one("#dcom_strategic_reserve").update(f"Strategic Reserve: ${reserve:,.2f}")
            self.query_one("#dcom_operating_mode").update(f"Operating Mode: {mode}")

        # Update the chart
        history = data.get("history", [])
        if history:
            chart_str = self._render_text_chart(history)
            self.query_one("#portfolio_chart").update(chart_str)
        else:
            self.query_one("#portfolio_chart").update("[dim]No portfolio history available.[/dim]")


    # NOVO: Handler para a mensagem CommandOutput (opcional, mas bom para feedback)
    def on_command_output(self, message: CommandOutput) -> None:
        """Exibe o resultado de um comando no log."""
        if message.success:
            self.log_display.write(f"[green]Command success:[/green] {message.output}")
        else:
            self.log_display.write(f"[bold red]Command failed:[/bold red] {message.output}")
        # Aciona uma atualização do dashboard para vermos o resultado da ação
        self.update_dashboard()

def run_tui():
    """Ponto de entrada da linha de comando para a TUI."""
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