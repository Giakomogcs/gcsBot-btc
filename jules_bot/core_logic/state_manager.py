import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
import uuid
from jules_bot.utils.config_manager import config_manager
from jules_bot.services.trade_logger import TradeLogger
from jules_bot.bot.account_manager import AccountManager
from jules_bot.core_logic.strategy_rules import StrategyRules

class StateManager:
    def __init__(self, mode: str, bot_id: str):
        self.mode = mode
        self.bot_id = bot_id

        # This DB manager is for READING operations (get_open_positions, etc.)
        db_config = config_manager.get_db_config('POSTGRES')
        self.db_manager = PostgresManager(config=db_config)

        # The TradeLogger is now responsible for ALL WRITE operations.
        self.trade_logger = TradeLogger(mode=self.mode)

        logger.info(f"StateManager initialized for mode: '{self.mode}', bot_id: '{self.bot_id}'")

    def get_open_positions(self) -> list:
        """
        Fetches all trades marked as 'OPEN' for the current environment.
        For backtesting, it also filters by bot_id.
        """
        bot_id_to_filter = None
        if self.mode == 'backtest':
            bot_id_to_filter = self.bot_id
        
        return self.db_manager.get_open_positions(environment=self.mode, bot_id=bot_id_to_filter)

    def get_open_positions_count(self) -> int:
        """Queries the database and returns the number of currently open trades."""
        return len(self.get_open_positions())

    def get_trade_history(self, mode: str) -> list[dict]:
        """Fetches all trades (open and closed) from the database for the given mode."""
        # Note: The date range parameters are omitted to use the default values,
        # effectively fetching all trades for the given mode.
        return self.db_manager.get_all_trades_in_range(mode=mode)

    def get_last_purchase_price(self) -> float:
        """
        Retrieves the purchase price of the most recent 'buy' trade.
        Returns float('inf') if no open positions are found.
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return float('inf')

        # Sort by time to find the most recent position.
        # The returned objects are SQLAlchemy models, so we use attribute access.
        latest_position = sorted(open_positions, key=lambda p: p.timestamp, reverse=True)[0]
        
        # The field for price is 'price'.
        return latest_position.price

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

    def sync_trades_with_binance(self, account_manager: AccountManager, strategy_rules: StrategyRules):
        """
        Syncs historical trades from Binance with the local database and handles open positions.
        """
        logger.info("--- Starting trade synchronization with Binance ---")
        symbol = config_manager.get('APP', 'symbol')
        last_trade_id = self.db_manager.get_last_trade_id(self.mode)

        new_trades = account_manager.get_all_my_trades(symbol, from_id=last_trade_id + 1)

        if not new_trades:
            logger.info("No new trades to sync.")
            return

        logger.info(f"Found {len(new_trades)} new trades to sync.")

        # Group trades by orderId to identify open positions
        orders = {}
        for trade in new_trades:
            order_id = trade['orderId']
            if order_id not in orders:
                orders[order_id] = []
            orders[order_id].append(trade)

        for order_id, trades_in_order in orders.items():
            is_buy_order = all(t['isBuyer'] for t in trades_in_order)

            # This is a simplified assumption. A robust implementation would check if the total quantity bought
            # has been sold in other orders. For now, we assume one order per position.
            if is_buy_order:
                # This is an open position
                # We'll use the first trade in the order to represent the position
                buy_trade = trades_in_order[0]
                purchase_price = float(buy_trade['price'])
                sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)

                trade_data = {
                    'run_id': self.bot_id,
                    'symbol': buy_trade['symbol'],
                    'trade_id': str(uuid.uuid4()),
                    'exchange': 'binance',
                    'status': 'OPEN',
                    'order_type': 'buy',
                    'price': purchase_price,
                    'quantity': sum(float(t['qty']) for t in trades_in_order),
                    'usd_value': sum(float(t['price']) * float(t['qty']) for t in trades_in_order),
                    'commission': sum(float(t.get('commission', 0.0)) for t in trades_in_order),
                    'commission_asset': trades_in_order[0].get('commissionAsset'),
                    'timestamp': trades_in_order[0]['time'],
                    'exchange_order_id': str(order_id),
                    'binance_trade_id': trades_in_order[0]['id'],
                    'sell_target_price': sell_target_price,
                    'decision_context': {'source': 'sync', 'reason': 'open_position'}
                }
                
                # Check for duplicates before logging
                existing_trade = self.db_manager.get_trade_by_binance_trade_id(trade_data['binance_trade_id'])
                if existing_trade:
                    logger.info(f"Skipping duplicate trade with binance_trade_id {trade_data['binance_trade_id']}")
                else:
                    self.trade_logger.log_trade(trade_data)
            else:
                # This is a sell order or a mixed order, log all trades as closed
                for trade in trades_in_order:
                    trade_data = {
                        'run_id': self.bot_id,
                        'symbol': trade['symbol'],
                        'trade_id': str(uuid.uuid4()),
                        'exchange': 'binance',
                        'status': 'CLOSED',
                        'order_type': 'buy' if trade['isBuyer'] else 'sell',
                        'price': float(trade['price']),
                        'quantity': float(trade['qty']),
                        'usd_value': float(trade['price']) * float(trade['qty']),
                        'commission': float(trade.get('commission', 0.0)),
                        'commission_asset': trade.get('commissionAsset'),
                        'timestamp': trade['time'],
                        'exchange_order_id': str(trade['orderId']),
                        'binance_trade_id': trade['id'],
                        'decision_context': {'source': 'sync'}
                    }
                    
                    # Check for duplicates before logging
                    existing_trade = self.db_manager.get_trade_by_binance_trade_id(trade_data['binance_trade_id'])
                    if existing_trade:
                        logger.info(f"Skipping duplicate trade with binance_trade_id {trade_data['binance_trade_id']}")
                    else:
                        self.trade_logger.log_trade(trade_data)

        logger.info("--- Trade synchronization finished ---")

    def record_partial_sell(self, original_trade_id: str, remaining_quantity: float, sell_data: dict):
        """
        Records a partial sell. This involves two steps:
        1. Logging the sell transaction as a new, separate, 'CLOSED' trade record.
        2. Updating the original 'OPEN' buy position to reflect the new, reduced quantity.
        """
        # Step 1: Log the sell transaction as a new record.
        # To ensure it's a new record, we generate a new UUID for this sell transaction.
        sell_trade_id = str(uuid.uuid4())
        logger.info(f"Logging partial sell transaction with new trade_id: {sell_trade_id} for original trade: {original_trade_id}")

        sell_trade_data = {
            **sell_data,
            'run_id': self.bot_id,
            'trade_id': sell_trade_id,  # Use the new UUID
            'status': 'CLOSED',         # A sell transaction is a self-contained, closed event
            'order_type': 'sell',
            # Link back to the original trade for better traceability (optional, but good practice)
            'decision_context': {
                **sell_data.get('decision_context', {}),
                'closing_partial_trade_id': original_trade_id
            }
        }
        self.trade_logger.log_trade(sell_trade_data)

        # Step 2: Update the original buy position with the reduced quantity.
        logger.info(f"Updating original position {original_trade_id} with remaining quantity: {remaining_quantity}")
        if remaining_quantity > 0:
            self.db_manager.update_trade_quantity(original_trade_id, remaining_quantity)
        else:
            # If remaining quantity is zero, we should close the original position.
            logger.info(f"Remaining quantity is zero. Closing original position {original_trade_id}.")
            self.close_position(original_trade_id, sell_data, is_partial_close=False)


    def close_position(self, trade_id: str, exit_data: dict, is_partial_close: bool = True):
        """
        Logs the closing of a trade.
        If this is the final closing of a position (not a partial sell), it updates the original record.
        If it's a partial sell, this function is now a legacy path and the new record_partial_sell should be used.
        """
        logger.info(f"Closing position for trade_id: {trade_id}")

        # The original implementation of this function was flawed because it overwrote the buy record
        # with sell information. The new `record_partial_sell` is the correct path for partial sells.
        # This function will now only handle the final closing of a position.

        if is_partial_close:
             # This indicates a logic error - close_position should not be called for partials anymore.
             logger.warning("close_position was called for a partial sell. This is a deprecated path. Please use record_partial_sell.")
             # Fallback to old logic to avoid crashing, but this is not ideal.
             pass

        trade_data = {
            **exit_data,
            'run_id': self.bot_id,
            'trade_id': trade_id,
            'status': 'CLOSED',
            'order_type': 'sell',
            'strategy_name': exit_data.get('strategy_name', 'default'),
            'exchange': exit_data.get('exchange', 'binance')
        }

        self.trade_logger.log_trade(trade_data)
