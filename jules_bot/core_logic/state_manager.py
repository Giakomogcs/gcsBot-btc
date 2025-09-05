import pandas as pd
from decimal import Decimal
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
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
        Synchronizes the bot's state with the exchange. It ensures that any position
        on the exchange is accurately reflected in the local database.
        - It uses a FIFO method to match sells to buys.
        - Adopts new positions from the exchange that aren't in the database.
        - Updates the status and quantity of existing positions.
        - Closes local positions that are no longer open on the exchange.
        """
        logger.info("--- Starting State Synchronization & Position Adoption ---")
        try:
            symbol = config_manager.get('APP', 'symbol')
            if not symbol:
                logger.error("No symbol configured. Cannot perform sync.")
                return

            all_binance_trades = trader.get_all_my_trades(symbol=symbol)
            if all_binance_trades is None:
                logger.error("Failed to fetch trades from Binance. Aborting sync.")
                return

            db_trades = self.db_manager.get_all_trades_in_range(mode=self.mode, symbol=symbol)
            db_trades_map = {t.binance_trade_id: t for t in db_trades if t.binance_trade_id}

            logger.info(f"Found {len(all_binance_trades)} trades on Binance and {len(db_trades_map)} in DB for {symbol}.")

            if not all_binance_trades:
                logger.info("No trade history on Binance. Closing any locally open positions.")
                open_positions = self.get_open_positions()
                for pos in open_positions:
                    logger.warning(f"Closing stale local position {pos.trade_id} as no trades exist on Binance.")
                    self.db_manager.update_trade_status(pos.trade_id, "CLOSED")
                return

            buys = sorted([t for t in all_binance_trades if t['isBuyer']], key=lambda t: t['time'])
            sells = sorted([t for t in all_binance_trades if not t['isBuyer']], key=lambda t: t['time'])

            buy_pool = {
                buy['id']: {**buy, 'remaining_qty': Decimal(str(buy['qty']))}
                for buy in buys
            }

            # --- New FIFO Matching Logic ---
            # This logic now also tracks which sells close which buys to create sell records.
            matched_sells = {}
            for sell in sells:
                sell_qty_to_match = Decimal(str(sell['qty']))
                sell_id = sell['id']
                matched_sells[sell_id] = []

                for buy_id in sorted(buy_pool.keys()):
                    if sell_qty_to_match <= Decimal('0'):
                        break

                    buy = buy_pool[buy_id]
                    if buy['remaining_qty'] <= Decimal('0'):
                        continue

                    matched_qty = min(sell_qty_to_match, buy['remaining_qty'])
                    if matched_qty > 0:
                        buy['remaining_qty'] -= matched_qty
                        sell_qty_to_match -= matched_qty

                        # Record the match for creating a sell record later
                        matched_sells[sell_id].append({
                            'buy_id': buy_id,
                            'matched_qty': matched_qty,
                            'sell_trade_data': sell
                        })

            logger.info("FIFO simulation complete. Reconciling with local database and creating sell records...")

            all_prices = trader.get_all_prices()

            # Create sell records for all matched sells
            for sell_id, matches in matched_sells.items():
                for match in matches:
                    buy_id = match['buy_id']
                    sell_trade_data = match['sell_trade_data']

                    # Check if this sell has already been recorded
                    if self.db_manager.get_trade_by_binance_id(sell_trade_data['id']):
                        logger.info(f"Sell trade {sell_trade_data['id']} has already been recorded. Skipping.")
                        continue

                    original_buy_db_trade = db_trades_map.get(buy_id)
                    if original_buy_db_trade:
                        self._create_sell_record_from_sync(
                            original_buy_trade=original_buy_db_trade,
                            binance_sell_trade=sell_trade_data,
                            quantity_sold=match['matched_qty'],
                            strategy_rules=strategy_rules,
                            all_prices=all_prices
                        )
                    else:
                        logger.warning(f"Could not find original buy trade in DB for Binance buy_id {buy_id}. Cannot create linked sell record.")

            # Reconcile local state with the simulated state from the exchange
            binance_open_buy_ids = set()
            for buy_id, buy_state in buy_pool.items():
                final_quantity = buy_state['remaining_qty']
                is_open_on_binance = final_quantity > Decimal('1e-9')

                if is_open_on_binance:
                    binance_open_buy_ids.add(buy_id)

                db_trade = db_trades_map.get(buy_id)
                if db_trade:
                    # Trade exists in DB, check for status/quantity updates
                    final_status = "OPEN" if is_open_on_binance else "CLOSED"
                    # Only update if there's a meaningful change
                    if db_trade.status != final_status or not math.isclose(Decimal(str(db_trade.quantity)), final_quantity, rel_tol=1e-9):
                        logger.info(f"Updating position {db_trade.trade_id} (BinanceID: {buy_id}): Status {db_trade.status}->{final_status}, Qty {db_trade.quantity}->{final_quantity:.8f}")
                        self.db_manager.update_trade_status_and_quantity(db_trade.trade_id, final_status, float(final_quantity))
                elif is_open_on_binance:
                    # Trade is open on Binance but not in DB, so adopt it
                    logger.info(f"Adopting new open position from Binance (TradeID: {buy_id}), Qty: {final_quantity:.8f}")
                    self._create_position_from_binance_trade(buy_state, strategy_rules, all_prices, "OPEN")

            # Final check: Close any local positions that are no longer considered open on Binance
            locally_open_trades = self.get_open_positions()
            for local_trade in locally_open_trades:
                # Check if the trade has a Binance ID and if that ID is not in the set of open buys from the simulation
                if local_trade.binance_trade_id and local_trade.binance_trade_id not in binance_open_buy_ids:
                    logger.warning(f"Closing stale local position {local_trade.trade_id} (BinanceID: {local_trade.binance_trade_id}) as it's no longer considered open on the exchange.")
                    self.db_manager.update_trade_status(local_trade.trade_id, "CLOSED")

            logger.info("--- State Synchronization & Position Adoption Finished ---")
        except Exception as e:
            logger.critical(f"A critical error occurred during state synchronization: {e}", exc_info=True)

    def _calculate_commission_in_usd(self, commission: Decimal, asset: str, price: Decimal, symbol: str, all_prices: dict) -> Decimal:
        """Helper to calculate commission value in USD."""
        if commission <= 0:
            return Decimal('0')

        if asset == 'USDT':
            return commission
        elif asset == symbol.replace('USDT', ''):
            return commission * price
        else:
            asset_price_symbol = f"{asset}USDT"
            asset_price = all_prices.get(asset_price_symbol)
            if asset_price:
                return commission * Decimal(str(asset_price))
            else:
                logger.warning(f"Could not find price for commission asset '{asset}'. Commission calculation may be inaccurate.")
                return Decimal('0')

    def _create_position_from_binance_trade(self, binance_trade: dict, strategy_rules: StrategyRules, all_prices: dict, final_status: str):
        """
        Helper to create a new DB BUY position from a single Binance trade record,
        using the final status and quantity determined by the sync simulation.
        """
        try:
            # The binance_trade dict comes from the simulation, so it has 'remaining_qty'
            purchase_price = binance_trade['price']
            original_quantity = binance_trade['qty']
            final_quantity = binance_trade['remaining_qty']
            commission = binance_trade['commission']
            commission_asset = binance_trade['commissionAsset']
            symbol = binance_trade['symbol']

            commission_usd = self._calculate_commission_in_usd(
                commission, commission_asset, purchase_price, symbol, all_prices
            )
            
            internal_trade_id = str(uuid.uuid4())
            # Pass original_quantity for an accurate sell target calculation if it depends on the full size
            sell_target_price = strategy_rules.calculate_sell_target_price(purchase_price, original_quantity, params=None)

            buy_result = {
                "run_id": self.bot_id,
                "trade_id": internal_trade_id,
                "symbol": symbol,
                "price": purchase_price,
                "quantity": final_quantity, # Log the remaining quantity
                "usd_value": purchase_price * original_quantity, # Log the original value
                "commission": commission,
                "commission_asset": commission_asset,
                "commission_usd": commission_usd,
                "exchange_order_id": str(binance_trade['orderId']),
                "binance_trade_id": int(binance_trade['id']),
                "timestamp": datetime.fromtimestamp(binance_trade['time'] / 1000, tz=datetime.timezone.utc),
                "decision_context": {"reason": "sync_from_binance_buy", "original_qty": float(original_quantity)},
                "environment": self.mode,
                "status": final_status, # Use the status from the simulation
                "order_type": "buy",
                "sell_target_price": sell_target_price
            }
            
            self.trade_logger.log_trade(buy_result)
        except Exception as e:
            logger.error(f"Failed to create position from trade {binance_trade.get('id')}: {e}", exc_info=True)

    def _create_sell_record_from_sync(self, original_buy_trade: Trade, binance_sell_trade: dict, quantity_sold: Decimal, strategy_rules: StrategyRules, all_prices: dict):
        """
        Helper to create a new SELL record during synchronization.
        This now calculates PnL and stores the raw sell data as 'fills'.
        """
        try:
            sell_price = Decimal(str(binance_sell_trade['price']))
            sell_trade_id = str(uuid.uuid4())
            sell_usd_value = sell_price * quantity_sold
            commission = Decimal(str(binance_sell_trade['commission']))
            commission_asset = binance_sell_trade['commissionAsset']
            symbol = original_buy_trade.symbol

            # --- PnL and Commission Calculation ---
            sell_commission_usd = self._calculate_commission_in_usd(
                commission, commission_asset, sell_price, symbol, all_prices
            )

            realized_pnl_usd = strategy_rules.calculate_realized_pnl(
                buy_price=Decimal(str(original_buy_trade.price)),
                sell_price=sell_price,
                quantity_sold=quantity_sold,
                buy_commission_usd=Decimal(str(original_buy_trade.commission_usd)),
                sell_commission_usd=sell_commission_usd,
                buy_quantity=Decimal(str(original_buy_trade.quantity)) # Use original buy quantity for pro-rata calc
            )

            buy_usd_value = original_buy_trade.price * quantity_sold
            pnl_percentage = (realized_pnl_usd / buy_usd_value) * 100 if buy_usd_value != 0 else 0

            # Store the raw sell trade data in the decision context to act as the "fills"
            decision_context = {
                'reason': 'sync_from_binance_sell',
                'pnl_percentage': f"{pnl_percentage:.2f}",
                'fills': binance_sell_trade
            }

            sell_data = {
                'run_id': original_buy_trade.run_id, 'environment': self.mode,
                'strategy_name': original_buy_trade.strategy_name, 'symbol': symbol,
                'trade_id': sell_trade_id, 'linked_trade_id': original_buy_trade.trade_id,
                'exchange': original_buy_trade.exchange, 'status': 'CLOSED', 'order_type': 'sell',
                'price': original_buy_trade.price, 'quantity': quantity_sold,
                'usd_value': buy_usd_value,
                'sell_price': sell_price,
                'sell_usd_value': sell_usd_value,
                'commission': commission,
                'commission_asset': commission_asset,
                'commission_usd': sell_commission_usd,
                'timestamp': datetime.fromtimestamp(binance_sell_trade['time'] / 1000, tz=timezone.utc),
                'exchange_order_id': str(binance_sell_trade['orderId']),
                'binance_trade_id': int(binance_sell_trade['id']),
                'decision_context': decision_context,
                'realized_pnl_usd': realized_pnl_usd
            }

            self.trade_logger.log_trade(sell_data)
            logger.info(f"Created SELL record {sell_trade_id} linked to BUY {original_buy_trade.trade_id} with PnL ${realized_pnl_usd:.2f}")
        except Exception as e:
            logger.error(f"Failed to create sell record from sync: {e}", exc_info=True)

    def _create_sell_record_from_sync_unlinked(self, binance_sell_trade: dict):
        """Helper to create a new SELL record during synchronization for a trade that cannot be linked to a buy."""
        try:
            sell_price = Decimal(str(binance_sell_trade['price']))
            quantity_sold = Decimal(str(binance_sell_trade['qty']))
            sell_usd_value = sell_price * quantity_sold

            sell_data = {
                'run_id': self.bot_id, 'environment': self.mode,
                'strategy_name': 'sync_unlinked', 'symbol': binance_sell_trade['symbol'],
                'trade_id': str(uuid.uuid4()), 'linked_trade_id': None,
                'exchange': 'binance', 'status': 'CLOSED', 'order_type': 'sell',
                'price': sell_price, # In unlinked sells, we don't know the buy price, so we use sell_price as placeholder
                'quantity': quantity_sold,
                'usd_value': sell_usd_value, # Placeholder
                'sell_price': sell_price,
                'sell_usd_value': sell_usd_value,
                'commission': Decimal(str(binance_sell_trade['commission'])),
                'commission_asset': binance_sell_trade['commissionAsset'],
                'timestamp': datetime.utcfromtimestamp(binance_sell_trade['time'] / 1000).replace(tzinfo=timezone.utc),
                'exchange_order_id': str(binance_sell_trade['orderId']),
                'binance_trade_id': int(binance_sell_trade['id']),
                'decision_context': {'reason': 'sync_from_binance_unlinked_sell'},
                'realized_pnl_usd': 0 # PnL is unknown without the buy side
            }
            self.trade_logger.log_trade(sell_data)
            logger.info(f"Created unlinked SELL record for Binance Trade ID {binance_sell_trade['id']}")
        except Exception as e:
            logger.error(f"Failed to create unlinked sell record from sync: {e}", exc_info=True)

    def recalculate_open_position_targets(self, strategy_rules: StrategyRules, sa_instance: SituationalAwareness, dynamic_params: DynamicParameters, features_df: pd.DataFrame):
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
        # The features_df is now passed directly to the method.
        if features_df is None or features_df.empty:
            logger.error("Features dataframe is missing or empty. Aborting target recalculation.")
            return

        current_regime = -1
        # The sa_instance is always "fitted" as it's rule-based.
        regime_df = sa_instance.transform(features_df)
        if not regime_df.empty:
            current_regime = int(regime_df['market_regime'].iloc[-1])

        # If the regime is undefined, we cannot determine the correct parameters.
        if current_regime == -1:
            logger.warning("Cannot recalculate targets because market regime is undefined (-1). Skipping.")
            return

        logger.info(f"Recalculating targets based on current market regime: {current_regime}")

        # 2. Get the parameters for the current regime
        dynamic_params.update_parameters(current_regime)
        current_params = dynamic_params.parameters

        # 3. Iterate through open positions and recalculate
        updated_count = 0
        for position in open_positions:
            try:
                purchase_price = Decimal(str(position.price))
                
                # Defensively handle invalid or missing current_target
                current_target = Decimal('0') # Default value
                if position.sell_target_price is not None:
                    try:
                        current_target = Decimal(str(position.sell_target_price))
                    except Exception:
                        logger.warning(f"Could not parse current sell target '{position.sell_target_price}' for trade {position.trade_id}. Defaulting to 0.")

                quantity = Decimal(str(position.quantity))
                new_target = strategy_rules.calculate_sell_target_price(purchase_price, quantity, params=current_params)

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

    def update_trade_trailing_state(self, trade_id: str, is_trailing: bool, highest_price: Optional[Decimal]):
        """
        Updates the trailing state fields for a specific trade.
        """
        logger.info(f"Updating trailing state for trade {trade_id}: is_trailing={is_trailing}, highest_price={highest_price}")
        update_data = {
            "is_trailing": is_trailing,
            "highest_price_since_breach": highest_price
        }
        # The underlying db_manager.update_trade is prepared to handle this dictionary
        self.db_manager.update_trade(trade_id, update_data)

    def update_trade_smart_trailing_state(self, trade_id: str, is_active: bool, highest_profit: Optional[Decimal] = None, activation_price: Optional[Decimal] = None):
        """
        Updates the state fields for the intelligent trailing stop for a specific trade.
        """
        logger.info(f"Updating smart trailing state for {trade_id}: active={is_active}, highest_profit={highest_profit}, activation_price={activation_price}")
        update_data = {
            "is_smart_trailing_active": is_active,
            "smart_trailing_highest_profit": highest_profit,
            "smart_trailing_activation_price": activation_price
        }
        # The underlying db_manager.update_trade is prepared to handle this dictionary
        self.db_manager.update_trade(trade_id, update_data)

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
        # Calculate PnL percentage
        buy_usd_value = original_trade.price * Decimal(str(sell_data['quantity']))
        pnl_percentage = (sell_data.get('realized_pnl_usd', 0) / buy_usd_value) * 100 if buy_usd_value != 0 else 0

        decision_context = sell_data.get('decision_context', {})
        decision_context['pnl_percentage'] = f"{pnl_percentage:.2f}"

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
            'usd_value': buy_usd_value,
            'sell_price': Decimal(str(sell_data['price'])),
            'sell_usd_value': Decimal(str(sell_data['usd_value'])),
            'commission': Decimal(str(sell_data.get('commission', '0'))),
            'commission_asset': sell_data.get('commission_asset'),
            'timestamp': datetime.utcfromtimestamp(sell_data['timestamp'] / 1000).replace(tzinfo=timezone.utc),
            'exchange_order_id': sell_data.get('exchange_order_id'),
            'binance_trade_id': sell_data.get('binance_trade_id'),
            'decision_context': decision_context,
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
        buy_usd_value = Decimal(str(original_trade.price)) * Decimal(str(sell_result['quantity']))
        pnl_percentage = (Decimal(str(realized_pnl_usd)) / buy_usd_value) * 100 if buy_usd_value != 0 else 0

        decision_context = sell_result.get('decision_context', {})
        decision_context['pnl_percentage'] = f"{pnl_percentage:.2f}"

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
            'usd_value': buy_usd_value,
            'sell_price': Decimal(str(sell_result['price'])),
            'sell_usd_value': Decimal(str(sell_result['usd_value'])),
            'commission': Decimal(str(sell_result.get('commission', '0'))),
            'commission_asset': sell_result.get('commission_asset'),
            'timestamp': datetime.utcfromtimestamp(sell_result['timestamp'] / 1000).replace(tzinfo=timezone.utc),
            'exchange_order_id': sell_result.get('exchange_order_id'),
            'binance_trade_id': sell_result.get('binance_trade_id'),
            'decision_context': decision_context,
            'realized_pnl_usd': realized_pnl_usd,
        }

        self.trade_logger.log_trade(sell_data)
        logger.info(f"Created new SELL record {sell_trade_id} for forced sell of {trade_id} with PnL: ${realized_pnl_usd:.2f}.")

        # 2. Update the original 'buy' trade to be closed
        self.db_manager.update_trade_status(trade_id, 'CLOSED')
        logger.info(f"Updated original BUY record {trade_id} status to 'CLOSED'.")
