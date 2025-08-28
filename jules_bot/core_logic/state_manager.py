import pandas as pd
from decimal import Decimal
import math
from datetime import datetime, timedelta, timezone
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
import uuid
from jules_bot.utils.config_manager import config_manager
from jules_bot.services.trade_logger import TradeLogger
from jules_bot.bot.account_manager import AccountManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.bot.situational_awareness import SituationalAwareness
from jules_bot.core_logic.dynamic_parameters import DynamicParameters
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator


class StateManager:
    def __init__(self, mode: str, bot_id: str, db_manager: PostgresManager, feature_calculator: LiveFeatureCalculator):
        self.mode = mode
        self.bot_id = bot_id
        self.db_manager = db_manager
        self.SessionLocal = db_manager.SessionLocal # Add this line
        self.feature_calculator = feature_calculator

        # The TradeLogger is now responsible for ALL WRITE operations.
        self.trade_logger = TradeLogger(mode=self.mode, db_manager=self.db_manager)

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

    def get_trade_history_for_run(self) -> list:
        """Fetches all trades from the database for the current bot run."""
        return self.db_manager.get_trades_by_run_id(run_id=self.bot_id)

    def get_trades_in_last_n_hours(self, hours: int) -> list:
        """Fetches all trades from the database within the last N hours."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(hours=hours)
        return self.db_manager.get_all_trades_in_range(
            mode=self.mode,
            start_date=start_date,
            end_date=end_date
        )

    def get_last_purchase_price(self) -> Decimal:
        """
        Retrieves the purchase price of the most recent 'buy' trade.
        Returns Decimal('inf') if no open positions are found.
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return Decimal('inf')

        # Sort by time to find the most recent position.
        latest_position = sorted(open_positions, key=lambda p: p.timestamp, reverse=True)[0]
        
        return Decimal(str(latest_position.price))

    def create_new_position(self, buy_result: dict, sell_target_price: Decimal):
        """
        Records a new open position in the database via the TradeLogger service.
        """
        logger.info(f"Creating new position for trade_id: {buy_result.get('trade_id')} with target sell price: {sell_target_price:.8f}")

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

    def sync_holdings_with_binance(self, account_manager: AccountManager, strategy_rules: StrategyRules, trader):
        """
        Synchronizes the database with current Binance trades. It ensures that every
        buy trade on Binance is represented as an 'OPEN' or 'CLOSED' position in the
        local database, preventing duplicates.
        """
        logger.info("--- Starting trade synchronization with Binance ---")
        try:
            symbol = config_manager.get('APP', 'symbol')
            if not symbol:
                logger.error("No symbol configured in APP section. Cannot perform sync.")
                return

            # 1. Fetch all trades from Binance for the given symbol
            binance_trades = trader.get_all_my_trades(symbol=symbol)
            if not binance_trades:
                logger.info(f"No trades found on Binance for {symbol}. Sync complete.")
                return

            # 2. Fetch all trades from the local DB for the same symbol and environment
            db_trades = self.db_manager.get_all_trades_in_range(mode=self.mode, symbol=symbol)
            existing_binance_trade_ids = {t.binance_trade_id for t in db_trades if t.binance_trade_id}
            logger.info(f"Found {len(existing_binance_trade_ids)} existing trades in the database for {symbol}.")

            # 3. Reconcile: Iterate through Binance trades and create/update local records
            new_trades_synced = 0
            updated_trades = 0
            for b_trade in binance_trades:
                if b_trade['id'] in existing_binance_trade_ids:
                    continue

                # If the trade is not in our DB by binance_trade_id, check by exchange_order_id
                # This handles the case where the trade was logged before the binance_trade_id was available
                local_trade = self.db_manager.get_trade_by_exchange_order_id(str(b_trade['orderId']))

                if local_trade and local_trade.binance_trade_id is None:
                    # Found a match! Update the existing record with the binance_trade_id
                    logger.info(f"Found matching local trade ({local_trade.trade_id}) for Binance trade ID {b_trade['id']} by matching order ID. Updating.")
                    self.db_manager.update_trade_binance_id(local_trade.trade_id, b_trade['id'])
                    # Add the newly linked ID to the set to prevent duplicates in the same run
                    existing_binance_trade_ids.add(b_trade['id'])
                    updated_trades += 1
                    continue

                if b_trade['isBuyer']:
                    logger.info(f"Found new BUY trade on Binance (ID: {b_trade['id']}). Creating local position.")
                    self._create_position_from_trade(b_trade, strategy_rules)
                    new_trades_synced += 1

            if new_trades_synced > 0 or updated_trades > 0:
                logger.info(f"Sync complete. New trades created: {new_trades_synced}. Trades updated: {updated_trades}.")
                # After syncing, reconcile the total position with the actual balance
                self.reconcile_holdings(symbol, trader)
            else:
                logger.info("Database is already in sync with Binance. No new trades to add or update.")

            logger.info("--- Trade synchronization finished ---")

        except Exception as e:
            logger.error(f"An error occurred during trade synchronization: {e}", exc_info=True)

    def _create_position_from_trade(self, binance_trade: dict, strategy_rules: StrategyRules):
        """Helper to create a new DB position from a single Binance trade record."""
        try:
            purchase_price = Decimal(str(binance_trade['price']))
            quantity = Decimal(str(binance_trade['qty']))
            
            # Create a new, unique internal trade_id
            internal_trade_id = str(uuid.uuid4())

            # We pass `params=None` because, during a sync, we don't know what the dynamic
            # parameters were at the time of the historical trade. The function will use a default.
            sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price, params=None)

            buy_result = {
                "trade_id": internal_trade_id,
                "symbol": binance_trade['symbol'],
                "price": purchase_price,
                "quantity": quantity,
                "usd_value": purchase_price * quantity,
                "commission": Decimal(str(binance_trade['commission'])),
                "commission_asset": binance_trade['commissionAsset'],
                "exchange_order_id": str(binance_trade['orderId']),
                "binance_trade_id": int(binance_trade['id']),
                "timestamp": pd.to_datetime(binance_trade['time'], unit='ms', utc=True),
                "decision_context": {"reason": "sync_from_binance_trade"},
                "environment": self.mode,
            }
            
            self.create_new_position(buy_result, sell_target_price)
            logger.info(f"Successfully created new position for Binance trade ID: {binance_trade['id']}")

        except Exception as e:
            logger.error(f"Failed to create position from trade {binance_trade.get('id')}: {e}", exc_info=True)

    def reconcile_holdings(self, symbol: str, trader):
        """
        Adjusts the quantities of open positions to match the actual exchange balance.
        This is the primary mechanism for self-correcting state drift. It accounts
        for sells by reducing the quantity of the oldest buy positions first (FIFO).
        """
        logger.info(f"Reconciling position quantities for {symbol} with actual exchange balance...")
        try:
            # 1. Get all open positions for the symbol from the DB, sorted oldest first
            open_positions = sorted(
                self.db_manager.get_open_positions(environment=self.mode, symbol=symbol),
                key=lambda p: p.timestamp
            )
            if not open_positions:
                logger.info("No open positions found to reconcile.")
                return

            # 2. Get the total quantity held by the bot for this symbol
            bot_total_quantity = sum(Decimal(str(p.quantity)) for p in open_positions)

            # 3. Get the actual balance from the exchange
            asset = symbol.replace('USDT', '')
            # Ensure the balance from the exchange is treated as a Decimal
            exchange_balance = Decimal(str(trader.get_account_balance(asset=asset)))
            
            logger.info(f"Bot's calculated total quantity for {asset}: {bot_total_quantity:.8f}")
            logger.info(f"Actual exchange balance for {asset}: {exchange_balance:.8f}")

            # 4. Calculate the discrepancy
            discrepancy = bot_total_quantity - exchange_balance
            # Use a Decimal for tolerance comparison
            if discrepancy <= Decimal('0.00000001'):
                logger.info("Bot's position quantities are already in sync with the exchange balance.")
                return
            
            logger.warning(f"Discrepancy of {discrepancy:.8f} {asset} found. Reconciling by closing/reducing oldest positions...")

            # 5. Reconcile by reducing quantity from oldest positions first (FIFO)
            for position in open_positions:
                if discrepancy <= Decimal('0'):
                    break

                # Ensure all quantities are Decimal for comparison
                position_quantity = Decimal(str(position.quantity))
                quantity_to_reduce = min(position_quantity, discrepancy)
                
                new_quantity = position_quantity - quantity_to_reduce
                
                # Use a Decimal for tolerance comparison
                if new_quantity <= Decimal('0.00000001'):
                    logger.info(f"Closing position {position.trade_id} via reconciliation as it has been fully sold.")
                    context_update = {
                        "reconciliation_note": "Position closed by reconciliation process due to balance discrepancy.",
                        "reconciliation_time": datetime.utcnow().isoformat()
                    }
                    self.db_manager.update_trade_status_and_context(
                        trade_id=position.trade_id,
                        new_status='RECONCILED_CLOSED',
                        context_update=context_update
                    )
                else:
                    logger.info(f"Reducing quantity of position {position.trade_id} by {quantity_to_reduce:.8f} to new quantity {new_quantity:.8f}.")
                    context_update = {
                        "reconciliation_note": f"Position quantity reduced by {quantity_to_reduce:.8f} due to balance discrepancy.",
                        "reconciliation_time": datetime.utcnow().isoformat()
                    }
                    self.db_manager.update_trade_quantity_and_context(
                        trade_id=position.trade_id,
                        new_quantity=float(new_quantity), # Ensure it's a float for the DB
                        context_update=context_update
                    )
                
                discrepancy -= quantity_to_reduce

            logger.info("Finished reconciling position quantities.")

        except Exception as e:
            logger.error(f"An error occurred during balance reconciliation for {symbol}: {e}", exc_info=True)

    def recalculate_open_position_targets(self, strategy_rules: StrategyRules, sa_instance: SituationalAwareness, dynamic_params: DynamicParameters):
        """
        Recalculates the sell_target_price for all open positions based on the current
        market regime and strategy parameters.
        """
        logger.info("--- Starting recalculation of sell targets for open positions ---")
        open_positions = self.get_open_positions()
        if not open_positions:
            logger.info("No open positions to recalculate.")
            return

        # 1. Determine the current market regime
        features_df = self.feature_calculator.get_features_dataframe()
        if features_df.empty:
            logger.error("Could not get features dataframe. Aborting target recalculation.")
            return

        current_regime = -1
        # The sa_instance is always "fitted" as it's rule-based.
        regime_df = sa_instance.transform(features_df)
        if not regime_df.empty:
            current_regime = int(regime_df['market_regime'].iloc[-1])

        logger.info(f"Recalculating targets based on current market regime: {current_regime}")

        # 2. Get the parameters for the current regime
        dynamic_params.update_parameters(current_regime)
        current_params = dynamic_params.parameters

        # 3. Iterate through open positions and recalculate
        updated_count = 0
        for position in open_positions:
            try:
                purchase_price = Decimal(str(position.price))
                current_target = Decimal(str(position.sell_target_price))

                new_target = strategy_rules.calculate_sell_target_price(purchase_price, params=current_params)

                # Use a small tolerance for comparison to avoid floating point issues
                if not math.isclose(new_target, current_target, rel_tol=1e-9):
                    self.db_manager.update_trade_sell_target(position.trade_id, new_target)
                    logger.info(f"Updated sell target for trade {position.trade_id}: Old=${current_target:,.2f}, New=${new_target:,.2f}")
                    updated_count += 1
            except Exception as e:
                logger.error(f"Failed to recalculate target for trade {position.trade_id}: {e}", exc_info=True)

        if updated_count > 0:
            logger.info(f"Successfully updated targets for {updated_count} open positions.")
        else:
            logger.info("All open position targets are already up to date.")

        logger.info("--- Finished recalculating sell targets ---")


    def record_partial_sell(self, original_trade_id: str, remaining_quantity: Decimal, sell_data: dict):
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
        if remaining_quantity > Decimal('0'):
            original_trade = self.db_manager.get_trade_by_trade_id(original_trade_id)
            if not original_trade:
                logger.error(f"Could not find original trade {original_trade_id} to create treasury position. Aborting treasury creation.")
                # We should still close the original position to avoid inconsistent state
                self.db_manager.update_trade_status(original_trade_id, 'CLOSED')
                return

            treasury_trade_id = str(uuid.uuid4())
            logger.info(f"Creating new TREASURY position {treasury_trade_id} with remaining quantity: {remaining_quantity:.8f}")

            buy_price = Decimal(str(original_trade.price))
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

    def close_forced_position(self, trade_id: str, sell_result: dict, realized_pnl: Decimal):
        """
        Updates a specific trade to CLOSED status after a forced sell,
        and records the realized PnL. This directly updates the existing trade record.
        """
        logger.info(f"Force closing position {trade_id} with PnL: ${realized_pnl:.2f}")

        update_data = sell_result.copy()

        # Convert integer timestamp (milliseconds) to datetime object before DB insertion
        raw_timestamp = update_data.get('timestamp')
        if isinstance(raw_timestamp, int):
            update_data['timestamp'] = datetime.fromtimestamp(raw_timestamp / 1000, tz=timezone.utc)

        # Add the PnL to the sell data dictionary
        update_data['realized_pnl_usd'] = realized_pnl

        # Use the direct DB method to update the original trade record
        # This bypasses the event-style logging of TradeLogger for a direct state update.
        self.db_manager.update_trade_on_sell(trade_id, update_data)

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
