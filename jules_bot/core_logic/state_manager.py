import pandas as pd
from decimal import Decimal
import math
from datetime import datetime, timedelta, timezone
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.database.models import Trade
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

        # A new 'buy' position should never have a 'sell_price'.
        # This defensively removes the key if it was accidentally included in buy_result.
        trade_data.pop('sell_price', None)
        trade_data.pop('sell_usd_value', None)

        # Defensive coding: ensure no rogue PnL keys are present for a BUY trade.
        self.trade_logger.log_trade(trade_data)

    def sync_holdings_with_binance(self, account_manager: AccountManager, strategy_rules: StrategyRules, trader):
        """
        Synchronizes the database with Binance trade history using a robust,
        stateful FIFO approach. Creates separate BUY and SELL records.
        """
        logger.info("--- Starting trade synchronization with Binance (V3 Logic) ---")
        try:
            symbol = config_manager.get('APP', 'symbol')
            if not symbol:
                logger.error("No symbol configured in APP section. Cannot perform sync.")
                return

            # 1. Fetch all trades and current prices from Binance and the local DB
            binance_trades = trader.get_all_my_trades(symbol=symbol)
            if not binance_trades:
                logger.info(f"No trades found on Binance for {symbol}. Sync complete.")
                return

            # Fetch all prices once to avoid multiple API calls
            all_prices = trader.get_all_prices()

            db_trades = self.db_manager.get_all_trades_in_range(mode=self.mode, symbol=symbol)
            db_binance_trade_ids = {t.binance_trade_id for t in db_trades if t.binance_trade_id}
            logger.info(f"Found {len(db_trades)} trades in DB and {len(binance_trades)} on Binance for {symbol}.")

            # 2. Sync all BUY trades from Binance that are not in our DB
            new_buys_synced = 0
            for b_trade in binance_trades:
                if b_trade['isBuyer'] and b_trade['id'] not in db_binance_trade_ids:
                    logger.info(f"Found new BUY trade on Binance (ID: {b_trade['id']}). Creating local BUY record.")
                    self._create_position_from_binance_trade(b_trade, strategy_rules, all_prices)
                    new_buys_synced += 1

            if new_buys_synced > 0:
                logger.info(f"Synced {new_buys_synced} new buy trades. Refetching DB state before processing sells.")
                db_trades = self.db_manager.get_all_trades_in_range(mode=self.mode, symbol=symbol)

            # 3. Process SELL trades using FIFO logic
            open_positions_fifo = sorted([t for t in db_trades if t.status == 'OPEN' and t.order_type == 'buy'], key=lambda p: p.timestamp)

            # Get sell trades from Binance that haven't been processed yet
            sells_to_process = [st for st in binance_trades if not st['isBuyer'] and st['id'] not in db_binance_trade_ids]

            if not sells_to_process:
                logger.info("No new sell trades from Binance to process.")
            else:
                logger.info(f"Found {len(sells_to_process)} new sell trades to process from Binance.")

            for sell_trade in sells_to_process:
                sell_price = Decimal(str(sell_trade['price']))
                sell_quantity_remaining = Decimal(str(sell_trade['qty']))
                logger.info(f"Processing Binance sell trade ID {sell_trade['id']} for {sell_quantity_remaining} units at ${sell_price:,.2f}.")

                # This loop will continue until the entire sell quantity is accounted for
                # by matching it against open buy positions.
                for open_pos in open_positions_fifo:
                    if sell_quantity_remaining <= Decimal('1e-9'): break # Sell is fully accounted for
                    if open_pos.status != 'OPEN': continue # Skip already closed positions

                    open_pos_quantity = Decimal(str(open_pos.quantity))
                    quantity_to_sell_from_pos = min(open_pos_quantity, sell_quantity_remaining)

                    if quantity_to_sell_from_pos <= Decimal('1e-9'): continue

                    # Create a new SELL record for this part of the transaction
                    buy_price = Decimal(str(open_pos.price))
                    logger.info(f"MATCH: Matched sell trade {sell_trade['id']} (Qty: {quantity_to_sell_from_pos}) with buy trade {open_pos.trade_id} (Buy Price: ${buy_price:,.2f}).")

                    # CRITICAL CALCULATION: Determine the realized profit or loss for this sell event.
                    # First, calculate the commission in USD for the sell trade.
                    sell_commission = Decimal(str(sell_trade.get('commission', '0')))
                    sell_commission_asset = sell_trade.get('commissionAsset')
                    sell_commission_usd = Decimal('0.0')
                    if sell_commission > 0:
                        if sell_commission_asset == 'USDT':
                            sell_commission_usd = sell_commission
                        elif sell_commission_asset == symbol.replace('USDT', ''):
                            sell_commission_usd = sell_commission * sell_price
                        else:
                            asset_price = all_prices.get(f"{sell_commission_asset}USDT")
                            if asset_price:
                                sell_commission_usd = sell_commission * Decimal(str(asset_price))

                    realized_pnl_usd = strategy_rules.calculate_realized_pnl(
                        buy_price=buy_price,
                        sell_price=sell_price,
                        quantity_sold=quantity_to_sell_from_pos,
                        buy_commission_usd=Decimal(str(open_pos.commission_usd)),
                        sell_commission_usd=sell_commission_usd,
                        buy_quantity=Decimal(str(open_pos.quantity))
                    )
                    logger.info(f"CALC PNL: Realized PnL for this portion is ${realized_pnl_usd:,.2f}.")

                    self._create_sell_record_from_sync(open_pos, sell_trade, quantity_to_sell_from_pos, realized_pnl_usd, sell_commission_usd)

                    # Update the original BUY position's quantity
                    remaining_quantity_in_pos = open_pos_quantity - quantity_to_sell_from_pos
                    open_pos.quantity = remaining_quantity_in_pos # Update in-memory object for this session

                    if remaining_quantity_in_pos <= Decimal('1e-9'):
                        self.db_manager.update_trade_status(open_pos.trade_id, 'CLOSED')
                        open_pos.status = 'CLOSED' # Update in-memory object
                        logger.info(f"BUY trade {open_pos.trade_id} fully closed.")
                    else:
                        self.db_manager.update_trade_quantity(open_pos.trade_id, float(remaining_quantity_in_pos))
                        logger.info(f"BUY trade {open_pos.trade_id} partially closed. Remaining qty: {remaining_quantity_in_pos}")

                    sell_quantity_remaining -= quantity_to_sell_from_pos

            logger.info("--- Trade synchronization finished ---")
        except Exception as e:
            logger.error(f"An error occurred during trade synchronization: {e}", exc_info=True)

    def _create_position_from_binance_trade(self, binance_trade: dict, strategy_rules: StrategyRules, all_prices: dict):
        """Helper to create a new DB BUY position from a single Binance trade record."""
        try:
            purchase_price = Decimal(str(binance_trade['price']))
            quantity = Decimal(str(binance_trade['qty']))
            commission = Decimal(str(binance_trade['commission']))
            commission_asset = binance_trade['commissionAsset']
            symbol = binance_trade['symbol']

            # --- Calculate Commission in USD ---
            commission_usd = Decimal('0.0')
            if commission > 0:
                if commission_asset == 'USDT':
                    commission_usd = commission
                elif commission_asset == symbol.replace('USDT', ''):
                    commission_usd = commission * purchase_price
                else:
                    asset_price_symbol = f"{commission_asset}USDT"
                    asset_price = all_prices.get(asset_price_symbol)
                    if asset_price:
                        commission_usd = commission * Decimal(str(asset_price))
                    else:
                        logger.warning(f"Could not find price for commission asset '{commission_asset}' during sync. commission_usd will be 0.")
            
            internal_trade_id = str(uuid.uuid4())
            sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price, params=None)

            buy_result = {
                "run_id": self.bot_id,
                "trade_id": internal_trade_id, "symbol": symbol,
                "price": purchase_price, "quantity": quantity, "usd_value": purchase_price * quantity,
                "commission": commission,
                "commission_asset": commission_asset,
                "commission_usd": commission_usd,
                "exchange_order_id": str(binance_trade['orderId']),
                "binance_trade_id": int(binance_trade['id']),
                "timestamp": datetime.utcfromtimestamp(binance_trade['time'] / 1000).replace(tzinfo=timezone.utc),
                "decision_context": {"reason": "sync_from_binance_buy"},
                "environment": self.mode, "status": "OPEN", "order_type": "buy",
                "sell_target_price": sell_target_price
            }
            
            self.trade_logger.log_trade(buy_result)
        except Exception as e:
            logger.error(f"Failed to create position from trade {binance_trade.get('id')}: {e}", exc_info=True)

    def _create_sell_record_from_sync(self, original_buy_trade: Trade, binance_sell_trade: dict, quantity_sold: Decimal, realized_pnl_usd: Decimal, sell_commission_usd: Decimal):
        """Helper to create a new SELL record during synchronization."""
        try:
            sell_price = Decimal(str(binance_sell_trade['price']))
            sell_trade_id = str(uuid.uuid4())
            sell_usd_value = sell_price * quantity_sold
            commission = Decimal(str(binance_sell_trade['commission']))
            commission_asset = binance_sell_trade['commissionAsset']

            sell_data = {
                'run_id': original_buy_trade.run_id, 'environment': self.mode,
                'strategy_name': original_buy_trade.strategy_name, 'symbol': original_buy_trade.symbol,
                'trade_id': sell_trade_id, 'linked_trade_id': original_buy_trade.trade_id,
                'exchange': original_buy_trade.exchange, 'status': 'CLOSED', 'order_type': 'sell',
                'price': original_buy_trade.price, 'quantity': quantity_sold,
                'usd_value': original_buy_trade.price * quantity_sold,
                'sell_price': sell_price,
                'sell_usd_value': sell_usd_value,
                'commission': commission,
                'commission_asset': commission_asset,
                'commission_usd': sell_commission_usd,
                'timestamp': datetime.utcfromtimestamp(binance_sell_trade['time'] / 1000).replace(tzinfo=timezone.utc),
                'exchange_order_id': str(binance_sell_trade['orderId']),
                'binance_trade_id': int(binance_sell_trade['id']),
                'decision_context': {'reason': 'sync_from_binance_sell'},
                'realized_pnl_usd': realized_pnl_usd
            }
            logger.debug(f"Passing this data to TradeLogger for a SELL record: {sell_data}")
            self.trade_logger.log_trade(sell_data)
            logger.info(f"Created SELL record {sell_trade_id} linked to BUY {original_buy_trade.trade_id} with PnL ${realized_pnl_usd:.2f}")
        except Exception as e:
            logger.error(f"Failed to create sell record from sync: {e}", exc_info=True)

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
        Records a partial sell by creating a new 'sell' record for the sold portion
        and updating the quantity of the original 'buy' record.
        """
        logger.info(f"Recording partial sell for original trade: {original_trade_id}")

        original_trade = self.db_manager.get_trade_by_trade_id(original_trade_id)
        if not original_trade:
            logger.error(f"Could not find original trade {original_trade_id} to record partial sell. Aborting.")
            return

        # 1. Create a new 'sell' record for the sold portion
        sell_trade_id = str(uuid.uuid4())
        
        # Explicitly construct the dictionary to ensure type safety and handle the timestamp correctly.
        sell_record_data = {
            'run_id': self.bot_id,
            'environment': self.mode,
            'strategy_name': original_trade.strategy_name,
            'symbol': original_trade.symbol,
            'trade_id': sell_trade_id,
            'linked_trade_id': original_trade_id,
            'exchange': original_trade.exchange,
            'status': 'CLOSED',  # A sell action is always final
            'order_type': 'sell',
            'price': original_trade.price,
            'quantity': Decimal(str(sell_data['quantity'])),
            'usd_value': original_trade.price * Decimal(str(sell_data['quantity'])),
            'sell_price': Decimal(str(sell_data['price'])),
            'sell_usd_value': Decimal(str(sell_data['usd_value'])),
            'commission': Decimal(str(sell_data.get('commission', '0'))),
            'commission_asset': sell_data.get('commission_asset'),
            'timestamp': datetime.utcfromtimestamp(sell_data['timestamp'] / 1000).replace(tzinfo=timezone.utc),
            'exchange_order_id': sell_data.get('exchange_order_id'),
            'binance_trade_id': sell_data.get('binance_trade_id'),
            'decision_context': sell_data.get('decision_context'),
            'realized_pnl_usd': sell_data.get('realized_pnl_usd'),
            'hodl_asset_amount': sell_data.get('hodl_asset_amount'),
            'hodl_asset_value_at_sell': sell_data.get('hodl_asset_value_at_sell'),
        }

        self.trade_logger.log_trade(sell_record_data)
        logger.info(f"Created new SELL record {sell_trade_id} for partial sell of {original_trade_id} with PnL: ${sell_record_data.get('realized_pnl_usd', 0):.2f}.")

        # 2. Update the original 'buy' trade's quantity to reflect the remainder
        if remaining_quantity > Decimal('1e-8'): # Use tolerance
            logger.info(f"Updating quantity of original trade {original_trade_id} to remaining {remaining_quantity:.8f}.")
            context_update = {
                "partial_sell_info": f"Partial sell executed. New sell record: {sell_trade_id}",
                "last_update_time": datetime.utcnow().isoformat()
            }
            self.db_manager.update_trade_quantity_and_context(
                trade_id=original_trade_id,
                new_quantity=float(remaining_quantity),
                context_update=context_update
            )
        else:
            # If the remaining quantity is zero, close the original trade
            logger.info(f"Remaining quantity for {original_trade_id} is zero. Marking as CLOSED.")
            self.db_manager.update_trade_status(original_trade_id, 'CLOSED')

    def close_forced_position(self, trade_id: str, sell_result: dict, realized_pnl_usd: Decimal):
        """
        Records a new 'sell' trade to close a position after a forced sell,
        and updates the original 'buy' trade's status to 'CLOSED'.

        Args:
            trade_id: The ID of the original 'buy' trade to close.
            sell_result: The result from trader.execute_sell(), containing the
                         actual price, quantity, and usd_value of the sale.
            realized_pnl_usd: The calculated profit or loss for this trade.
        """
        logger.info(f"Force closing position {trade_id} with PnL: ${realized_pnl_usd:.2f}")

        original_trade = self.db_manager.get_trade_by_trade_id(trade_id)
        if not original_trade:
            logger.error(f"Could not find original trade {trade_id} to close. Aborting.")
            return

        # 1. Create a new 'sell' record
        sell_trade_id = str(uuid.uuid4())
        
        # Explicitly construct the dictionary to ensure type safety and handle the timestamp correctly.
        # The 'timestamp' from the trader response is an integer, but TradeLogger expects a datetime object.
        sell_data = {
            'run_id': self.bot_id,
            'environment': self.mode,
            'strategy_name': original_trade.strategy_name,
            'symbol': original_trade.symbol,
            'trade_id': sell_trade_id,
            'linked_trade_id': trade_id,
            'exchange': original_trade.exchange,
            'status': 'CLOSED',
            'order_type': 'sell',
            'price': original_trade.price,
            'quantity': Decimal(str(sell_result['quantity'])),
            'usd_value': Decimal(str(original_trade.price)) * Decimal(str(sell_result['quantity'])),
            'sell_price': Decimal(str(sell_result['price'])),
            'sell_usd_value': Decimal(str(sell_result['usd_value'])),
            'commission': Decimal(str(sell_result.get('commission', '0'))),
            'commission_asset': sell_result.get('commission_asset'),
            'timestamp': datetime.utcfromtimestamp(sell_result['timestamp'] / 1000).replace(tzinfo=timezone.utc),
            'exchange_order_id': sell_result.get('exchange_order_id'),
            'binance_trade_id': sell_result.get('binance_trade_id'),
            'decision_context': sell_result.get('decision_context'),
            'realized_pnl_usd': realized_pnl_usd,
        }

        self.trade_logger.log_trade(sell_data)
        logger.info(f"Created new SELL record {sell_trade_id} for forced sell of {trade_id} with PnL: ${realized_pnl_usd:.2f}.")

        # 2. Update the original 'buy' trade to be closed
        self.db_manager.update_trade_status(trade_id, 'CLOSED')
        logger.info(f"Updated original BUY record {trade_id} status to 'CLOSED'.")
