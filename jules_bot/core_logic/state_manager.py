import pandas as pd
from decimal import Decimal
import math
from datetime import datetime, timedelta, timezone
from typing import Optional
from jules_bot.utils.logger import logger
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.database.models import Trade
import uuid
from jules_bot.utils.config_manager import config_manager
from jules_bot.services.trade_logger import TradeLogger
from jules_bot.bot.account_manager import AccountManager
from jules_bot.core_logic.strategy_rules import StrategyRules
from jules_bot.bot.situational_awareness import SituationalAwareness
from jules_bot.core_logic.dynamic_parameters import DynamicParameters
from jules_bot.research.live_feature_calculator import LiveFeatureCalculator


class StateManager:
    def __init__(self, mode: str, bot_id: str, db_manager: PostgresManager, feature_calculator: LiveFeatureCalculator):
        self.mode = mode
        self.bot_id = bot_id
        self.db_manager = db_manager
        self.SessionLocal = db_manager.SessionLocal # Add this line
        self.feature_calculator = feature_calculator

        # The TradeLogger is now responsible for ALL WRITE operations.
        self.trade_logger = TradeLogger(mode=self.mode, db_manager=self.db_manager)

        logger.info(f"StateManager initialized for mode: '{self.mode}', bot_id: '{self.bot_id}'")

    def get_open_positions(self) -> list:
        """
        Fetches all trades marked as 'OPEN' for the current environment.
        For backtesting, it also filters by bot_id.
        """
        bot_id_to_filter = None
        if self.mode == 'backtest':
            bot_id_to_filter = self.bot_id
        
        return self.db_manager.get_open_positions(environment=self.mode, bot_id=bot_id_to_filter)

    def get_open_positions_count(self) -> int:
        """Queries the database and returns the number of currently open trades."""
        return len(self.get_open_positions())

    def get_trade_history(self, mode: str) -> list[dict]:
        """Fetches all trades (open and closed) from the database for the given mode."""
        # Note: The date range parameters are omitted to use the default values,
        # effectively fetching all trades for the given mode.
        return self.db_manager.get_all_trades_in_range(mode=mode)

    def get_trade_history_for_run(self) -> list:
        """Fetches all trades from the database for the current bot run."""
        return self.db_manager.get_trades_by_run_id(run_id=self.bot_id)

    def get_trades_in_last_n_hours(self, hours: int) -> list:
        """Fetches all trades from the database within the last N hours."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(hours=hours)
        return self.db_manager.get_all_trades_in_range(
            mode=self.mode,
            start_date=start_date,
            end_date=end_date
        )

    def get_last_purchase_price(self) -> Decimal:
        """
        Retrieves the purchase price of the most recent 'buy' trade.
        Returns Decimal('inf') if no open positions are found.
        """
        open_positions = self.get_open_positions()
        if not open_positions:
            return Decimal('inf')

        # Sort by time to find the most recent position.
        latest_position = sorted(open_positions, key=lambda p: p.timestamp, reverse=True)[0]
        
        return Decimal(str(latest_position.price))

    def create_new_position(self, buy_result: dict, sell_target_price: Decimal):
        """
        Records a new open position in the database via the TradeLogger service.
        """
        logger.info(f"Creating new position for trade_id: {buy_result.get('trade_id')} with target sell price: {sell_target_price:.8f}")

        # This dictionary flattens all the necessary data for the TradeLogger.
        # The TradeLogger is responsible for creating the TradePoint and ensuring type safety.
        trade_data = {
            **buy_result,  # Unpack the raw buy result dictionary
            'run_id': self.bot_id,
            'status': 'OPEN',
            'order_type': 'buy',
            'sell_target_price': sell_target_price,
            'strategy_name': buy_result.get('strategy_name', 'default'),
            'exchange': buy_result.get('exchange', 'binance')
        }

        # A new 'buy' position should never have a 'sell_price'.
        # This defensively removes the key if it was accidentally included in buy_result.
        trade_data.pop('sell_price', None)
        trade_data.pop('sell_usd_value', None)

        # Defensive coding: ensure no rogue PnL keys are present for a BUY trade.
        self.trade_logger.log_trade(trade_data)


    def recalculate_open_position_targets(self, strategy_rules: StrategyRules, sa_instance: SituationalAwareness, dynamic_params: DynamicParameters):
        """
        Recalculates the sell_target_price for all open positions based on the current
        market regime and strategy parameters.
        """
        logger.info("--- Starting recalculation of sell targets for open positions ---")
        open_positions = self.get_open_positions()
        if not open_positions:
            logger.info("No open positions to recalculate.")
            return

        # 1. Determine the current market regime
        features_df = self.feature_calculator.get_features_dataframe()
        if features_df.empty:
            logger.error("Could not get features dataframe. Aborting target recalculation.")
            return

        current_regime = -1
        # The sa_instance is always "fitted" as it's rule-based.
        regime_df = sa_instance.transform(features_df)
        if not regime_df.empty:
            current_regime = int(regime_df['market_regime'].iloc[-1])

        # If the regime is undefined, we cannot determine the correct parameters.
        if current_regime == -1:
            logger.warning("Cannot recalculate targets because market regime is undefined (-1). Skipping.")
            return

        logger.info(f"Recalculating targets based on current market regime: {current_regime}")

        # 2. Get the parameters for the current regime
        dynamic_params.update_parameters(current_regime)
        current_params = dynamic_params.parameters

        # 3. Iterate through open positions and recalculate
        updated_count = 0
        for position in open_positions:
            try:
                purchase_price = Decimal(str(position.price))
                
                # Defensively handle invalid or missing current_target
                current_target = Decimal('0') # Default value
                if position.sell_target_price is not None:
                    try:
                        current_target = Decimal(str(position.sell_target_price))
                    except Exception:
                        logger.warning(f"Could not parse current sell target '{position.sell_target_price}' for trade {position.trade_id}. Defaulting to 0.")

                quantity = Decimal(str(position.quantity))
                new_target = strategy_rules.calculate_sell_target_price(purchase_price, quantity, params=current_params)

                # Use a small tolerance for comparison to avoid floating point issues
                if not math.isclose(new_target, current_target, rel_tol=1e-9):
                    self.db_manager.update_trade_sell_target(position.trade_id, new_target)
                    logger.info(f"Updated sell target for trade {position.trade_id}: Old=${current_target:,.2f}, New=${new_target:,.2f}")
                    updated_count += 1
            except Exception as e:
                logger.error(f"Failed to recalculate target for trade {position.trade_id}: {e}", exc_info=True)

        if updated_count > 0:
            logger.info(f"Successfully updated targets for {updated_count} open positions.")
        else:
            logger.info("All open position targets are already up to date.")

        logger.info("--- Finished recalculating sell targets ---")

    def update_trade_trailing_state(self, trade_id: str, is_trailing: bool, highest_price: Optional[Decimal]):
        """
        Updates the trailing state fields for a specific trade.
        """
        logger.info(f"Updating trailing state for trade {trade_id}: is_trailing={is_trailing}, highest_price={highest_price}")
        update_data = {
            "is_trailing": is_trailing,
            "highest_price_since_breach": highest_price
        }
        # The underlying db_manager.update_trade is prepared to handle this dictionary
        self.db_manager.update_trade(trade_id, update_data)

    def update_trade_smart_trailing_state(
        self,
        trade_id: str,
        is_active: bool,
        highest_profit: Optional[Decimal] = None,
        activation_price: Optional[Decimal] = None,
        current_trail_percentage: Optional[Decimal] = None
    ):
        """
        Updates the state fields for the intelligent trailing stop for a specific trade.
        """
        logger.info(
            f"Updating smart trailing state for {trade_id}: active={is_active}, "
            f"highest_profit={highest_profit}, activation_price={activation_price}, "
            f"trail_pct={current_trail_percentage}"
        )
        update_data = {
            "is_smart_trailing_active": is_active,
            "smart_trailing_highest_profit": highest_profit,
            "smart_trailing_activation_price": activation_price,
        }
        if current_trail_percentage is not None:
            update_data["current_trail_percentage"] = current_trail_percentage

        # The underlying db_manager.update_trade is prepared to handle this dictionary
        self.db_manager.update_trade(trade_id, update_data)

    def record_partial_sell(self, original_trade_id: str, remaining_quantity: Decimal, sell_data: dict):
        """
        Records a partial sell by creating a new 'sell' record for the sold portion
        and updating the quantity of the original 'buy' record.
        """
        logger.info(f"Recording partial sell for original trade: {original_trade_id}")

        original_trade = self.db_manager.get_trade_by_trade_id(original_trade_id)
        if not original_trade:
            logger.error(f"Could not find original trade {original_trade_id} to record partial sell. Aborting.")
            return

        # 1. Create a new 'sell' record for the sold portion
        sell_trade_id = str(uuid.uuid4())
        
        # Explicitly construct the dictionary to ensure type safety and handle the timestamp correctly.
        # Calculate PnL percentage
        buy_usd_value = original_trade.price * Decimal(str(sell_data['quantity']))
        pnl_percentage = (sell_data.get('realized_pnl_usd', 0) / buy_usd_value) * 100 if buy_usd_value != 0 else 0

        decision_context = sell_data.get('decision_context', {})
        decision_context['pnl_percentage'] = f"{pnl_percentage:.2f}"

        # Explicitly construct the dictionary to ensure type safety and handle the timestamp correctly.
        sell_record_data = {
            'run_id': self.bot_id,
            'environment': self.mode,
            'strategy_name': original_trade.strategy_name,
            'symbol': original_trade.symbol,
            'trade_id': sell_trade_id,
            'linked_trade_id': original_trade_id,
            'exchange': original_trade.exchange,
            'status': 'CLOSED',  # A sell action is always final
            'order_type': 'sell',
            'price': original_trade.price,
            'quantity': Decimal(str(sell_data['quantity'])),
            'usd_value': buy_usd_value,
            'sell_price': Decimal(str(sell_data['price'])),
            'sell_usd_value': Decimal(str(sell_data['usd_value'])),
            'commission': Decimal(str(sell_data.get('commission', '0'))),
            'commission_asset': sell_data.get('commission_asset'),
            'timestamp': datetime.utcfromtimestamp(sell_data['timestamp'] / 1000).replace(tzinfo=timezone.utc),
            'exchange_order_id': sell_data.get('exchange_order_id'),
            'binance_trade_id': sell_data.get('binance_trade_id'),
            'decision_context': decision_context,
            'realized_pnl_usd': sell_data.get('realized_pnl_usd'),
            'hodl_asset_amount': sell_data.get('hodl_asset_amount'),
            'hodl_asset_value_at_sell': sell_data.get('hodl_asset_value_at_sell'),
        }

        self.trade_logger.log_trade(sell_record_data)
        logger.info(f"Created new SELL record {sell_trade_id} for partial sell of {original_trade_id} with PnL: ${sell_record_data.get('realized_pnl_usd', 0):.2f}.")

        # 2. Update the original 'buy' trade's quantity to reflect the remainder
        if remaining_quantity > Decimal('1e-8'): # Use tolerance
            logger.info(f"Updating quantity of original trade {original_trade_id} to remaining {remaining_quantity:.8f}.")
            context_update = {
                "partial_sell_info": f"Partial sell executed. New sell record: {sell_trade_id}",
                "last_update_time": datetime.utcnow().isoformat()
            }
            self.db_manager.update_trade_quantity_and_context(
                trade_id=original_trade_id,
                new_quantity=remaining_quantity,
                context_update=context_update
            )
        else:
            # If the remaining quantity is zero, close the original trade
            logger.info(f"Remaining quantity for {original_trade_id} is zero. Marking as CLOSED.")
            self.db_manager.update_trade_status(original_trade_id, 'CLOSED')

    def close_forced_position(self, trade_id: str, sell_result: dict, realized_pnl_usd: Decimal):
        """
        Records a new 'sell' trade to close a position after a forced sell,
        and updates the original 'buy' trade's status to 'CLOSED'.

        Args:
            trade_id: The ID of the original 'buy' trade to close.
            sell_result: The result from trader.execute_sell(), containing the
                         actual price, quantity, and usd_value of the sale.
            realized_pnl_usd: The calculated profit or loss for this trade.
        """
        logger.info(f"Force closing position {trade_id} with PnL: ${realized_pnl_usd:.2f}")

        original_trade = self.db_manager.get_trade_by_trade_id(trade_id)
        if not original_trade:
            logger.error(f"Could not find original trade {trade_id} to close. Aborting.")
            return

        # 1. Create a new 'sell' record
        sell_trade_id = str(uuid.uuid4())
        
        # Explicitly construct the dictionary to ensure type safety and handle the timestamp correctly.
        # The 'timestamp' from the trader response is an integer, but TradeLogger expects a datetime object.
        buy_usd_value = Decimal(str(original_trade.price)) * Decimal(str(sell_result['quantity']))
        pnl_percentage = (Decimal(str(realized_pnl_usd)) / buy_usd_value) * 100 if buy_usd_value != 0 else 0

        decision_context = sell_result.get('decision_context', {})
        decision_context['pnl_percentage'] = f"{pnl_percentage:.2f}"

        sell_data = {
            'run_id': self.bot_id,
            'environment': self.mode,
            'strategy_name': original_trade.strategy_name,
            'symbol': original_trade.symbol,
            'trade_id': sell_trade_id,
            'linked_trade_id': trade_id,
            'exchange': original_trade.exchange,
            'status': 'CLOSED',
            'order_type': 'sell',
            'price': original_trade.price,
            'quantity': Decimal(str(sell_result['quantity'])),
            'usd_value': buy_usd_value,
            'sell_price': Decimal(str(sell_result['price'])),
            'sell_usd_value': Decimal(str(sell_result['usd_value'])),
            'commission': Decimal(str(sell_result.get('commission', '0'))),
            'commission_asset': sell_result.get('commission_asset'),
            'timestamp': datetime.utcfromtimestamp(sell_result['timestamp'] / 1000).replace(tzinfo=timezone.utc),
            'exchange_order_id': sell_result.get('exchange_order_id'),
            'binance_trade_id': sell_result.get('binance_trade_id'),
            'decision_context': decision_context,
            'realized_pnl_usd': realized_pnl_usd,
        }

        self.trade_logger.log_trade(sell_data)
        logger.info(f"Created new SELL record {sell_trade_id} for forced sell of {trade_id} with PnL: ${realized_pnl_usd:.2f}.")

        # 2. Update the original 'buy' trade to be closed
        self.db_manager.update_trade_status(trade_id, 'CLOSED')
        logger.info(f"Updated original BUY record {trade_id} status to 'CLOSED'.")

    def record_sell_failure(self, trade_id: str, reason: dict):
        """
        Updates the status of a trade to 'SELL_ABORTED' after a failed execution.
        """
        logger.warning(f"Recording sell failure for trade {trade_id}. Reason: {reason}")
        context_update = {
            "sell_failure_reason": reason,
            "last_update_time": datetime.utcnow().isoformat()
        }
        self.db_manager.update_trade_status_and_context(
            trade_id=trade_id,
            new_status='SELL_ABORTED',
            context_update=context_update
        )
