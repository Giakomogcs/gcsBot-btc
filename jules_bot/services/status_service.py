import logging
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import pytz

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from jules_bot.bot.situational_awareness import SituationalAwareness
from jules_bot.core.exchange_connector import ExchangeManager
from jules_bot.core_logic.capital_manager import CapitalManager
from jules_bot.core_logic.dynamic_parameters import DynamicParameters
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.database.models import BotStatus
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator
from jules_bot.utils.config_manager import ConfigManager
from jules_bot.utils.helpers import _calculate_progress_pct, calculate_buy_progress

logger = logging.getLogger(__name__)


class StatusService:
    def __init__(self, db_manager: PostgresManager, config_manager: ConfigManager, feature_calculator: LiveFeatureCalculator):
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.feature_calculator = feature_calculator
        self.strategy = StrategyRules(self.config_manager)
        self.capital_manager = CapitalManager(self.config_manager, self.strategy)


    def update_bot_status(self, bot_id: str, mode: str, reason: str, open_positions: int, portfolio_value: Decimal, market_regime: int, operating_mode: str, buy_target: Decimal, buy_progress: Decimal):
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
                status.open_positions = int(open_positions)
                status.portfolio_value_usd = portfolio_value
                status.market_regime = int(market_regime)
                status.operating_mode = operating_mode
                status.buy_target = buy_target
                status.buy_progress = buy_progress
                status.is_running = True # Mark as running on update
                
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to update bot status for {bot_id}: {e}", exc_info=True)

    def set_bot_stopped(self, bot_id: str):
        """Explicitly sets the bot's status to stopped."""
        with self.db_manager.get_db() as session:
            try:
                status = session.query(BotStatus).filter(BotStatus.bot_id == bot_id).first()
                if status:
                    status.is_running = False
                    session.commit()
                    logger.info(f"Set bot '{bot_id}' status to STOPPED.")
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to set bot status to stopped for {bot_id}: {e}", exc_info=True)

    def set_bot_running(self, bot_id: str, mode: str):
        """Explicitly sets the bot's status to running."""
        with self.db_manager.get_db() as session:
            try:
                status = session.query(BotStatus).filter(BotStatus.bot_id == bot_id).first()
                if not status:
                    status = BotStatus(bot_id=bot_id, mode=mode)
                    session.add(status)
                status.is_running = True
                session.commit()
                logger.info(f"Set bot '{bot_id}' status to RUNNING.")
            except Exception as e:
                session.rollback()
                logger.error(f"Failed to set bot status to running for {bot_id}: {e}", exc_info=True)

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

            # Fetch all open positions for the bot, not just for this specific run_id
            open_positions_db = self.db_manager.get_open_positions(environment) or []
            open_positions_count = len(open_positions_db)

            positions_status = self._process_open_positions(open_positions_db, current_price)

            wallet_balances, total_wallet_usd_value = self._process_wallet_balances(exchange_manager, current_price)
            
            # --- LIVE STRATEGY EVALUATION ---
            current_regime = -1
            try:
                sa_instance = SituationalAwareness()
                historical_data = self.feature_calculator.get_historical_data_with_features()
                if historical_data is not None and not historical_data.empty:
                    regime_df = sa_instance.transform(historical_data)
                    if not regime_df.empty and 'market_regime' in regime_df.columns:
                        current_regime = regime_df['market_regime'].iloc[-1]
            except Exception as e:
                logger.warning(f"Could not determine market regime for status: {e}")

            dynamic_params = DynamicParameters(self.config_manager)
            dynamic_params.update_parameters(current_regime)
            current_params = dynamic_params.parameters

            cash_balance = next((bal['free'] for bal in wallet_balances if bal['asset'] == 'USDT'), Decimal('0'))
            end_date = datetime.now(pytz.utc)
            start_date = end_date - timedelta(hours=self.capital_manager.difficulty_reset_timeout_hours)
            trade_history = self.db_manager.get_all_trades_in_range(
                mode=environment,
                start_date=start_date,
                end_date=end_date
            )

            difficulty_factor = self.capital_manager._calculate_difficulty_factor(trade_history)

            # Re-evaluate the buy signal here to get the live status for the TUI
            buy_amount, operating_mode, reason, regime, _ = self.capital_manager.get_buy_order_details(
                market_data=market_data,
                open_positions=open_positions_db,
                portfolio_value=total_wallet_usd_value, # Using total wallet value as portfolio value
                free_cash=cash_balance,
                params=current_params,
                trade_history=trade_history
            )

            should_buy = buy_amount > 0

            # This logic is now duplicated from the trading_bot, which is what the user wants.
            # It ensures the TUI is calculating its own state.
            condition_target_price, condition_progress = calculate_buy_progress(
                market_data, current_params, difficulty_factor
            )

            bot_status_db = self.db_manager.get_bot_status(bot_id)
            bot_status_str = "RUNNING" if bot_status_db and bot_status_db.is_running else "STOPPED"

            # Format the target price for display
            condition_target = f"${condition_target_price:,.2f}" if condition_target_price > 0 else "N/A"

            buy_target_percentage_drop = Decimal('0')
            if condition_target_price > 0 and current_price > 0:
                try:
                    if current_price > condition_target_price:
                        buy_target_percentage_drop = ((current_price - condition_target_price) / current_price) * 100
                except InvalidOperation:
                    pass

            # Get all trades for the bot's schema, not just this run, for accurate PnL
            full_trade_history = self.db_manager.get_all_trades_in_range(mode=environment, bot_id=None, start_date=None) or []

            # --- PnL and Count Calculation ---
            total_realized_pnl = sum(
                Decimal(str(trade.realized_pnl_usd))
                for trade in full_trade_history
                if trade.order_type == 'sell' and trade.realized_pnl_usd is not None
            )
            total_unrealized_pnl = sum(
                pos['unrealized_pnl'] for pos in positions_status
            )
            net_total_pnl = total_realized_pnl + total_unrealized_pnl
            trade_history_dicts = [trade.to_dict() for trade in full_trade_history]
            total_trades_count = len(trade_history_dicts)

            # --- Capital Allocation Calculation ---
            total_btc_balance = next((bal['total'] for bal in wallet_balances if bal['asset'] == 'BTC'), Decimal('0'))
            capital_allocation = self.capital_manager.get_capital_allocation(
                open_positions=open_positions_db,
                free_usdt_balance=cash_balance, # cash_balance is already the free USDT
                total_btc_balance=total_btc_balance,
                current_btc_price=current_price
            )

            bot_status_db = self.db_manager.get_bot_status(bot_id)
            bot_status_str = "RUNNING" if bot_status_db and bot_status_db.is_running else "STOPPED"

            return {
                "bot_status": bot_status_str,
                "mode": environment,
                "symbol": "BTC/USDT",
                "current_btc_price": current_price,
                "total_wallet_usd_value": total_wallet_usd_value,
                "open_positions_count": open_positions_count,
                "total_trades_count": total_trades_count,
                "open_positions_status": positions_status,
                "buy_signal_status": {
                    "should_buy": should_buy,
                    "reason": reason,
                    "market_regime": current_regime,
                    "operating_mode": operating_mode,
                    "condition_target": condition_target,
                    "condition_progress": condition_progress,
                    "buy_target_percentage_drop": buy_target_percentage_drop,
                    "condition_label": "N/A"
                },
                "trade_history": trade_history_dicts,
                "wallet_balances": wallet_balances,
                "total_realized_pnl": total_realized_pnl,
                "total_unrealized_pnl": total_unrealized_pnl,
                "net_total_pnl": net_total_pnl,
                "capital_allocation": capital_allocation
            }
        except OperationalError as e:
            logger.error(f"Database connection error in StatusService: {e}", exc_info=True)
            return {"error": "Database connection failed.", "details": str(e)}
        except Exception as e:
            logger.error(f"Error getting extended status: {e}", exc_info=True)
            return {"error": str(e), "bot_status": "ERROR"}

    def _calculate_buy_condition_details(self, reason: str, market_data: dict, current_params: dict, should_buy: bool) -> tuple[str, Decimal, str]:
        if should_buy:
            return "Met", Decimal('100'), "Signal Active"

        current_price = Decimal(str(market_data.get('close')))
        high_price = Decimal(str(market_data.get('high', current_price)))
        target_value_str = "N/A"
        progress_pct = Decimal('0')
        label = "Buy Condition"

        bbl_match = re.search(r"Buy target: \$([\d,\.]+)", reason)
        if bbl_match:
            try:
                target_price = Decimal(bbl_match.group(1).replace(',', ''))
                progress_pct = _calculate_progress_pct(current_price, high_price, target_price)
                target_value_str = f"${target_price:,.2f}"
                label = "Buy Target (BBL)"
                return target_value_str, progress_pct, label
            except (InvalidOperation, IndexError):
                pass

        ema_match = re.search(r"below EMA20 \$([\d,\.]+)", reason)
        if ema_match:
            try:
                target_price = Decimal(ema_match.group(1).replace(',', ''))
                progress_pct = _calculate_progress_pct(current_price, high_price, target_price)
                target_value_str = f"${target_price:,.2f}"
                label = "Pullback Target (EMA20)"
                return target_value_str, progress_pct, label
            except (InvalidOperation, IndexError):
                pass

        if "dip buy" in reason.lower() or "no pullback" in reason.lower():
            try:
                buy_dip_percentage = current_params.get('buy_dip_percentage', Decimal('0.02'))
                target_price = high_price * (Decimal('1') - buy_dip_percentage)
                progress_pct = _calculate_progress_pct(current_price, high_price, target_price)
                target_value_str = f"${target_price:,.2f}"
                label = f"Dip Target ({buy_dip_percentage:.1%})"
                return target_value_str, progress_pct, label
            except InvalidOperation:
                pass

    def _process_open_positions(self, open_positions_db, current_price):
        positions_status = []
        for trade in open_positions_db:
            entry_price = Decimal(trade.price) if trade.price is not None else Decimal('0')
            quantity = Decimal(trade.quantity) if trade.quantity is not None else Decimal('0')
            sell_target_price = Decimal(trade.sell_target_price) if trade.sell_target_price is not None else Decimal('0')
            buy_commission_usd = Decimal(trade.commission_usd) if trade.commission_usd is not None else Decimal('0')

            unrealized_pnl = self.strategy.calculate_net_unrealized_pnl(entry_price, current_price, quantity, buy_commission_usd)

            # Calculate PnL Percentage
            entry_value = entry_price * quantity
            unrealized_pnl_pct = (unrealized_pnl / entry_value) * 100 if entry_value > 0 else Decimal('0')

            # Calculate Potential PnL at target
            sell_value_at_target = sell_target_price * quantity
            sell_commission_at_target = sell_value_at_target * self.strategy.commission_rate
            target_pnl = self.strategy.calculate_realized_pnl(
                buy_price=entry_price,
                sell_price=sell_target_price,
                quantity_sold=quantity,
                buy_commission_usd=buy_commission_usd,
                sell_commission_usd=sell_commission_at_target,
                buy_quantity=quantity
            )

            # Calculate progress based on PnL, which is more intuitive than price.
            progress_pct = _calculate_progress_pct(unrealized_pnl, Decimal('0'), target_pnl)
            price_to_target = sell_target_price - current_price
            usd_to_target = price_to_target * quantity

            positions_status.append({
                "trade_id": trade.trade_id,
                "timestamp": trade.timestamp.isoformat(),
                "entry_price": entry_price,
                "current_price": current_price,
                "quantity": quantity,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "target_pnl": target_pnl,
                "sell_target_price": sell_target_price,
                "progress_to_sell_target_pct": progress_pct,
                "price_to_target": price_to_target,
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

                if asset == 'BTC':
                    usd_value = total * current_price
                else:
                    usd_value = total

                processed_balances.append({
                    'asset': asset, 'free': free, 'locked': locked,
                    'total': total, 'usd_value': usd_value
                })
                total_usd_value += usd_value
            except InvalidOperation:
                continue

        return processed_balances, total_usd_value
