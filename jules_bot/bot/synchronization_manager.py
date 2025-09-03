import datetime
import uuid
from decimal import Decimal
from binance.client import Client
from binance.exceptions import BinanceAPIException
from jules_bot.core.schemas import TradePoint
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.logger import logger
from jules_bot.core_logic.strategy_rules import StrategyRules

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
        logger.info("SynchronizationManager initialized.")

    def run_full_sync(self):
        """
        Runs the full synchronization process. It's idempotent and can be run safely multiple times.
        """
        logger.info("Starting full trade history synchronization...")
        
        # Get the ID of the last trade we successfully synced
        last_synced_id = self.db.get_last_binance_trade_id()
        
        # Fetch all trades from the exchange starting from the next ID
        # If last_synced_id is 0, this will fetch from id 1.
        trades_from_binance = self._fetch_all_binance_trades(start_from_id=last_synced_id + 1)
        
        if trades_from_binance:
            self._reconcile_trades(trades_from_binance)
        
        logger.info("Synchronization process complete.")

    def _fetch_all_binance_trades(self, start_from_id: int = 0) -> list:
        """
        Fetches all trades from Binance for the specified symbol, handling pagination.
        """
        logger.info(f"Fetching all trades from Binance for symbol {self.symbol} starting from tradeId {start_from_id}...")
        
        all_trades = []
        from_id = start_from_id
        
        while True:
            try:
                # Binance API can return up to 1000 trades per call
                trades = self.client.get_my_trades(symbol=self.symbol, fromId=from_id, limit=1000)
                
                if not trades:
                    logger.info("No more new trades to fetch from Binance.")
                    break
                
                all_trades.extend(trades)
                
                last_trade_id = trades[-1]['id']
                from_id = last_trade_id + 1
                
                logger.info(f"Fetched {len(trades)} trades. Last trade ID was {last_trade_id}. Next fromId will be {from_id}.")

            except BinanceAPIException as e:
                logger.error(f"Binance API error while fetching trades: {e}", exc_info=True)
                break
            except Exception as e:
                logger.error(f"An unexpected error occurred while fetching trades: {e}", exc_info=True)
                break
        
        logger.info(f"Finished fetching. Total new trades retrieved: {len(all_trades)}")
        return all_trades

    def _reconcile_trades(self, binance_trades: list):
        """
        Reconciles the fetched Binance trades with the local database.
        """
        logger.info(f"Reconciling {len(binance_trades)} trades with the database.")
        
        # Sort trades by time, just in case the API doesn't guarantee it
        sorted_trades = sorted(binance_trades, key=lambda t: t['time'])

        for trade in sorted_trades:
            # Idempotency check: Ensure we haven't processed this trade in a previous run
            existing_trade = self.db.get_trade_by_binance_trade_id(trade['id'])
            if existing_trade:
                logger.debug(f"Trade with Binance ID {trade['id']} already exists in DB. Skipping.")
                continue

            logger.info(f"Reconciling new trade. Binance ID: {trade['id']}, Side: {'BUY' if trade['isBuyer'] else 'SELL'}")

            trade_point = self._convert_binance_trade_to_tradepoint(trade)

            if trade['isBuyer']:
                # For a buy trade, log it as OPEN. Sells will close it later.
                self.db.log_trade(trade_point)
            else: 
                self._reconcile_sell_trade(trade_point)
    
    def _reconcile_sell_trade(self, sell_trade_point: TradePoint):
        """
        Handles the logic for linking a sell trade to a buy trade using FIFO.
        """
        open_buy_trade = self.db.get_oldest_open_buy_trade()

        if not open_buy_trade:
            logger.critical(
                f"CRITICAL INCONSISTENCY: Found a sell trade (Binance ID: {sell_trade_point.binance_trade_id}) "
                f"but there are NO open buy positions in the database. This sell cannot be linked."
            )
            # Log the sell without a link for data integrity.
            self.db.log_trade(sell_trade_point)
            return

        sell_trade_point.linked_trade_id = open_buy_trade.trade_id
        
        sell_qty = Decimal(str(sell_trade_point.quantity))
        buy_qty = Decimal(str(open_buy_trade.quantity))

        if sell_qty >= buy_qty:
            logger.info(
                f"Sell trade (Binance ID: {sell_trade_point.binance_trade_id}) closes buy trade "
                f"(Trade ID: {open_buy_trade.trade_id})."
            )
            self.db.update_trade_status(open_buy_trade.trade_id, "CLOSED")
            if sell_qty > buy_qty:
                logger.warning(
                    f"Sell quantity ({sell_qty}) is greater than the oldest open buy's quantity ({buy_qty}). "
                    f"This suggests a data discrepancy (e.g., manual trades). The buy position will be closed."
                )
        else:
            new_quantity = buy_qty - sell_qty
            logger.info(
                f"Sell trade (Binance ID: {sell_trade_point.binance_trade_id}) partially closes buy trade "
                f"(Trade ID: {open_buy_trade.trade_id}). Reducing quantity from {buy_qty} to {new_quantity}."
            )
            self.db.update_trade_quantity(open_buy_trade.trade_id, float(new_quantity))

        # Calculate PnL before logging the sell
        try:
            buy_commission_usd = self._calculate_commission_in_usd(
                price=open_buy_trade.price,
                commission=open_buy_trade.commission,
                commission_asset=open_buy_trade.commission_asset
            )
            sell_commission_usd = self._calculate_commission_in_usd(
                price=sell_trade_point.price,
                commission=sell_trade_point.commission,
                commission_asset=sell_trade_point.commission_asset
            )

            realized_pnl = self.strategy_rules.calculate_realized_pnl(
                buy_price=open_buy_trade.price,
                sell_price=sell_trade_point.price,
                quantity_sold=sell_qty,
                buy_commission_usd=buy_commission_usd,
                sell_commission_usd=sell_commission_usd,
                buy_quantity=buy_qty
            )
            sell_trade_point.realized_pnl_usd = realized_pnl
            logger.info(f"Calculated realized PnL for synced trade: ${realized_pnl:,.4f}")

        except Exception as e:
            logger.error(f"Failed to calculate PnL for synced sell trade (Binance ID: {sell_trade_point.binance_trade_id}): {e}", exc_info=True)


        # Log the sell trade to the database
        self.db.log_trade(sell_trade_point)

    def _calculate_commission_in_usd(self, price: Decimal, commission: Decimal, commission_asset: str) -> Decimal:
        """
        Calculates the value of the commission in USD.
        NOTE: This is a simplified version for sync. It doesn't handle historical BNB prices.
        """
        price = Decimal(str(price))
        commission = Decimal(str(commission))

        if commission_asset == "USDT":
            return commission
        if commission_asset == self.base_asset:
            return commission * price
        if commission_asset == "BNB":
            logger.warning("Commission in BNB detected during sync. Historical BNB price is not available. PnL may be slightly inaccurate.")
            # Fallback: Assume BNB price is correlated with the asset price for an approximation.
            # A more robust solution would require a historical price oracle for BNB.
            return commission * price # This is an approximation

        logger.warning(f"Unknown commission asset '{commission_asset}'. Returning 0 for commission USD.")
        return Decimal("0")


    def _convert_binance_trade_to_tradepoint(self, binance_trade: dict) -> TradePoint:
        """
        Maps a trade dictionary from the Binance API to the internal TradePoint schema.
        """
        is_buy = binance_trade['isBuyer']
        
        # Trades reconciled from history are not part of a specific strategy run
        return TradePoint(
            run_id="sync",
            environment=self.environment,
            strategy_name="sync",
            symbol=self.symbol,
            trade_id=f"sync_{uuid.uuid4()}", # Generate a new unique ID
            exchange="binance",
            status="CLOSED" if not is_buy else "OPEN",
            order_type='buy' if is_buy else 'sell',
            price=float(binance_trade['price']),
            quantity=float(binance_trade['qty']),
            usd_value=float(binance_trade['price']) * float(binance_trade['qty']),
            commission=float(binance_trade['commission']),
            commission_asset=binance_trade['commissionAsset'],
            timestamp=datetime.datetime.fromtimestamp(binance_trade['time'] / 1000, tz=datetime.timezone.utc),
            exchange_order_id=str(binance_trade['orderId']),
            binance_trade_id=int(binance_trade['id']),
            decision_context={'source': 'sync'}
        )
