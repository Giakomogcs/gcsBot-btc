import logging
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

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
from jules_bot.utils.helpers import _calculate_progress_pct

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

            open_positions_db = self.db_manager.get_open_positions(environment, bot_id) or []
            open_positions_count = len(open_positions_db)

            positions_status = self._process_open_positions(open_positions_db, current_price)

            wallet_balances, total_wallet_usd_value = self._process_wallet_balances(exchange_manager, current_price)
            
            # --- LIVE STRATEGY EVALUATION ---
            # This section replicates the bot's decision-making process for the TUI
            # to provide a real-time status view, independent of the bot's last saved state.

            # 1. Determine Market Regime
            current_regime = -1
            try:
                sa_instance = SituationalAwareness()
                historical_data = self.feature_calculator.get_historical_data_with_features()
                if historical_data is not None and not historical_data.empty:
                    # Transform the historical data to get regimes for all points
                    regime_df = sa_instance.transform(historical_data)
                    if not regime_df.empty and 'market_regime' in regime_df.columns:
                        # Get the latest market regime from the series
                        current_regime = regime_df['market_regime'].iloc[-1]
            except Exception as e:
                logger.warning(f"Could not determine market regime for status: {e}")

            # 2. Get Dynamic Parameters
            dynamic_params = DynamicParameters(self.config_manager)
            dynamic_params.update_parameters(current_regime)
            current_params = dynamic_params.parameters

            # 3. Evaluate Buy Condition
            cash_balance = next((bal['free'] for bal in wallet_balances if bal['asset'] == 'USDT'), Decimal('0'))

            # The regime is returned but not used in the TUI status, so we can ignore it with `_`
            # FIX: Fetch recent trade history to correctly calculate difficulty factor for the live status
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(hours=self.capital_manager.difficulty_reset_timeout_hours)
            trade_history = self.db_manager.get_all_trades_in_range(
                mode=environment,
                start_date=start_date,
                end_date=end_date
            )

            buy_amount_usdt, operating_mode, reason, _ = self.capital_manager.get_buy_order_details(
                market_data=market_data,
                open_positions=open_positions_db,
                portfolio_value=total_wallet_usd_value, # Using wallet value as proxy
                free_cash=cash_balance,
                params=current_params,
                trade_history=trade_history
            )

            # 4. Calculate Buy Progress
            should_buy = buy_amount_usdt > 0
            condition_target, condition_progress, condition_label = self._calculate_buy_condition_details(
                reason, market_data, current_params, should_buy
            )

            buy_target_percentage_drop = Decimal('0')
            if 'N/A' not in condition_target and current_price > 0:
                try:
                    target_price = Decimal(condition_target.replace('$', '').replace(',', ''))
                    if current_price > target_price:
                        buy_target_percentage_drop = ((current_price - target_price) / current_price) * 100
                except InvalidOperation:
                    pass

            should_buy = buy_amount_usdt > 0

            trade_history = self.db_manager.get_all_trades_in_range(mode=environment, bot_id=bot_id) or []
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
                    "reason": reason,
                    "market_regime": current_regime,
                    "operating_mode": operating_mode,
                    "condition_target": condition_target,
                    "condition_progress": condition_progress,
                    "condition_label": condition_label,
                    "buy_target_percentage_drop": buy_target_percentage_drop
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

    def _calculate_buy_condition_details(self, reason: str, market_data: dict, current_params: dict, should_buy: bool) -> tuple[str, Decimal, str]:
        """
        Parses the 'reason' string from the buy signal evaluation to determine
        the actual condition the bot is waiting for and calculates the progress towards it.
        """
        # If a buy signal is definitively active, we don't need to parse the reason.
        if should_buy:
            return "Met", Decimal('100'), "Signal Active"

        current_price = Decimal(str(market_data.get('close')))
        high_price = Decimal(str(market_data.get('high', current_price)))

        # Default values
        target_value_str = "N/A"
        progress_pct = Decimal('0')
        label = "Buy Condition"

        # Pattern 1: Waiting for price to drop to a Bollinger Band
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

        # Pattern 2: Waiting for price to drop below EMA20 in an uptrend
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

        # Pattern 3: Waiting for a general dip buy signal (handles "no pullback" and other dip scenarios)
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

        # If no specific target was parsed, return the generic status.
        # This signals to the TUI to simplify the display.
        return reason, Decimal('0'), "INFO"


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

                # Correctly calculate USD value for both assets
                if asset == 'BTC':
                    usd_value = total * current_price
                else: # For USDT, the value is the total amount
                    usd_value = total

                processed_balances.append({
                    'asset': asset, 'free': free, 'locked': locked,
                    'total': total, 'usd_value': usd_value
                })
                total_usd_value += usd_value
            except InvalidOperation:
                continue

        return processed_balances, total_usd_value
