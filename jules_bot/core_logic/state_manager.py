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

        # This function is now a passthrough and should be refactored.
        # For now, we adapt it to call the new log_trade function.
        # The logic for calculating sell_target_price should be moved to the bot/strategy itself.

        from jules_bot.core.schemas import TradePoint

        # The bot_id is not part of the TradePoint schema. It is used for status, not individual trades.
        # We now create a TradePoint object to enforce the schema.
        try:
            trade_point = TradePoint(
                mode=buy_result.get('mode', 'backtest'), # Assume backtest if not provided
                strategy_name=buy_result.get('strategy_name', 'default'),
                symbol=buy_result['symbol'],
                trade_id=buy_result['trade_id'],
                exchange=buy_result.get('exchange', 'simulated'),
                order_type='buy',
                price=buy_result['price'],
                quantity=buy_result['quantity'],
                usd_value=buy_result['usd_value'],
                commission=buy_result.get('commission', 0.0),
                commission_asset=buy_result.get('commission_asset', 'USDT'),
                exchange_order_id=buy_result.get('exchange_order_id')
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
                mode=exit_data.get('mode', 'backtest'),
                strategy_name=exit_data.get('strategy_name', 'default'),
                symbol=exit_data['symbol'],
                trade_id=trade_id, # The ID of the trade being closed
                exchange=exit_data.get('exchange', 'simulated'),
                order_type='sell',
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
