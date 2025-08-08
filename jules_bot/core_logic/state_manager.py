import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.config_manager import config_manager

class StateManager:
    def __init__(self, bucket_name: str, bot_id: str):
        self.bucket_name = bucket_name
        self.bot_id = bot_id
        db_config = config_manager.get_section('INFLUXDB')
        db_config['bucket'] = self.bucket_name
        db_config['url'] = f"http://{db_config['host']}:{db_config['port']}"
        self.db_manager = DatabaseManager(config=db_config)
        logger.info(f"StateManager initialized for bucket: {self.bucket_name}, bot_id: {self.bot_id}")

    def get_open_positions(self) -> list[dict]:
        """Fetches all trades marked as 'OPEN' from the database for the current bot."""
        return self.db_manager.get_open_positions(bot_id=self.bot_id)

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

    def get_last_purchase_price(self) -> float:
        """
        Retrieves the purchase price of the most recent 'OPEN' trade.
        Returns a default high price if no open trades are found.
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return float('inf')

        # In a robust system, the query itself should order by time
        last_position = sorted(open_positions, key=lambda p: p['time'], reverse=True)[0]
        return last_position.get('purchase_price', float('inf'))

    def create_new_position(self, buy_result: dict):
        """
        Calculates the target sell price and records a new open position in the database.
        """
        logger.info(f"Attempting to create new position from buy result: {buy_result}")

        commission_rate = float(config_manager.get('STRATEGY_RULES', 'commission_rate'))
        sell_factor = float(config_manager.get('STRATEGY_RULES', 'sell_factor'))
        target_profit = float(config_manager.get('STRATEGY_RULES', 'target_profit'))

        purchase_price = buy_result['price']

        # Formula Implementation
        numerator = purchase_price * (1 + commission_rate)
        denominator = sell_factor * (1 - commission_rate)

        if denominator == 0:
            logger.error("Denominator is zero in sell target price calculation. Aborting.")
            return

        break_even_price = numerator / denominator
        sell_target_price = break_even_price * (1 + target_profit)

        logger.info(f"Calculated sell_target_price: {sell_target_price} for purchase_price: {purchase_price}")

        trade_data = {
            **buy_result,
            'sell_target_price': sell_target_price,
            'bot_id': self.bot_id
        }
        self.db_manager.write_trade(trade_data)

    def close_position(self, trade_id: str, exit_data: dict):
        """Updates an existing trade record to mark it as 'CLOSED' and adds exit data."""
        self.db_manager.update_trade_status(trade_id, exit_data)
