import sys
import multiprocessing
import time
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, DataTable, Log, ProgressBar, Static, TabbedContent

# This is a placeholder for the backtester class
class Backtester:
    def __init__(self, queue):
        self.queue = queue

    def run(self):
        for i in range(101):
            time.sleep(0.05)
            self.queue.put({'type': 'progress', 'value': i / 100.0})
            if i % 10 == 0:
                self.queue.put({'type': 'log', 'message': f"Processed {i} candles."})
            if i % 25 == 0 and i > 0:
                self.queue.put({'type': 'new_trade', 'data': {'id': i, 'pnl': 10.5 * (i/25)}})

        self.queue.put({'type': 'result', 'pnl': 1234.56})
        self.queue.put({'type': 'done'})

class BacktestScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield ProgressBar(total=1.0, id="progress")
        yield Static("P&L: N/A", id="pnl")

        trades_table = DataTable(id="trades")
        trades_table.add_columns("Trade ID", "PnL")
        yield trades_table

        yield Log(id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.1, self.update_ui)

    def update_ui(self) -> None:
        if not self.app.queue.empty():
            message = self.app.queue.get()
            if message['type'] == 'progress':
                self.query_one(ProgressBar).progress = message['value']
            elif message['type'] == 'log':
                self.query_one(Log).write_line(message['message'])
            elif message['type'] == 'new_trade':
                table = self.query_one("#trades")
                trade_data = message['data']
                table.add_row(str(trade_data['id']), f"${trade_data['pnl']:.2f}")
            elif message['type'] == 'result':
                self.query_one("#pnl").update(f"Final P&L: ${message['pnl']:.2f}")
            elif message['type'] == 'done':
                self.app.exit()

class TradeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("KPIs: Portfolio Value: $10000 | Session P&L: +$123.45", id="kpis")

        open_positions_table = DataTable(id="open_positions")
        open_positions_table.add_columns("ID", "Entry", "Qty", "P&L", "Legacy")
        open_positions_table.add_row("123", "50000", "0.1", "+50.0", "False")
        open_positions_table.add_row("456", "48000", "0.2", "-150.0", "True", style="on red")
        yield open_positions_table

        with TabbedContent("Treasury", "Logs"):
            treasury_table = DataTable(id="treasury_trades")
            treasury_table.add_columns("ID", "Entry", "Qty")
            treasury_table.add_row("789", "45000", "0.01")
            yield treasury_table

            log = Log(id="live_log")
            log.write_line("Bot started in live mode.")
            yield log

        yield Footer()

class TUI(App):
    def __init__(self, mode, queue=None):
        super().__init__()
        self.mode = mode
        self.queue = queue

    def on_mount(self) -> None:
        if self.mode == "--backtest":
            self.push_screen(BacktestScreen())
        else:
            self.push_screen(TradeScreen())

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--live"

    queue = multiprocessing.Queue()

    if mode == "--backtest":
        # In a real scenario, we would import the actual Backtester
        # and run it. For now, we use the placeholder.
        backtester = Backtester(queue)
        process = multiprocessing.Process(target=backtester.run)
        process.start()

        app = TUI(mode, queue)
        app.run()

        process.join()
    else:
        app = TUI(mode, queue)
        app.run()
