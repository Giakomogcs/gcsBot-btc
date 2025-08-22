import logging
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.database.models import BotStatus
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.core_logic.capital_manager import CapitalManager
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
        self.config_manager = config_manager
        self.feature_calculator = feature_calculator
        self.strategy = StrategyRules(self.config_manager)
        self.capital_manager = CapitalManager(self.config_manager, self.strategy)


    def update_bot_status(self, bot_id: str, mode: str, reason: str, open_positions: int, portfolio_value: Decimal):
        """
        Creates or updates the status of a bot in the database.
        """
        with self.db_manager.get_db() as session:
            try:
                status = session.query(BotStatus).filter(BotStatus.bot_id == bot_id).first()
                if not status:
                    status = BotStatus(bot_id=bot_id, mode=mode, is_running=True)
                    session.add(status)
                
                status.last_buy_condition = reason
                status.open_positions = open_positions
                status.portfolio_value_usd = portfolio_value
                status.is_running = True # Mark as running on update
                
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to update bot status for {bot_id}: {e}", exc_info=True)

    def get_extended_status(self, environment: str, bot_id: str):
        """
        Gathers and calculates extended status information, including
        open positions' PnL, progress towards sell targets, and buy signal readiness.
        """
        try:
            exchange_manager = ExchangeManager(mode=environment)
            symbol = "BTCUSDT"

            market_data_series = self.feature_calculator.get_current_candle_with_features()
            if market_data_series.empty:
                return {"error": "Could not fetch current market data."}
            market_data = market_data_series.to_dict()
            current_price = Decimal(str(market_data.get('close', '0')))

            bot_id_to_filter = bot_id if environment == 'backtest' else None
            open_positions_db = self.db_manager.get_open_positions(environment, bot_id_to_filter) or []
            open_positions_count = len(open_positions_db)

            positions_status = self._process_open_positions(open_positions_db, current_price)

            wallet_balances, total_wallet_usd_value = self._process_wallet_balances(exchange_manager, current_price)
            
            # Fetch the persisted bot status reason
            with self.db_manager.get_db() as session:
                stmt = select(BotStatus.last_buy_condition).where(BotStatus.bot_id == bot_id)
                reason = session.execute(stmt).scalar_one_or_none() or "N/A"
                operating_mode = "N/A" # This could also be persisted if needed

            # This part is for the TUI display, not for the bot's actual decision making
            should_buy, _, _ = self.strategy.evaluate_buy_signal(market_data, open_positions_count)
            btc_purchase_target, btc_purchase_progress_pct = self._calculate_buy_progress(market_data, open_positions_count)

            trade_history = self.db_manager.get_all_trades_in_range(environment) or []
            trade_history_dicts = [trade.to_dict() for trade in trade_history]

            return {
                "mode": environment,
                "symbol": "BTC/USDT",
                "current_btc_price": current_price,
                "total_wallet_usd_value": total_wallet_usd_value,
                "open_positions_count": open_positions_count,
                "open_positions_status": positions_status,
                "buy_signal_status": {
                    "should_buy": should_buy,
                    "reason": reason, # Use the persisted reason
                    "operating_mode": operating_mode,
                    "btc_purchase_target": btc_purchase_target,
                    "btc_purchase_progress_pct": btc_purchase_progress_pct
                },
                "trade_history": trade_history_dicts,
                "wallet_balances": wallet_balances
            }
        except OperationalError as e:
            logger.error(f"Database connection error in StatusService: {e}", exc_info=True)
            return {"error": "Database connection failed.", "details": str(e)}
        except Exception as e:
            logger.error(f"Error getting extended status: {e}", exc_info=True)
            return {"error": str(e)}

    def _process_open_positions(self, open_positions_db, current_price):
        positions_status = []
        for trade in open_positions_db:
            entry_price = Decimal(trade.price)
            quantity = Decimal(trade.quantity)
            sell_target_price = Decimal(trade.sell_target_price)

            unrealized_pnl = self.strategy.calculate_net_unrealized_pnl(entry_price, current_price, quantity)
            progress_pct = _calculate_progress_pct(current_price, entry_price, sell_target_price)
            price_to_target = sell_target_price - current_price
            usd_to_target = price_to_target * quantity

            positions_status.append({
                "trade_id": trade.trade_id, "entry_price": entry_price, "current_price": current_price,
                "quantity": quantity, "unrealized_pnl": unrealized_pnl, "sell_target_price": sell_target_price,
                "progress_to_sell_target_pct": progress_pct, "price_to_target": price_to_target,
                "usd_to_target": usd_to_target,
            })
        return positions_status

    def _process_wallet_balances(self, exchange_manager, current_price):
        wallet_balances = exchange_manager.get_account_balance() or []
        processed_balances_dict = {
            'BTC': {'asset': 'BTC', 'free': '0.0', 'locked': '0.0'},
            'USDT': {'asset': 'USDT', 'free': '0.0', 'locked': '0.0'}
        }
        for bal in wallet_balances:
            asset = bal.get('asset')
            if asset in processed_balances_dict:
                processed_balances_dict[asset] = bal

        processed_balances = []
        total_usd_value = Decimal('0')
        for asset, bal in processed_balances_dict.items():
            try:
                free = Decimal(bal.get('free', '0'))
                locked = Decimal(bal.get('locked', '0'))
                total = free + locked
                usd_value = (free * current_price) if asset == 'BTC' else free

                processed_balances.append({
                    'asset': asset, 'free': free, 'locked': locked,
                    'total': total, 'usd_value': usd_value
                })
                total_usd_value += usd_value
            except InvalidOperation:
                continue

        return processed_balances, total_usd_value

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
