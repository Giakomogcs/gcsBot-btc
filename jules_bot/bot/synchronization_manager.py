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
        Synchronizes the bot's state with the exchange using a two-pass approach.
        1. Mirror Pass: Ensures every trade from the exchange exists in the local DB.
        2. Reconciliation Pass: Updates the status and links of local trades based on a full FIFO simulation.
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

            # --- Pass 2: Reconciliation ---
            logger.info("[Sync Pass 2/2] Reconciling local trade state with exchange history...")
            self._reconcile_local_state(all_binance_trades)
            logger.info("[Sync Pass 2/2] Reconciliation complete.")

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
        Performs a full FIFO simulation on the exchange data and updates the local
        database records to match the simulated state (statuses, quantities, links).
        """
        db_trades = self.db.get_all_trades_for_sync(environment=self.environment, symbol=self.symbol)
        db_trades_map = {t.binance_trade_id: t for t in db_trades if t.binance_trade_id}

        if not all_binance_trades:
            logger.info("No trade history on Binance. Closing any locally open positions.")
            for pos in db_trades:
                if pos.status == "OPEN":
                    logger.warning(f"Closing stale local position {pos.trade_id} as no trades exist on Binance.")
                    self.db.update_trade_status(pos.trade_id, "CLOSED")
            return
        
        buys = sorted([t for t in all_binance_trades if t['isBuyer']], key=lambda t: t['time'])
        sells = sorted([t for t in all_binance_trades if not t['isBuyer']], key=lambda t: t['time'])

        buy_pool = {buy['id']: {**buy, 'remaining_qty': Decimal(str(buy['qty']))} for buy in buys}

        for sell in sells:
            sell_qty_to_match = Decimal(str(sell['qty']))
            for buy_id in sorted(buy_pool.keys()):
                if sell_qty_to_match <= Decimal('0'): break
                buy = buy_pool[buy_id]
                if buy['remaining_qty'] <= Decimal('0'): continue

                matched_qty = min(sell_qty_to_match, buy['remaining_qty'])
                if matched_qty > 0:
                    buy['remaining_qty'] -= matched_qty
                    sell_qty_to_match -= matched_qty

                    # Find the corresponding local sell and update its link
                    local_sell = db_trades_map.get(sell['id'])
                    local_buy = db_trades_map.get(buy_id)
                    if local_sell and local_buy:
                        if local_sell.linked_trade_id != local_buy.trade_id:
                             self.db.update_trade(local_sell.trade_id, {'linked_trade_id': local_buy.trade_id})
                    else:
                        logger.warning(f"Could not find local trade for sell {sell['id']} or buy {buy_id} during reconciliation linking.")


        # Finally, update the status and quantity of all local buy trades based on the simulation
        for buy_id, buy_state in buy_pool.items():
            final_quantity = buy_state['remaining_qty']
            is_open_on_binance = final_quantity > Decimal('1e-9')
            final_status = "OPEN" if is_open_on_binance else "CLOSED"

            db_trade = db_trades_map.get(buy_id)
            if db_trade:
                if db_trade.status != final_status or not math.isclose(Decimal(str(db_trade.quantity)), final_quantity, rel_tol=1e-9):
                    logger.info(f"Reconciling position {db_trade.trade_id} (BinanceID: {buy_id}): Status {db_trade.status}->{final_status}, Qty {db_trade.quantity}->{final_quantity:.8f}")
                    self.db.update_trade_status_and_quantity(db_trade.trade_id, final_status, final_quantity)
            else:
                # This case should ideally not be hit because the mirror pass should have created it.
                logger.error(f"Inconsistency detected: Buy trade {buy_id} exists on exchange but not in DB after mirror pass.")

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
