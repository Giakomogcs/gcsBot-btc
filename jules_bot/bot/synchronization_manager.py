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
    REFACTORED to be event-driven and handle PnL for external trades.
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
        Synchronizes the bot's state with the exchange using an event-driven approach.
        It processes trades from the exchange and reconciles them against the local state.
        """
        logger.info("--- Starting State Synchronization (Event-Driven) ---")
        try:
            if not self.symbol:
                logger.error("No symbol configured. Cannot perform sync.")
                return

            all_binance_trades = self._fetch_all_binance_trades()
            if all_binance_trades is None:
                logger.error("Failed to fetch trades from Binance. Aborting sync.")
                return

            local_trades = self.db.get_all_trades_for_sync(self.environment, self.symbol)
            local_binance_trade_ids = {t.binance_trade_id for t in local_trades if t.binance_trade_id}

            all_prices = {item['symbol']: item['price'] for item in self.client.get_all_tickers()}
            
            new_trades_from_binance = [t for t in all_binance_trades if t['id'] not in local_binance_trade_ids]
            
            if not new_trades_from_binance:
                logger.info("No new trades from exchange to process. Local DB is up to date.")
            else:
                logger.info(f"Found {len(new_trades_from_binance)} new trades on the exchange to process.")
                new_trades_from_binance.sort(key=lambda t: t['time'])

                for trade in new_trades_from_binance:
                    if trade['isBuyer']:
                        self._create_position_from_binance_trade(trade, all_prices, "OPEN")
                    else:
                        self._reconcile_external_sell(trade, all_prices)
            
            self._final_balance_sanity_check()
            logger.info("--- State Synchronization Finished ---")

        except Exception as e:
            logger.critical(f"A critical error occurred during state synchronization: {e}", exc_info=True)

    def _reconcile_external_sell(self, sell_trade_data: dict, all_prices: dict):
        """
        Reconciles a sell trade that occurred outside the bot.
        It finds the corresponding open buy positions, calculates PnL,
        creates a local sell record, and updates the buy positions' remaining quantities.
        """
        sell_id = sell_trade_data['id']
        sell_qty_to_match = Decimal(str(sell_trade_data['qty']))
        sell_price = Decimal(str(sell_trade_data['price']))
        logger.info(f"-> Reconciling external sell (Binance Trade ID: {sell_id}, Qty: {sell_qty_to_match}, Price: {sell_price})")
        sell_commission = Decimal(str(sell_trade_data['commission']))
        sell_commission_asset = sell_trade_data['commissionAsset']
        
        open_buys = self.db.get_open_positions(self.environment, self.symbol)
        open_buys.sort(key=lambda t: t.timestamp)

        if not open_buys:
            logger.warning(f"Found an external sell (ID: {sell_trade_data['id']}) but no open buy positions to match it against. Logging as unlinked.")
            self._create_unlinked_sell_record(sell_trade_data, all_prices)
            return

        for buy_trade in open_buys:
            if sell_qty_to_match <= Decimal('1e-9'):
                break

            if buy_trade.remaining_quantity > Decimal('1e-9'):
                qty_to_sell_from_this_buy = min(sell_qty_to_match, buy_trade.remaining_quantity)
                
                sell_commission_usd = self._calculate_commission_in_usd(sell_commission, sell_commission_asset, sell_price, all_prices)
                
                # Pro-rate commissions for accurate PnL
                prorated_sell_commission = (sell_commission_usd / Decimal(str(sell_trade_data['qty']))) * qty_to_sell_from_this_buy if Decimal(str(sell_trade_data['qty'])) > 0 else Decimal('0')
                prorated_buy_commission = (buy_trade.commission_usd / buy_trade.quantity) * qty_to_sell_from_this_buy if buy_trade.quantity > 0 else Decimal('0')

                realized_pnl = self.strategy_rules.calculate_realized_pnl(
                    buy_price=buy_trade.price,
                    sell_price=sell_price,
                    quantity_sold=qty_to_sell_from_this_buy,
                    buy_commission_usd=prorated_buy_commission,
                    sell_commission_usd=prorated_sell_commission,
                    buy_quantity=buy_trade.quantity
                )

                new_sell_trade_data = {
                    'run_id': self.run_id, 'environment': self.environment,
                    'strategy_name': 'sync_external', 'symbol': self.symbol,
                    'trade_id': f"sync_sell_{uuid.uuid4()}", 'linked_trade_id': buy_trade.trade_id,
                    'exchange': 'binance', 'status': 'CLOSED', 'order_type': 'sell',
                    'price': sell_price, 'quantity': qty_to_sell_from_this_buy,
                    'usd_value': sell_price * qty_to_sell_from_this_buy,
                    'commission': (sell_commission / Decimal(str(sell_trade_data['qty']))) * qty_to_sell_from_this_buy if Decimal(str(sell_trade_data['qty'])) > 0 else Decimal('0'),
                    'commission_asset': sell_commission_asset, 'commission_usd': prorated_sell_commission,
                    'timestamp': datetime.datetime.fromtimestamp(sell_trade_data['time'] / 1000, tz=datetime.timezone.utc),
                    'exchange_order_id': str(sell_trade_data['orderId']),
                    'binance_trade_id': int(sell_trade_data['id']),
                    'decision_context': {'reason': 'sync_reconciled_external_sell'},
                    'realized_pnl_usd': realized_pnl
                }
                self.trade_logger.log_trade(new_sell_trade_data)

                new_remaining_qty = buy_trade.remaining_quantity - qty_to_sell_from_this_buy
                update_payload = {'remaining_quantity': new_remaining_qty}
                
                log_msg = (
                    f"   - Matched {qty_to_sell_from_this_buy:.8f} qty against Buy Trade ID: {str(buy_trade.trade_id)} "
                    f"(bought at ${Decimal(buy_trade.price):.4f})"
                )
                logger.info(log_msg)
                logger.info(f"   - Calculated Realized PnL for this portion: {float(realized_pnl):.4f}")

                if new_remaining_qty <= Decimal('1e-8'):
                    update_payload['status'] = 'CLOSED'
                    logger.info(f"   - Buy Trade {buy_trade.trade_id} is now fully closed.")
                else:
                    logger.info(f"   - Buy Trade {buy_trade.trade_id} has new remaining quantity: {new_remaining_qty:.8f}")

                self.db.update_trade(buy_trade.trade_id, update_payload)
                
                sell_qty_to_match -= qty_to_sell_from_this_buy

    def _final_balance_sanity_check(self):
        """
        A final check to ensure the sum of local remaining quantities matches the exchange balance.
        If not, it logs a warning, as this indicates a non-trade event like a deposit or withdrawal.
        """
        logger.info("Performing final balance sanity check...")
        try:
            account_info = self.client.get_account()
            balance_info = next((item for item in account_info['balances'] if item['asset'] == self.base_asset), None)
            exchange_balance = Decimal(balance_info['free']) + Decimal(balance_info['locked']) if balance_info else Decimal('0')
            
            local_open_trades = self.db.get_open_positions(self.environment, self.symbol)
            local_total_remaining_quantity = sum(t.remaining_quantity for t in local_open_trades)
            
            tolerance = Decimal('0.00000001')
            if abs(local_total_remaining_quantity - exchange_balance) > tolerance:
                discrepancy = exchange_balance - local_total_remaining_quantity
                logger.warning(
                    f"FINAL SANITY CHECK FAILED: Discrepancy of {discrepancy:.8f} {self.base_asset} found between "
                    f"local state ({local_total_remaining_quantity:.8f}) and exchange balance ({exchange_balance:.8f}). "
                    "This may be due to a recent deposit or withdrawal. Manual review advised."
                )
            else:
                logger.info("Final balance sanity check passed. Local state is aligned with exchange balance.")
        except Exception as e:
            logger.error(f"Could not perform final balance sanity check: {e}", exc_info=True)

    def _calculate_and_update_realized_pnl(self, closed_buy_trade: Trade):
        sell_trade = self.db.find_linked_sell_trade(closed_buy_trade.trade_id)
        if not sell_trade:
            return
        if sell_trade.realized_pnl_usd is not None and sell_trade.realized_pnl_usd != 0:
            return

        buy_price = Decimal(str(closed_buy_trade.price))
        sell_price = Decimal(str(sell_trade.price))
        quantity = Decimal(str(closed_buy_trade.quantity))
        buy_commission = Decimal(str(closed_buy_trade.commission_usd))
        sell_commission = Decimal(str(sell_trade.commission_usd))

        realized_pnl = self.strategy_rules.calculate_realized_pnl(
            buy_price=buy_price, sell_price=sell_price, quantity_sold=quantity,
            buy_commission_usd=buy_commission, sell_commission_usd=sell_commission,
            buy_quantity=quantity
        )
        self.db.update_trade(sell_trade.trade_id, {'realized_pnl_usd': realized_pnl})

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
        logger.warning(f"Could not find price for commission asset '{asset}'.")
        return Decimal('0')

    def _create_position_from_binance_trade(self, binance_trade: dict, all_prices: dict, final_status: str):
        purchase_price = Decimal(str(binance_trade['price']))
        quantity = Decimal(str(binance_trade['qty']))
        commission = Decimal(str(binance_trade['commission']))
        commission_asset = binance_trade['commissionAsset']
        commission_usd = self._calculate_commission_in_usd(commission, commission_asset, purchase_price, all_prices)
        sell_target_price = self.strategy_rules.calculate_sell_target_price(purchase_price, quantity, params=None)
        trade_data = {
            "run_id": self.run_id, "trade_id": f"sync_{uuid.uuid4()}", "symbol": self.symbol,
            "price": purchase_price, "quantity": quantity, "usd_value": purchase_price * quantity,
            "commission": commission, "commission_asset": commission_asset, "commission_usd": commission_usd,
            "exchange_order_id": str(binance_trade['orderId']), "binance_trade_id": int(binance_trade['id']),
            "timestamp": datetime.datetime.fromtimestamp(binance_trade['time'] / 1000, tz=datetime.timezone.utc),
            "decision_context": {"reason": "sync_adopted_buy"}, "environment": self.environment,
            "status": final_status, "order_type": "buy", "sell_target_price": sell_target_price
        }
        self.trade_logger.log_trade(trade_data)

    def _create_unlinked_sell_record(self, sell_trade: dict, all_prices: dict):
        sell_price = Decimal(str(sell_trade['price']))
        quantity = Decimal(str(sell_trade['qty']))
        commission = Decimal(str(sell_trade['commission']))
        commission_asset = sell_trade['commissionAsset']
        commission_usd = self._calculate_commission_in_usd(commission, commission_asset, sell_price, all_prices)
        trade_data = {
            'run_id': self.run_id, 'environment': self.environment, 'strategy_name': 'sync',
            'symbol': self.symbol, 'trade_id': f"sync_{uuid.uuid4()}", 'linked_trade_id': None,
            'exchange': 'binance', 'status': 'CLOSED', 'order_type': 'sell',
            'price': sell_price, 'quantity': quantity, 'usd_value': sell_price * quantity,
            'sell_price': sell_price, 'sell_usd_value': sell_price * quantity,
            'commission': commission, 'commission_asset': commission_asset, 'commission_usd': commission_usd,
            'timestamp': datetime.datetime.fromtimestamp(sell_trade['time'] / 1000, tz=datetime.timezone.utc),
            'exchange_order_id': str(sell_trade['orderId']), 'binance_trade_id': int(sell_trade['id']),
            'decision_context': {'reason': 'sync_unlinked_sell'}, 'realized_pnl_usd': 0
        }
        self.trade_logger.log_trade(trade_data)
