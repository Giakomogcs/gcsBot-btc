import sys
import os
from multiprocessing import Process, Queue
from queue import Empty

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ProgressBar, Log
from textual.timer import Timer

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from jules_bot.backtesting.engine import run_backtest
from jules_bot.utils.config_manager import settings

class JulesBotApp(App):
    """A Textual app to manage and display the trading bot's status."""

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]

    def __init__(self, config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = config
        self.ipc_queue = Queue()
        self.backtest_process = None
        self.check_queue_timer: Timer = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Log(id="log_widget", wrap=True)
        yield ProgressBar(id="progress_bar", total=1.0)
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is first mounted."""
        log_widget = self.query_one(Log)
        log_widget.write_line("UI Mounted. Checking execution mode...")
        if self.config.app.execution_mode == 'backtest':
            log_widget.write_line("Execution mode is 'backtest'. Starting backtest process...")
            self.start_backtest()
        else:
            log_widget.write_line(f"Execution mode is '{self.config.app.execution_mode}'. No UI action taken.")

    def start_backtest(self) -> None:
        """Initializes and starts the backtest worker process."""
        log_widget = self.query_one(Log)
        try:
            self.backtest_process = Process(
                target=run_backtest,
                args=(self.ipc_queue, self.config)
            )
            self.backtest_process.start()
            log_widget.write_line("Backtest process started.")
            # Set a timer to call self.check_queue every 100ms
            self.check_queue_timer = self.set_interval(0.1, self.check_queue, pause=False)
        except Exception as e:
            log_widget.write_line(f"Failed to start backtest process: {e}")

    def check_queue(self) -> None:
        """Polls the IPC queue for messages from the backtest worker."""
        try:
            message = self.ipc_queue.get_nowait()
            self.process_message(message)
        except Empty:
            # This is normal, just means no new messages.
            pass

    def process_message(self, message: dict) -> None:
        """Updates UI widgets based on the message from the worker."""
        msg_type = message.get('type')
        log_widget = self.query_one(Log)

        if msg_type == 'progress':
            progress_bar = self.query_one(ProgressBar)
            progress_bar.update(progress=message.get('value', 0))
        elif msg_type == 'log':
            log_widget.write_line(message.get('message', ''))
        elif msg_type == 'new_closed_trade':
            trade_data = message.get('data', {})
            log_widget.write_line(f"[TRADE] PNL: ${trade_data.get('pnl_usdt', 0):.2f}, Reason: {trade_data.get('exit_reason', 'N/A')}")
        elif msg_type == 'error':
            log_widget.write_line(f"[ERROR] {message.get('message', 'Unknown error')}")
            if self.check_queue_timer:
                self.check_queue_timer.pause()
        elif msg_type == 'finished':
            if self.check_queue_timer:
                self.check_queue_timer.pause()
            final_data = message.get('data', {})
            log_widget.write_line("--- BACKTEST FINISHED ---")
            for key, value in final_data.items():
                if isinstance(value, float):
                    log_widget.write_line(f"{key.replace('_', ' ').title()}: {value:,.4f}")
                else:
                    log_widget.write_line(f"{key.replace('_', ' ').title()}: {value}")
            log_widget.write_line("Press Ctrl+C to exit.")

    def action_toggle_dark(self) -> None:
        """An action to toggle dark mode."""
        self.dark = not self.dark

if __name__ == '__main__':
    # This allows running the UI directly for testing,
    # but it should be launched from main.py or a script.
    app = JulesBotApp(config=settings)
    app.run()
