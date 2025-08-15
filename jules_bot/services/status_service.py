import logging
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator


logger = logging.getLogger(__name__)

def _calculate_progress_pct(current_price, start_price, target_price):
    if target_price is None or start_price is None or current_price is None:
        return 0.0
    if target_price == start_price:
        return 100.0 if current_price >= target_price else 0.0

    progress = (current_price - start_price) / (target_price - start_price) * 100
    return max(0, min(progress, 100))

class StatusService:
    def __init__(self, db_manager: PostgresManager, config_manager: ConfigManager, feature_calculator: LiveFeatureCalculator):
        self.db_manager = db_manager
        self.strategy = StrategyRules(config_manager)
        self.feature_calculator = feature_calculator
        # Note: ExchangeManager is instantiated per-request in get_extended_status
        # to ensure it's created with the correct mode (live/test).

    def get_extended_status(self, environment: str, bot_id: str):
        """
        Gathers and calculates extended status information, including
        open positions' PnL, progress towards sell targets, and buy signal readiness.
        """
        try:
            exchange_manager = ExchangeManager(mode=environment)
            symbol = "BTCUSDT" # Assuming BTCUSDT for now

            # 1. Fetch current market data with all features
            market_data_series = self.feature_calculator.get_current_candle_with_features()
            if market_data_series.empty:
                return {"error": "Could not fetch current market data."}

            market_data = market_data_series.to_dict()
            current_price = market_data.get('close', 0)

            # 2. Fetch open positions from local DB
            # CORRECTED LOGIC: Only filter by bot_id in 'backtest' mode.
            # For 'trade' and 'test' modes, we want to see all open positions for the environment.
            bot_id_to_filter = bot_id if environment == 'backtest' else None
            open_positions_db = self.db_manager.get_open_positions(environment, bot_id_to_filter)

            # 3. Process open positions
            positions_status = []
            for trade in open_positions_db:
                unrealized_pnl = (current_price - trade.price) * trade.quantity if trade.price and trade.quantity else 0
                progress_to_sell_target_pct = _calculate_progress_pct(
                    current_price, trade.price, trade.sell_target_price
                )

                # Add the new requested data fields
                price_to_target = (trade.sell_target_price - current_price) if trade.sell_target_price and current_price else 0
                usd_to_target = price_to_target * trade.quantity if trade.quantity and price_to_target else 0

                positions_status.append({
                    "trade_id": trade.trade_id,
                    "entry_price": trade.price,
                    "current_price": current_price,
                    "quantity": trade.quantity,
                    "unrealized_pnl": unrealized_pnl,
                    "sell_target_price": trade.sell_target_price,
                    "progress_to_sell_target_pct": progress_to_sell_target_pct,
                    "price_to_target": price_to_target,
                    "usd_to_target": usd_to_target,
                })

            # 4. Determine buy signal status
            should_buy, _, reason = self.strategy.evaluate_buy_signal(
                market_data, len(positions_status) # Use the count of reconciled open positions
            )
            btc_purchase_target, btc_purchase_progress_pct = self._calculate_buy_progress(
                market_data, len(positions_status)
            )

            # 5. Fetch trade history from DB
            trade_history = self.db_manager.get_all_trades_in_range(environment)
            trade_history_dicts = [trade.to_dict() for trade in trade_history]

            # 6. Fetch live wallet data
            wallet_balances = exchange_manager.get_account_balance()

            # Filter for relevant assets and calculate USD value
            relevant_assets = {'BTC', 'USDT'}
            processed_balances = []
            for bal in wallet_balances:
                asset = bal.get('asset')
                if asset in relevant_assets:
                    free = float(bal.get('free', 0))
                    locked = float(bal.get('locked', 0))
                    total = free + locked
                    
                    if asset == 'BTC':
                        bal['usd_value'] = total * current_price
                    elif asset == 'USDT':
                        bal['usd_value'] = total
                    
                    processed_balances.append(bal)

            # 7. Assemble the final status object
            extended_status = {
                "mode": environment,
                "symbol": "BTC/USDT",
                "current_btc_price": current_price,
                "open_positions_status": positions_status,
                "buy_signal_status": {
                    "should_buy": should_buy,
                    "reason": reason,
                    "btc_purchase_target": btc_purchase_target,
                    "btc_purchase_progress_pct": btc_purchase_progress_pct
                },
                "trade_history": trade_history_dicts,
                "wallet_balances": processed_balances
            }

            return extended_status

        except Exception as e:
            logger.error(f"Error getting extended status: {e}", exc_info=True)
            return {"error": str(e)}

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
