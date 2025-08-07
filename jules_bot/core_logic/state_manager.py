import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.config_manager import config_manager

class StateManager:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        db_config = config_manager.get_section('INFLUXDB')
        db_config['bucket'] = self.bucket_name
        db_config['url'] = f"http://{db_config['host']}:{db_config['port']}"
        self.db_manager = DatabaseManager(config=db_config)
        logger.info(f"StateManager initialized for bucket: {self.bucket_name}")

    def get_open_positions(self) -> list[dict]:
        """Fetches all trades marked as 'OPEN' from the database."""
        return self.db_manager.get_open_positions(bot_id="jules_bot_main")

    def get_open_positions_count(self) -> int:
        """Queries the database and returns the number of currently open trades."""
        return len(self.get_open_positions())

    def get_total_capital_allocated(self) -> float:
        """Queries all open trades and returns the sum of their initial USDT cost."""
        open_positions = self.get_open_positions()
        total_capital = 0.0
        for position in open_positions:
            total_capital += position.get('usd_value', 0.0)
        return total_capital

    def open_trade(self, trade_data: dict):
        """Writes a new trade with status OPEN to the 'trades' measurement."""
        self.db_manager.open_trade(trade_data)

    def close_trade(self, trade_id: str, exit_data: dict):
        """Updates an existing trade record to mark it as 'CLOSED' and adds exit data."""
        self.db_manager.close_trade(trade_id, exit_data)
