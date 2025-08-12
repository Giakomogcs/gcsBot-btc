import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.services.trade_logger import TradeLogger

class StateManager:
    def __init__(self, mode: str, bot_id: str):
        self.mode = mode
        self.bot_id = bot_id
        self.bucket_name = self._get_bucket_for_mode(mode)

        # This DB manager is for READING operations (get_open_positions, etc.)
        db_config = config_manager.get_db_config()
        db_config['bucket'] = self.bucket_name
        self.db_manager = DatabaseManager(config=db_config)

        # The TradeLogger is now responsible for ALL WRITE operations.
        self.trade_logger = TradeLogger(mode=self.mode)

        logger.info(f"StateManager initialized for mode: '{self.mode}', bucket: '{self.bucket_name}', bot_id: '{self.bot_id}'")

    def _get_bucket_for_mode(self, mode: str) -> str:
        """Selects the correct InfluxDB bucket based on the operating mode."""
        if mode == 'trade':
            return config_manager.get('INFLUXDB', 'bucket_live')
        elif mode == 'test':
            return config_manager.get('INFLUXDB', 'bucket_testnet')
        elif mode == 'backtest':
            return config_manager.get('INFLUXDB', 'bucket_backtest')
        else:
            # Fallback or error
            logger.error(f"Invalid mode '{mode}' provided to StateManager. Defaulting to test bucket.")
            return config_manager.get('INFLUXDB', 'bucket_testnet')

    def get_open_positions(self) -> list[dict]:
        """Fetches all trades marked as 'OPEN' from the database for the current bot."""
        return self.db_manager.get_open_positions(bot_id=self.bot_id)

    def get_open_positions_count(self) -> int:
        """Queries the database and returns the number of currently open trades."""
        return len(self.get_open_positions())

    def get_trade_history(self, mode: str) -> list[dict]:
        """Fetches all trades (open and closed) from the database for the given mode."""
        return self.db_manager.get_all_trades_by_mode(mode=mode)

    def get_last_purchase_price(self) -> float:
        """
        Retrieves the purchase price of the most recent 'buy' trade.
        Returns float('inf') if no open positions are found.
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return float('inf')

        # Sort by time to find the most recent position.
        # The field name for time in the dictionary from InfluxDB is '_time'.
        latest_position = sorted(open_positions, key=lambda p: p['_time'], reverse=True)[0]
        
        # The field for price is 'price'.
        return latest_position.get('price', float('inf'))

    def create_new_position(self, buy_result: dict, sell_target_price: float):
        """
        Records a new open position in the database via the TradeLogger service.
        """
        logger.info(f"Creating new position for trade_id: {buy_result.get('trade_id')} with target sell price: {sell_target_price}")

        # This dictionary flattens all the necessary data for the TradeLogger.
        # The TradeLogger is responsible for creating the TradePoint and ensuring type safety.
        trade_data = {
            **buy_result,  # Unpack the raw buy result dictionary
            'run_id': self.bot_id,
            'status': 'OPEN',
            'order_type': 'buy',
            'sell_target_price': sell_target_price,
            'strategy_name': buy_result.get('strategy_name', 'default'),
            'exchange': buy_result.get('exchange', 'binance')
        }

        self.trade_logger.log_trade(trade_data)

    def close_position(self, trade_id: str, exit_data: dict):
        """
        Logs the closing of a trade via the TradeLogger service.
        """
        logger.info(f"Closing position for trade_id: {trade_id}")

        # This dictionary flattens all the necessary data for the TradeLogger.
        trade_data = {
            **exit_data, # Unpack the raw exit data dictionary
            'run_id': self.bot_id,
            'trade_id': trade_id, # Ensure the original trade_id is used
            'status': 'CLOSED',
            'order_type': 'sell',
            'strategy_name': exit_data.get('strategy_name', 'default'),
            'exchange': exit_data.get('exchange', 'binance')
        }

        self.trade_logger.log_trade(trade_data)
