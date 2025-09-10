import datetime
import uuid
import math
from decimal import Decimal
from binance.client import Client
from binance.exceptions import BinanceAPIException
from jules_bot.core.schemas import TradePoint
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.logger import logger
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.database.models import Trade
from jules_bot.services.trade_logger import TradeLogger
from jules_bot.utils.config_manager import config_manager


class SynchronizationManager:
    """
    Handles the synchronization of trade history between Binance and the local database.
    Ensures that the local state is a faithful mirror of the exchange's history.
    """
    def __init__(self, binance_client: Client, db_manager: PostgresManager, symbol: str, strategy_rules: StrategyRules, environment: str = 'live'):
        """
        Initializes the SynchronizationManager.
        """
        self.client = binance_client
        self.db = db_manager
        self.symbol = symbol
        self.environment = environment
        self.strategy_rules = strategy_rules
        self.base_asset = symbol.replace("USDT", "")
        self.trade_logger = TradeLogger(mode=self.environment, db_manager=self.db)
        self.run_id = config_manager.get('APP', 'run_id', fallback='sync_run')
        logger.info("SynchronizationManager initialized.")

    def run_full_sync(self):
        """
        Synchronizes the bot's state with the exchange using a three-pass approach.
        1. Mirror Pass: Ensures every trade from the exchange exists in the local DB.
        2. Linking Pass: Links sell trades to their corresponding buy trades (non-destructive).
        3. Status Sync Pass: Updates local trade statuses based on the live exchange balance (destructive).
        """
        logger.info("--- Starting State Synchronization (Two-Pass) ---")
        try:
            if not self.symbol:
                logger.error("No symbol configured. Cannot perform sync.")
                return

            all_binance_trades = self._fetch_all_binance_trades()
            if all_binance_trades is None:
                logger.error("Failed to fetch trades from Binance. Aborting sync.")
                return

            # --- Pass 1: Mirroring ---
            logger.info("[Sync Pass 1/2] Mirroring exchange trades to local DB...")
            self._mirror_binance_trades(all_binance_trades)
            logger.info("[Sync Pass 1/2] Mirroring complete.")

            # --- Pass 2: Reconciliation (Phase 1 - Linking) ---
            logger.info("[Sync Pass 2/3] Linking sell trades to buys...")
            self._reconcile_local_state(all_binance_trades)
            logger.info("[Sync Pass 2/3] Linking complete.")

            # --- Pass 3: Reconciliation (Phase 2 - Status Sync) ---
            logger.info("[Sync Pass 3/3] Synchronizing open position status with exchange balance...")
            self._sync_open_positions_status()
            logger.info("[Sync Pass 3/3] Status sync complete.")

            logger.info("--- State Synchronization Finished ---")

        except Exception as e:
            logger.critical(f"A critical error occurred during state synchronization: {e}", exc_info=True)

    def _mirror_binance_trades(self, all_binance_trades: list):
        """
        Ensures that every trade from Binance has a corresponding record in the local database.
        """
        db_trade_ids = {t.binance_trade_id for t in self.db.get_all_trades_for_sync(self.environment, self.symbol)}
        
        trades_to_add = []
        for trade in all_binance_trades:
            if trade['id'] not in db_trade_ids:
                trades_to_add.append(trade)

        if not trades_to_add:
            logger.info("No new trades from exchange to mirror. Local DB is up to date.")
            return

        logger.info(f"Found {len(trades_to_add)} new trades on the exchange to be mirrored locally.")
        all_prices = self.client.get_all_tickers()
        all_prices = {item['symbol']: item['price'] for item in all_prices}

        for trade in trades_to_add:
            if trade['isBuyer']:
                # This is a new buy trade not seen before. Adopt it as 'OPEN'.
                self._create_position_from_binance_trade(trade, all_prices, "OPEN")
            else:
                # This is a new sell trade. We can't link it yet, so log it as unlinked.
                # The reconciliation pass will handle the linking.
                self._create_unlinked_sell_record(trade, all_prices)

    def _reconcile_local_state(self, all_binance_trades: list):
        """
        (Phase 1 of Reconciliation)
        Links sell trades to their corresponding buy trades using FIFO logic.
        This method is non-destructive; it only establishes links and does not
        change the status or quantity of any trade.
        """
        db_trades = self.db.get_all_trades_for_sync(environment=self.environment, symbol=self.symbol)
        db_trades_map = {t.binance_trade_id: t for t in db_trades if t.binance_trade_id}
        
        buys = sorted([t for t in all_binance_trades if t['isBuyer']], key=lambda t: t['time'])
        sells = sorted([t for t in all_binance_trades if not t['isBuyer']], key=lambda t: t['time'])

        if not sells:
            logger.info("Reconciliation (Linker): No sells found, nothing to link.")
            return

        logger.info(f"Reconciliation (Linker): Attempting to link {len(sells)} sells to {len(buys)} buys.")

        # Create a pool of buy quantities that can be consumed by sells
        buy_pool = {buy['id']: Decimal(str(buy['qty'])) for buy in buys}
        
        link_updates = 0
        for sell in sells:
            sell_qty_to_match = Decimal(str(sell['qty']))
            local_sell = db_trades_map.get(sell['id'])

            # Skip if sell is not in DB or already linked
            if not local_sell or local_sell.linked_trade_id:
                continue

            for buy in buys:
                if sell_qty_to_match <= Decimal('0'):
                    break # This sell has been fully matched

                buy_id = buy['id']
                if buy_pool.get(buy_id, Decimal('0')) > Decimal('0'):
                    matched_qty = min(sell_qty_to_match, buy_pool[buy_id])
                    
                    buy_pool[buy_id] -= matched_qty
                    sell_qty_to_match -= matched_qty
                    
                    local_buy = db_trades_map.get(buy_id)
                    if local_buy:
                        # Link the sell to this buy. 
                        # For simplicity, we link a sell to the first buy it matches with.
                        # Complex partial fills could be handled by a separate linking table if needed.
                        logger.info(f"Linking sell {local_sell.trade_id} (BinanceID: {sell['id']}) to buy {local_buy.trade_id} (BinanceID: {buy_id}).")
                        self.db.update_trade(local_sell.trade_id, {'linked_trade_id': local_buy.trade_id})
                        link_updates += 1
                        # Once linked, break to the next sell
                        break 
        
        if link_updates > 0:
            logger.info(f"Reconciliation (Linker): Successfully created {link_updates} new trade links.")

    def _sync_open_positions_status(self):
        """
        (Phase 2 of Reconciliation)
        Ensures the status of local 'OPEN' trades matches the reality of the exchange account balance.
        This is the only function that should change a trade's status to 'CLOSED'.
        """
        logger.info("Status Sync: Fetching current exchange balance...")
        try:
            account_info = self.client.get_account()
            balance_info = next((item for item in account_info['balances'] if item['asset'] == self.base_asset), None)
            
            # Use a small tolerance for dust
            exchange_balance = Decimal(balance_info['free']) + Decimal(balance_info['locked']) if balance_info else Decimal('0')
            logger.info(f"Status Sync: Current exchange balance for {self.base_asset} is {exchange_balance:.8f}")

        except Exception as e:
            logger.error(f"Status Sync: Could not fetch account balance from Binance: {e}. Aborting status sync to be safe.", exc_info=True)
            return

        local_open_trades = self.db.get_open_positions(self.environment, self.symbol)
        if not local_open_trades:
            logger.info("Status Sync: No open positions found in the local database.")
            # If we have a balance on the exchange but no local trades, it's a discrepancy, but nothing to "close".
            if exchange_balance > Decimal('0.00001'):
                 logger.warning(f"Status Sync: Discrepancy detected. Exchange balance is {exchange_balance:.8f} but no open trades are in the DB.")
            return

        # Sort trades by timestamp, oldest first, to close them in FIFO order if needed
        local_open_trades.sort(key=lambda t: t.timestamp)
        
        local_total_quantity = sum(Decimal(str(t.quantity)) for t in local_open_trades)
        logger.info(f"Status Sync: Found {len(local_open_trades)} open trades in DB with a total quantity of {local_total_quantity:.8f}")

        # Using a tolerance for floating point comparisons
        if math.isclose(local_total_quantity, exchange_balance, rel_tol=1e-9):
            logger.info("Status Sync: Local state matches exchange balance. No status changes needed.")
            return

        if local_total_quantity > exchange_balance:
            qty_to_close = local_total_quantity - exchange_balance
            logger.warning(f"Status Sync: Local quantity ({local_total_quantity:.8f}) is greater than exchange balance ({exchange_balance:.8f}).\n"
                           f"This means ~{qty_to_close:.8f} {self.base_asset} was sold outside the bot's knowledge. Closing oldest trades...")
            
            closed_count = 0
            for trade in local_open_trades:
                if qty_to_close <= Decimal('0'):
                    break
                
                trade_qty = Decimal(str(trade.quantity))
                
                # This trade needs to be fully or partially closed
                close_amount = min(trade_qty, qty_to_close)
                
                # For now, we only support closing full trades for simplicity.
                # If a partial close is needed, we close the entire trade and log a warning.
                if close_amount > 0:
                    logger.warning(f"Status Sync: Closing trade {trade.trade_id} (Qty: {trade_qty}) to reconcile account balance.")
                    self.db.update_trade_status(trade.trade_id, "CLOSED")
                    self._calculate_and_update_realized_pnl(trade)
                    qty_to_close -= trade_qty
                    closed_count += 1
            
            logger.info(f"Status Sync: Closed {closed_count} trades to align with exchange balance.")

        elif exchange_balance > local_total_quantity:
            logger.warning(f"Status Sync: Exchange balance ({exchange_balance:.8f}) is greater than local open quantity ({local_total_quantity:.8f}).\n"
                           f"This may indicate a buy happened outside the bot. A new 'sync_adopted_buy' trade should have been created in the mirror pass.")

    def _calculate_and_update_realized_pnl(self, closed_buy_trade: Trade):
        """
        Calculates the realized PnL for a given buy trade that has just been closed
        and updates the corresponding linked sell trade in the database.
        """
        sell_trade = self.db.find_linked_sell_trade(closed_buy_trade.trade_id)
        if not sell_trade:
            logger.warning(f"PnL Calc: Could not find a linked sell trade for closed buy {closed_buy_trade.trade_id}. PnL will not be calculated at this time. It may be calculated on a future run once the sell is synced.")
            return

        # Ensure the sell trade doesn't already have PnL calculated
        if sell_trade.realized_pnl_usd is not None and sell_trade.realized_pnl_usd != 0:
            logger.info(f"PnL Calc: PnL for sell trade {sell_trade.trade_id} is already calculated. Skipping.")
            return

        buy_price = Decimal(str(closed_buy_trade.price))
        sell_price = Decimal(str(sell_trade.price))
        quantity = Decimal(str(closed_buy_trade.quantity)) # Assuming the full quantity was sold
        buy_commission = Decimal(str(closed_buy_trade.commission_usd))
        sell_commission = Decimal(str(sell_trade.commission_usd))

        realized_pnl = self.strategy_rules.calculate_realized_pnl(
            buy_price=buy_price,
            sell_price=sell_price,
            quantity_sold=quantity,
            buy_commission_usd=buy_commission,
            sell_commission_usd=sell_commission,
            buy_quantity=quantity
        )
        
        logger.info(f"PnL Calc: Calculated realized PnL of ${realized_pnl:.4f} for sell trade {sell_trade.trade_id}.")
        
        # Update the sell trade with the calculated PNL
        update_data = {'realized_pnl_usd': realized_pnl}
        self.db.update_trade(sell_trade.trade_id, update_data)
        logger.info(f"PnL Calc: Updated sell trade {sell_trade.trade_id} with realized PnL.")


    def _fetch_all_binance_trades(self) -> list:
        logger.info(f"Fetching all trades from Binance for symbol {self.symbol}...")
        all_trades = []
        from_id = 0
        limit = 1000
        while True:
            try:
                trades = self.client.get_my_trades(symbol=self.symbol, fromId=from_id, limit=limit)
                if not trades: break
                all_trades.extend(trades)
                from_id = trades[-1]['id'] + 1
                if len(trades) < limit: break
            except BinanceAPIException as e:
                logger.error(f"Binance API error while fetching trades: {e}", exc_info=True)
                return None
            except Exception as e:
                logger.error(f"An unexpected error occurred while fetching trades: {e}", exc_info=True)
                return None
        logger.info(f"Finished fetching. Total trades retrieved: {len(all_trades)}")
        return all_trades

    def _calculate_commission_in_usd(self, commission: Decimal, asset: str, price: Decimal, all_prices: dict) -> Decimal:
        if commission <= Decimal('0'): return Decimal('0')
        if asset == 'USDT': return commission
        if asset == self.base_asset: return commission * price

        asset_price_symbol = f"{asset}USDT"
        asset_price = all_prices.get(asset_price_symbol)
        if asset_price:
            return commission * Decimal(str(asset_price))

        logger.warning(f"Could not find price for commission asset '{asset}'. Commission calculation may be inaccurate.")
        return Decimal('0')

    def _create_position_from_binance_trade(self, binance_trade: dict, all_prices: dict, final_status: str):
        try:
            purchase_price = Decimal(str(binance_trade['price']))
            quantity = Decimal(str(binance_trade['qty']))
            commission = Decimal(str(binance_trade['commission']))
            commission_asset = binance_trade['commissionAsset']

            commission_usd = self._calculate_commission_in_usd(commission, commission_asset, purchase_price, all_prices)
            sell_target_price = self.strategy_rules.calculate_sell_target_price(purchase_price, quantity, params=None)

            trade_data = {
                "run_id": self.run_id,
                "trade_id": f"sync_{uuid.uuid4()}",
                "symbol": self.symbol,
                "price": purchase_price,
                "quantity": quantity,
                "usd_value": purchase_price * quantity,
                "commission": commission,
                "commission_asset": commission_asset,
                "commission_usd": commission_usd,
                "exchange_order_id": str(binance_trade['orderId']),
                "binance_trade_id": int(binance_trade['id']),
                "timestamp": datetime.datetime.fromtimestamp(binance_trade['time'] / 1000, tz=datetime.timezone.utc),
                "decision_context": {"reason": "sync_adopted_buy"},
                "environment": self.environment,
                "status": final_status,
                "order_type": "buy",
                "sell_target_price": sell_target_price
            }
            self.trade_logger.log_trade(trade_data)
        except Exception as e:
            logger.error(f"Failed to create position from trade {binance_trade.get('id')}: {e}", exc_info=True)

    def _create_unlinked_sell_record(self, sell_trade: dict, all_prices: dict):
        try:
            sell_price = Decimal(str(sell_trade['price']))
            quantity = Decimal(str(sell_trade['qty']))
            commission = Decimal(str(sell_trade['commission']))
            commission_asset = sell_trade['commissionAsset']

            commission_usd = self._calculate_commission_in_usd(commission, commission_asset, sell_price, all_prices)

            trade_data = {
                'run_id': self.run_id, 'environment': self.environment,
                'strategy_name': 'sync', 'symbol': self.symbol,
                'trade_id': f"sync_{uuid.uuid4()}", 'linked_trade_id': None,
                'exchange': 'binance', 'status': 'CLOSED', 'order_type': 'sell',
                'price': sell_price, 'quantity': quantity,
                'usd_value': sell_price * quantity,
                'sell_price': sell_price, 'sell_usd_value': sell_price * quantity,
                'commission': commission, 'commission_asset': commission_asset,
                'commission_usd': commission_usd,
                'timestamp': datetime.datetime.fromtimestamp(sell_trade['time'] / 1000, tz=datetime.timezone.utc),
                'exchange_order_id': str(sell_trade['orderId']),
                'binance_trade_id': int(sell_trade['id']),
                'decision_context': {'reason': 'sync_unlinked_sell'},
                'realized_pnl_usd': 0
            }
            self.trade_logger.log_trade(trade_data)
        except Exception as e:
            logger.error(f"Failed to create unlinked sell record from sync: {e}", exc_info=True)
