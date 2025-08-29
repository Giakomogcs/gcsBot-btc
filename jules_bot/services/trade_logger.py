import datetime
from typing import Dict, Any

from jules_bot.core.schemas import TradePoint
from jules_bot.database.postgres_manager import PostgresManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

class TradeLogger:
    """
    Acts as a guardian for writing trades to the database.
    It ensures that all data conforms to the schema defined in TradePoint,
    preventing schema collisions by explicitly casting data types.
    This is the single source of truth for logging any trade-related event.
    """
    def __init__(self, mode: str, db_manager: PostgresManager):
        if mode not in ['trade', 'test', 'backtest']:
            raise ValueError(f"Invalid mode '{mode}' provided to TradeLogger.")
        self.mode = mode
        self.db_manager = db_manager
        logger.info(f"TradeLogger initialized for mode '{self.mode}'.")

    def log_trade(self, trade_data: Dict[str, Any]):
        """
        Constructs a TradePoint and logs it to the database, ensuring
        all data types are correct. This is for CREATING new trades.
        """
        try:
            trade_point = self._create_trade_point(trade_data)
            self.db_manager.log_trade(trade_point)
            logger.info(f"Successfully logged '{trade_point.order_type}' trade for trade_id: {trade_point.trade_id}")
            return True
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"TradeLogger: Failed to create or log trade point. Error: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"TradeLogger: An unexpected error occurred while logging trade: {e}", exc_info=True)
            return False

    def update_trade(self, trade_data: Dict[str, Any]):
        """
        Updates an existing trade in the database with sell-side information.
        """
        try:
            trade_id = str(trade_data['trade_id'])
            # We don't need a full TradePoint, just the data to update.
            # The structure is validated implicitly by the db manager method.
            self.db_manager.update_trade_on_sell(trade_id, trade_data)
            logger.info(f"Successfully logged 'sell' trade for trade_id: {trade_id}")
            return True
        except KeyError as e:
            logger.error(f"TradeLogger: Missing 'trade_id' for update. Error: {e}")
            return False
        except Exception as e:
            logger.error(f"TradeLogger: An unexpected error occurred while updating trade: {e}", exc_info=True)
            return False

    def _create_trade_point(self, trade_data: Dict[str, Any]) -> TradePoint:
        """Helper to create and validate a TradePoint from a dictionary."""
        return TradePoint(
            run_id=str(trade_data['run_id']),
            environment=str(self.mode),
            strategy_name=str(trade_data.get('strategy_name', 'default')),
            symbol=str(trade_data['symbol']),
            trade_id=str(trade_data['trade_id']),
            exchange=str(trade_data.get('exchange', 'binance')),
            status=str(trade_data['status']),
            order_type=str(trade_data['order_type']),
            price=float(trade_data['price']),
            quantity=float(trade_data['quantity']),
            usd_value=float(trade_data['usd_value']),
            commission=float(trade_data.get('commission', 0.0)),
            commission_asset=str(trade_data.get('commission_asset', 'USDT')),
            timestamp=self._convert_timestamp(trade_data.get('timestamp')),
            exchange_order_id=str(trade_data.get('exchange_order_id')) if trade_data.get('exchange_order_id') else None,
            binance_trade_id=int(trade_data.get('binance_trade_id')) if trade_data.get('binance_trade_id') is not None else None,
            decision_context=trade_data.get('decision_context'),
            sell_target_price=float(trade_data.get('sell_target_price')) if trade_data.get('sell_target_price') is not None else None,
            commission_usd=float(trade_data.get('commission_usd')) if trade_data.get('commission_usd') is not None else None,
            realized_pnl_usd=float(trade_data.get('realized_pnl_usd')) if trade_data.get('realized_pnl_usd') is not None else None,
            hodl_asset_amount=float(trade_data.get('hodl_asset_amount')) if trade_data.get('hodl_asset_amount') is not None else None,
            hodl_asset_value_at_sell=float(trade_data.get('hodl_asset_value_at_sell')) if trade_data.get('hodl_asset_value_at_sell') is not None else None,
        )

    def _convert_timestamp(self, ts: Any) -> datetime.datetime:
        """
        Safely converts a timestamp from various formats (ms int, datetime) to a
        timezone-aware datetime object. Defaults to now() if input is None.
        """
        if ts is None:
            return datetime.datetime.now(datetime.timezone.utc)
        if isinstance(ts, int):
            # Assume it's a Unix timestamp in MILLISECONDS and convert to datetime
            return datetime.datetime.utcfromtimestamp(ts / 1000).replace(tzinfo=datetime.timezone.utc)
        if isinstance(ts, datetime.datetime):
            # If it's already a datetime object, ensure it's timezone-aware
            return ts.astimezone(datetime.timezone.utc) if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)

        logger.warning(f"Unexpected timestamp type '{type(ts)}'. Using current time.")
        return datetime.datetime.now(datetime.timezone.utc)
