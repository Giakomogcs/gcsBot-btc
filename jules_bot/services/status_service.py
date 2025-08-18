import logging
from decimal import Decimal, InvalidOperation
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator
from sqlalchemy.exc import OperationalError


logger = logging.getLogger(__name__)

def _calculate_progress_pct(current_price: Decimal, start_price: Decimal, target_price: Decimal) -> Decimal:
    """
    Calculates the percentage progress of a value from a starting point to a target.
    Clamps the result between 0 and 100.
    """
    if current_price is None or start_price is None or target_price is None:
        return Decimal('0.0')

    # Avoid division by zero if start and target prices are the same.
    if target_price == start_price:
        return Decimal('100.0') if current_price >= target_price else Decimal('0.0')

    try:
        # Calculate progress as a percentage. This works for both long and short scenarios.
        progress = (current_price - start_price) / (target_price - start_price) * Decimal('100')

        # Clamp the result between 0% and 100%.
        return max(Decimal('0'), min(progress, Decimal('100')))
    except (InvalidOperation, ZeroDivisionError):
        return Decimal('0.0')

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
            current_price = Decimal(str(market_data.get('close', '0')))
        except OperationalError as e:
            logger.error(f"Database connection error in StatusService: {e}", exc_info=True)
            return {"error": "Database connection failed.", "details": str(e)}

            # 2. Fetch open positions from local DB
            # CORRECTED LOGIC: Only filter by bot_id in 'backtest' mode.
            # For 'trade' and 'test' modes, we want to see all open positions for the environment.
            bot_id_to_filter = bot_id if environment == 'backtest' else None
            open_positions_db = self.db_manager.get_open_positions(environment, bot_id_to_filter)

            # 3. Process open positions
            positions_status = []
            for trade in open_positions_db:
                entry_price = Decimal(trade.price) if trade.price is not None else None
                quantity = Decimal(trade.quantity) if trade.quantity is not None else None
                sell_target_price = Decimal(trade.sell_target_price) if trade.sell_target_price is not None else None

                unrealized_pnl = self.strategy.calculate_net_unrealized_pnl(
                    entry_price=entry_price,
                    current_price=current_price,
                    total_quantity=quantity
                ) if entry_price and quantity else Decimal('0')

                progress_to_sell_target_pct = _calculate_progress_pct(
                    current_price,
                    start_price=entry_price,
                    target_price=sell_target_price
                )

                # Calculate how far the current price is from the sell target.
                price_to_target = Decimal('0')
                if sell_target_price is not None and current_price is not None:
                    price_to_target = sell_target_price - current_price
                
                # Calculate the USD value of that price difference.
                usd_to_target = Decimal('0')
                if quantity is not None:
                    usd_to_target = price_to_target * quantity

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

            # 6. Fetch live wallet data and ensure BTC/USDT are always present
            wallet_balances = exchange_manager.get_account_balance()
            
            # Create a default structure for balances to ensure BTC and USDT are always present
            processed_balances_dict = {
                'BTC': {'asset': 'BTC', 'free': '0.0', 'locked': '0.0', 'usd_value': 0.0},
                'USDT': {'asset': 'USDT', 'free': '0.0', 'locked': '0.0', 'usd_value': 0.0}
            }

            # Update the default structure with actual balances from the exchange
            for bal in wallet_balances:
                asset = bal.get('asset')
                if asset in processed_balances_dict:
                    processed_balances_dict[asset] = bal # Replace default with actual
            
            # Calculate USD value based on FREE balance (available for trading)
            # and ensure the list for the JSON output is created
            processed_balances = []
            for asset, bal in processed_balances_dict.items():
                try:
                    free = Decimal(bal.get('free', '0'))
                except InvalidOperation:
                    free = Decimal('0')

                # Calculate USD value based on the FREE (available) balance
                if asset == 'BTC':
                    bal['usd_value'] = free * current_price
                elif asset == 'USDT':
                    bal['usd_value'] = free
                
                processed_balances.append(bal)

            # Calculate total wallet value in USD from the FREE balances
            total_wallet_usd_value = sum(bal.get('usd_value', 0) for bal in processed_balances)

            # 7. Assemble the final status object
            extended_status = {
                "mode": environment,
                "symbol": "BTC/USDT",
                "current_btc_price": current_price,
                "total_wallet_usd_value": total_wallet_usd_value,
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

    def _calculate_buy_progress(self, market_data: dict, open_positions_count: int) -> tuple[Decimal, Decimal]:
        """
        Calculates the target price for the next buy and the progress towards it.
        """
        try:
            current_price = Decimal(str(market_data.get('close')))
            ema_20 = Decimal(str(market_data.get('ema_20')))
            bbl = Decimal(str(market_data.get('bbl_20_2_0')))
            ema_100 = Decimal(str(market_data.get('ema_100')))
            high_price = Decimal(str(market_data.get('high', current_price)))
        except (InvalidOperation, TypeError):
            return Decimal('0'), Decimal('0')

        if open_positions_count == 0:
            if current_price > ema_100: # Uptrend
                target_price = ema_20
                progress = Decimal('100.0') if current_price > target_price else \
                           _calculate_progress_pct(current_price, current_price * Decimal('1.05'), target_price)
            else: # Downtrend
                target_price = bbl
                progress = _calculate_progress_pct(current_price, high_price, target_price)
            return target_price, progress

        if current_price > ema_100: # Uptrend pullback
            target_price = ema_20
            progress = _calculate_progress_pct(current_price, high_price, target_price)
        else: # Downtrend breakout
            target_price = bbl
            progress = _calculate_progress_pct(current_price, high_price, target_price)

        return target_price, progress
