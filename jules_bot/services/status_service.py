import logging
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core.market_data_provider import MarketDataProvider
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)

def _calculate_progress_pct(current_price, start_price, target_price):
    if target_price == start_price:
        return 100.0 if current_price >= target_price else 0.0
    if target_price is None or start_price is None or current_price is None:
        return 0.0

    progress = (current_price - start_price) / (target_price - start_price) * 100
    return max(0, min(progress, 100))

class StatusService:
    def __init__(self, db_manager: PostgresManager, config_manager: ConfigManager, market_data_provider: MarketDataProvider):
        self.db_manager = db_manager
        self.strategy = StrategyRules(config_manager)
        self.market_data_provider = market_data_provider

    def get_reconciled_open_positions(self, exchange_manager: ExchangeManager, environment: str, bot_id: str, current_price: float):
        """
        Fetches open positions from the DB, reconciles them with the exchange,
        and calculates PnL and progress.
        """
        symbol = "BTCUSDT"
        open_positions_db = self.db_manager.get_open_positions(environment, bot_id)

        try:
            live_open_orders = exchange_manager.get_open_orders(symbol)
            live_open_order_ids = {str(order['orderId']) for order in live_open_orders}
        except Exception as e:
            logger.error(f"Could not fetch open orders from exchange: {e}")
            # If exchange fails, we can't reconcile. Return an empty list or handle as appropriate.
            return []

        positions_status = []
        for trade in open_positions_db:
            if str(trade.exchange_order_id) not in live_open_order_ids:
                continue

            unrealized_pnl = (current_price - trade.price) * trade.quantity if current_price else 0
            progress_to_sell_target_pct = _calculate_progress_pct(
                current_price, trade.price, trade.sell_target_price
            )
            positions_status.append({
                "trade_id": trade.trade_id,
                "entry_price": trade.price,
                "current_price": current_price,
                "quantity": trade.quantity,
                "unrealized_pnl": unrealized_pnl,
                "sell_target_price": trade.sell_target_price,
                "progress_to_sell_target_pct": progress_to_sell_target_pct,
            })
        return positions_status

    def get_buy_signal_status(self, market_data: dict, open_positions_count: int):
        """
        Determines the buy signal status based on market data and open positions.
        """
        should_buy, _, reason = self.strategy.evaluate_buy_signal(market_data, open_positions_count)
        btc_purchase_target, btc_purchase_progress_pct = self._calculate_buy_progress(market_data, open_positions_count)

        return {
            "should_buy": should_buy,
            "reason": reason,
            "btc_purchase_target": btc_purchase_target,
            "btc_purchase_progress_pct": btc_purchase_progress_pct
        }

    def get_trade_history(self, environment: str):
        """
        Fetches trade history from the database.
        """
        trade_history = self.db_manager.get_all_trades_in_range(environment)
        return [trade.to_dict() for trade in trade_history]

    def get_wallet_balances(self, exchange_manager: ExchangeManager):
        """
        Fetches wallet balances from the exchange.
        """
        try:
            return exchange_manager.get_account_balance()
        except Exception as e:
            logger.error(f"Could not fetch wallet balances from exchange: {e}")
            return {} # Return empty dict on error

    def _calculate_buy_progress(self, market_data: dict, open_positions_count: int) -> tuple[float, float]:
        """
        Calculates the target price for the next buy and the progress towards it.
        """
        current_price = market_data.get('close')
        ema_20 = market_data.get('ema_20')
        bbl = market_data.get('bbl_20_2_0')
        ema_100 = market_data.get('ema_100')

        if any(v is None for v in [current_price, ema_20, bbl, ema_100]):
            return 0, 0

        if open_positions_count == 0:
            if current_price > ema_100: # Uptrend
                target_price = ema_20
                progress = 100.0 if current_price > target_price else \
                           _calculate_progress_pct(current_price, current_price * 1.05, target_price)
            else: # Downtrend
                target_price = bbl
                progress = _calculate_progress_pct(current_price, market_data.get('high', current_price), target_price)
            return target_price, progress

        if current_price > ema_100: # Uptrend pullback
            target_price = ema_20
            progress = _calculate_progress_pct(current_price, market_data.get('high', current_price), target_price)
        else: # Downtrend breakout
            target_price = bbl
            progress = _calculate_progress_pct(current_price, market_data.get('high', current_price), target_price)

        return target_price, progress
