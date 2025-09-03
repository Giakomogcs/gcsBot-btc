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
        Runs the full synchronization process, prioritizing position sync and then trade history.
        """
        logger.info("Starting full synchronization...")

        # First, synchronize the current open positions
        self.sync_positions()

        # Then, reconcile the trade history for logging and PnL calculation
        last_synced_id = self.db.get_last_binance_trade_id()
        trades_from_binance = self._fetch_all_binance_trades(start_from_id=last_synced_id + 1)
        
        if trades_from_binance:
            self._reconcile_trades(trades_from_binance)
        
        logger.info("Full synchronization process complete.")

    def sync_positions(self):
        """
        Synchronizes the bot's open positions with the actual balance on the exchange.
        This method is the source of truth for the bot's state.
        It will adopt, update, or close local positions to match the exchange exactly.
        """
        logger.info(f"Starting position synchronization for {self.symbol}...")
        try:
            # 1. Get quantity from the exchange
            asset_balance = self.client.get_asset_balance(asset=self.base_asset)
            exchange_quantity = Decimal(asset_balance['free']) if asset_balance and 'free' in asset_balance else Decimal("0")
            logger.info(f"Exchange balance for {self.base_asset}: {exchange_quantity}")

            # 2. Get quantity from local DB
            local_quantity = self.db.get_total_open_quantity(self.symbol)
            logger.info(f"Local open quantity for {self.symbol}: {local_quantity}")

            # 3. Reconcile
            if exchange_quantity == local_quantity:
                logger.info(f"Quantities for {self.symbol} are in sync. No action needed.")
                return

            logger.warning(f"Discrepancy detected for {self.symbol}. Exchange: {exchange_quantity}, Local: {local_quantity}. Reconciling...")

            # If there's any discrepancy, the simplest and most robust approach is to
            # make the local state match the exchange state.

            # First, wipe the slate clean locally.
            self._close_all_local_positions()

            # If there's a position on the exchange, adopt it.
            if exchange_quantity > 0:
                self._adopt_position(exchange_quantity)

        except BinanceAPIException as e:
            logger.error(f"Binance API error during position sync for {self.base_asset}: {e}", exc_info=True)
            return
        except Exception as e:
            logger.error(f"An unexpected error occurred during position sync: {e}", exc_info=True)
            return

    def _adopt_position(self, quantity_to_adopt: Decimal):
        """
        Adopts a position from the exchange by calculating its average entry price
        from trade history and creating a single representative trade in the local DB.
        This uses a FIFO accounting method to determine the cost basis.
        """
        logger.info(f"Attempting to adopt position of {quantity_to_adopt} {self.base_asset}.")

        try:
            # 1. Fetch trade history
            all_trades = self.client.get_my_trades(symbol=self.symbol, limit=1000)
            if not all_trades:
                logger.error("Cannot adopt position: No trade history found for symbol.")
                return

            # 2. Reconstruct current position using FIFO
            inventory = []  # Stores the buy trades that constitute the current position
            for trade in all_trades:
                if trade['isBuyer']:
                    inventory.append(trade)
                else:  # It's a sell
                    sell_qty = Decimal(trade['qty'])
                    # Deduct sell quantity from the oldest buys first
                    while sell_qty > 0 and inventory:
                        oldest_buy = inventory[0]
                        oldest_buy_qty = Decimal(oldest_buy['qty'])

                        if oldest_buy_qty > sell_qty:
                            # The oldest buy partially covers the sell
                            oldest_buy['qty'] = str(oldest_buy_qty - sell_qty)
                            sell_qty = Decimal('0')
                        else:
                            # The oldest buy is completely used up by the sell
                            inventory.pop(0)
                            sell_qty -= oldest_buy_qty

            if not inventory:
                logger.error("Cannot adopt position: Inventory calculation resulted in zero holdings, which contradicts exchange balance.")
                return

            # 3. Calculate weighted average price from the remaining inventory
            total_cost = Decimal('0')
            total_qty = Decimal('0')
            for buy_trade in inventory:
                price = Decimal(buy_trade['price'])
                qty = Decimal(buy_trade['qty'])
                total_cost += price * qty
                total_qty += qty

            if total_qty == 0:
                logger.error("Cannot adopt position: Calculated total quantity is zero.")
                return

            avg_price = total_cost / total_qty
            logger.info(f"Calculated average entry price for adoption: {avg_price:.8f}")

            # 4. Create the new adopted trade in the database
            # The quantity is the one from get_asset_balance, which is the ultimate source of truth.
            # The calculated average price is for this true quantity.
            new_trade = TradePoint(
                run_id="adopted",
                environment=self.environment,
                strategy_name="adopted",
                symbol=self.symbol,
                trade_id=f"adopted_{uuid.uuid4()}",
                exchange="binance",
                status="OPEN",
                order_type='buy',
                price=float(avg_price),
                quantity=float(quantity_to_adopt),
                usd_value=float(avg_price * quantity_to_adopt),
                commission=0.0,  # Placeholder, as commissions are part of the historical price
                commission_asset='USDT',
                timestamp=datetime.datetime.now(datetime.timezone.utc),  # Timestamp of adoption
                decision_context={'source': 'adoption', 'reason': 'Adopting existing position from exchange.'}
            )
            self.db.log_trade(new_trade)
            logger.info(f"Successfully adopted position for {self.symbol} with trade_id {new_trade.trade_id}.")

        except BinanceAPIException as e:
            logger.error(f"Binance API error during position adoption for {self.symbol}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"An unexpected error occurred during position adoption: {e}", exc_info=True)

    def _close_all_local_positions(self):
        """
        Closes all open 'buy' trades for the current symbol in the local database.
        """
        logger.info(f"Closing all local open positions for {self.symbol} as part of sync.")
        open_trades = self.db.get_open_buy_trades_sorted(self.symbol)

        if not open_trades:
            logger.info(f"No local open positions found for {self.symbol} to close.")
            return

        for trade in open_trades:
            # Using a specific status for traceability
            self.db.update_trade_status(trade.trade_id, "CLOSED_BY_SYNC")
            logger.info(f"Closed local trade {trade.trade_id} (qty: {trade.quantity}) to sync with exchange.")

        logger.info(f"Finished closing {len(open_trades)} local positions for {self.symbol}.")

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

            # The new sync_positions logic is the source of truth for the state of open positions.
            # Here, we just log the trade from history for completeness, without trying to
            # affect the state of any open positions.
            # The status ('OPEN' or 'CLOSED') is correctly set in _convert_binance_trade_to_tradepoint.
            self.db.log_trade(trade_point)

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
