import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.config_manager import config_manager

class StateManager:
    def __init__(self, bucket_name: str, bot_id: str):
        self.bucket_name = bucket_name
        self.bot_id = bot_id
        # Get the base DB configuration from the environment
        db_config = config_manager.get_db_config()
        # Add the specific bucket for this instance
        db_config['bucket'] = self.bucket_name
        self.db_manager = DatabaseManager(config=db_config)
        logger.info(f"StateManager initialized for bucket: {self.bucket_name}, bot_id: {self.bot_id}")

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
        Records a new open position in the database.
        """
        logger.info(f"Creating new position for trade_id: {buy_result.get('trade_id')} with target sell price: {sell_target_price}")

        from jules_bot.core.schemas import TradePoint

        try:
            trade_point = TradePoint(
                run_id=self.bot_id,
                environment=buy_result.get('environment', 'backtest'),
                strategy_name=buy_result.get('strategy_name', 'default'),
                symbol=buy_result['symbol'],
                trade_id=buy_result['trade_id'],
                exchange=buy_result.get('exchange', 'simulated'),
                order_type='buy',
                status='OPEN',
                price=buy_result['price'],
                quantity=buy_result['quantity'],
                usd_value=buy_result['usd_value'],
                commission=buy_result.get('commission', 0.0),
                commission_asset=buy_result.get('commission_asset', 'USDT'),
                exchange_order_id=buy_result.get('exchange_order_id'),
                sell_target_price=sell_target_price  # Pass the pre-calculated target price
            )
            self.db_manager.log_trade(trade_point)
        except KeyError as e:
            logger.error(f"Missing essential key in buy_result to create TradePoint: {e}")
        except Exception as e:
            logger.error(f"Failed to create or log TradePoint: {e}")

    def close_position(self, trade_id: str, exit_data: dict):
        """
        Logs the closing part of a trade using the TradePoint schema.
        """
        from jules_bot.core.schemas import TradePoint

        try:
            trade_point = TradePoint(
                run_id=self.bot_id,
                environment=exit_data.get('environment', 'backtest'),
                strategy_name=exit_data.get('strategy_name', 'default'),
                symbol=exit_data['symbol'],
                trade_id=trade_id, # The ID of the trade being closed
                exchange=exit_data.get('exchange', 'simulated'),
                order_type='sell',
                status='CLOSED',
                price=exit_data['price'],
                quantity=exit_data['quantity'],
                usd_value=exit_data['usd_value'],
                commission=exit_data.get('commission', 0.0),
                commission_asset=exit_data.get('commission_asset', 'USDT'),
                exchange_order_id=exit_data.get('exchange_order_id'),
                realized_pnl=exit_data.get('realized_pnl')
            )
            self.db_manager.log_trade(trade_point)
        except KeyError as e:
            logger.error(f"Missing essential key in exit_data to create TradePoint: {e}")
        except Exception as e:
            logger.error(f"Failed to create or log closing TradePoint: {e}")
