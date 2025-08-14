import pandas as pd
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
import uuid
from jules_bot.utils.config_manager import config_manager
from jules_bot.services.trade_logger import TradeLogger
from jules_bot.bot.account_manager import AccountManager
from jules_bot.core_logic.strategy_rules import StrategyRules
import datetime

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

    def sync_holdings_with_binance(self, account_manager: AccountManager, strategy_rules: StrategyRules):
        """
        Synchronizes the database with current Binance holdings by checking for discrepancies.
        It closes local 'OPEN' positions that no longer exist on the exchange.
        It also logs warnings for assets held on the exchange but not tracked in the database.
        """
        logger.info("--- Starting holdings synchronization with Binance ---")

        try:
            # 1. Get current holdings from the exchange
            # We pass an empty dict for prices because, for this logic, we only need asset names and amounts.
            current_holdings = account_manager.get_all_account_balances({})

            # Create a map of holdings for easy lookup, ignoring dust amounts.
            holdings_map = {
                h['asset']: float(h['free']) + float(h['locked'])
                for h in current_holdings if (float(h['free']) + float(h['locked'])) > 0.00001
            }
            logger.info(f"Found {len(holdings_map)} non-dust assets on Binance: {list(holdings_map.keys())}")

            # 2. Get all 'OPEN' and 'TREASURY' positions from our database
            open_positions = self.get_open_positions()
            treasury_positions = self.db_manager.get_treasury_positions(environment=self.mode)

            db_positions_map = {}
            for pos in open_positions + treasury_positions:
                # Assuming all symbols are against USDT, which is a simplification.
                asset = pos.symbol.replace('USDT', '')
                if asset not in db_positions_map:
                    db_positions_map[asset] = []
                db_positions_map[asset].append(pos)

            if db_positions_map:
                logger.info(f"Found {len(db_positions_map)} assets with OPEN/TREASURY status in DB: {list(db_positions_map.keys())}")

            # 3. Reconcile: Close local positions that are no longer on the exchange
            for pos in open_positions:
                asset = pos.symbol.replace('USDT', '')
                if asset not in holdings_map:
                    logger.warning(
                        f"Position {pos.trade_id} for asset {asset} is 'OPEN' in the database, "
                        f"but the asset is no longer held on the exchange. Closing it as 'RECONCILED'."
                    )
                    self.db_manager.update_trade_status(pos.trade_id, 'RECONCILED')

            # 4. Reconcile: Create positions for untracked assets on the exchange
            quote_asset = config_manager.get('APP', 'quote_asset', fallback='USDT')
            for asset, balance in holdings_map.items():
                if asset == quote_asset: # Ignore the quote asset (e.g., USDT)
                    continue
                if asset not in db_positions_map:
                    self._create_position_from_untracked_asset(asset, balance, account_manager, strategy_rules)

            logger.info("--- Holdings synchronization finished ---")

        except Exception as e:
            logger.error(f"An error occurred during holdings synchronization: {e}", exc_info=True)

    def _create_position_from_untracked_asset(self, asset: str, balance: float, account_manager: AccountManager, strategy_rules: StrategyRules):
        """
        Creates a new 'OPEN' position in the database for an untracked asset found on the exchange.
        """
        logger.info(f"Attempting to create a new position for untracked asset: {asset}")
        
        # Assuming USDT is the quote asset, which is a common case.
        # This could be made more robust by fetching pairs from the exchange info.
        symbol = f"{asset}USDT"
        
        # Check if a position for this symbol already exists in the database to avoid duplicates.
        # This relies on a new method in PostgresManager that needs to be implemented.
        if self.db_manager.get_open_position_by_symbol(symbol=symbol, environment=self.mode):
            logger.warning(f"An open position for {symbol} already exists in the database. Skipping creation.")
            return

        # Fetch the most recent trade from Binance to infer the purchase details.
        # We limit to the last 1 trade to get the most recent purchase.
        trade_history = account_manager.get_trade_history(symbol=symbol, limit=1)
        if not trade_history:
            logger.error(f"Could not fetch trade history for {symbol}. Cannot create position for untracked asset.")
            return

        last_trade = trade_history[0]
        purchase_price = float(last_trade['price'])
        commission = float(last_trade['commission'])
        commission_asset = last_trade['commissionAsset']
        
        # Calculate the sell target price based on the strategy rules.
        sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price)

        # Construct the trade data dictionary for logging.
        trade_data = {
            'run_id': self.bot_id,
            'environment': self.mode,
            'strategy_name': 'sync', # Mark as a synchronized trade
            'symbol': symbol,
            'trade_id': str(uuid.uuid4()),
            'exchange': 'binance',
            'status': 'OPEN',
            'order_type': 'buy',
            'price': purchase_price,
            'quantity': balance,
            'usd_value': balance * purchase_price,
            'commission': commission,
            'commission_asset': commission_asset,
            'timestamp': datetime.datetime.fromtimestamp(last_trade['time'] / 1000, tz=datetime.timezone.utc),
            'exchange_order_id': last_trade['orderId'],
            'binance_trade_id': last_trade.get('id'), # Use .get() for safety
            'sell_target_price': sell_target_price,
            'decision_context': {'reason': 'untracked_asset_sync'}
        }
        
        self.trade_logger.log_trade(trade_data)
        logger.info(f"Successfully created a new 'OPEN' position for {symbol} from an untracked on-exchange asset.")

    def record_partial_sell(self, original_trade_id: str, remaining_quantity: float, sell_data: dict):
        """
        Records a partial sell and moves the remaining assets to a treasury.
        1. Logs the sell transaction as a new 'CLOSED' trade.
        2. Creates a new 'TREASURY' trade for the remaining assets.
        3. Closes the original 'OPEN' trade.
        """
        # Step 1: Log the sell transaction as a new record.
        sell_trade_id = str(uuid.uuid4())
        logger.info(f"Logging partial sell transaction with new trade_id: {sell_trade_id} for original trade: {original_trade_id}")
        sell_trade_data = {
            **sell_data,
            'run_id': self.bot_id,
            'trade_id': sell_trade_id,
            'status': 'CLOSED',
            'order_type': 'sell',
            'decision_context': {
                **sell_data.get('decision_context', {}),
                'closing_partial_trade_id': original_trade_id
            }
        }
        self.trade_logger.log_trade(sell_trade_data)

        # Step 2: If there's a remainder, create a new 'TREASURY' position for it.
        if remaining_quantity > 0:
            original_trade = self.db_manager.get_trade_by_trade_id(original_trade_id)
            if not original_trade:
                logger.error(f"Could not find original trade {original_trade_id} to create treasury position. Aborting treasury creation.")
                # We should still close the original position to avoid inconsistent state
                self.db_manager.update_trade_status(original_trade_id, 'CLOSED')
                return

            treasury_trade_id = str(uuid.uuid4())
            logger.info(f"Creating new TREASURY position {treasury_trade_id} with remaining quantity: {remaining_quantity}")

            buy_price = original_trade.price
            treasury_usd_value = remaining_quantity * buy_price

            treasury_data = {
                'run_id': self.bot_id,
                'environment': self.mode,
                'strategy_name': original_trade.strategy_name,
                'symbol': original_trade.symbol,
                'trade_id': treasury_trade_id,
                'exchange': original_trade.exchange,
                'status': 'TREASURY',
                'order_type': 'buy',
                'price': buy_price,
                'quantity': remaining_quantity,
                'usd_value': treasury_usd_value,
                'timestamp': original_trade.timestamp,
                'decision_context': {'source': 'treasury', 'original_trade_id': original_trade_id}
            }
            self.trade_logger.log_trade(treasury_data)

        # Step 3: Close the original position, as it's now fully accounted for.
        logger.info(f"Closing original position {original_trade_id} after partial sell and treasury creation.")
        self.db_manager.update_trade_status(original_trade_id, 'CLOSED')


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
