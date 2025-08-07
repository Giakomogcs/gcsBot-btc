from textual.app import App
from textual.widgets import Header, Footer, DataTable, Static
from jules_bot.database.database_manager import DatabaseManager

class StatusWidget(Static):
    """A widget to display bot status."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.border_title = "Bot Status"

    def update_status(self, status: dict):
        if status:
            self.update(
                f"Bot ID: {status.get('bot_id', 'N/A')}\n"
                f"Is Running: {status.get('is_running', 'N/A')}\n"
                f"Mode: {status.get('mode', 'N/A')}\n"
                f"Open Positions: {status.get('open_positions', 'N/A')}\n"
                f"Portfolio Value (USD): {status.get('portfolio_value_usd', 'N/A')}"
            )
        else:
            self.update("No status data available.")

class JulesBotApp(App):
    def __init__(self, db_manager: DatabaseManager, display_mode: str, **kwargs):
        super().__init__(**kwargs)
        self.db_manager = db_manager
        self.display_mode = display_mode
        self.status_widget = StatusWidget()
        self.history_table = DataTable()

    def compose(self):
        yield Header()
        yield self.status_widget
        yield self.history_table
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Set a timer to refresh the data every few seconds
        self.set_interval(5, self.update_dashboard)
        self.update_dashboard() # Initial update

    def update_dashboard(self) -> None:
        """
        Fetches fresh data from InfluxDB and updates all UI widgets.
        This is the core of the dynamic dashboard.
        """
        if self.display_mode == "trade":
            bot_status = self.db_manager.get_latest_bot_status("jules_bot_main")
            self.status_widget.update_status(bot_status)

        # For both modes, we can show the trade history
        trade_history_df = self.db_manager.get_trade_history("jules_bot_main") # or a backtest_id
        
        self.history_table.clear()
        if not trade_history_df.empty:
            self.history_table.add_columns(*trade_history_df.columns)
            self.history_table.add_rows(trade_history_df.to_records())

        self.screen.refresh()
