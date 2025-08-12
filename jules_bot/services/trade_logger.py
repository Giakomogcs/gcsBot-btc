import datetime
from typing import Dict, Any

from jules_bot.core.schemas import TradePoint
from jules_bot.database.database_manager import DatabaseManager
from jules_bot.utils.config_manager import config_manager
from jules_bot.utils.logger import logger

class TradeLogger:
    """
    Acts as a guardian for writing trades to the database.
    It ensures that all data conforms to the schema defined in TradePoint,
    preventing schema collisions by explicitly casting data types.
    This is the single source of truth for logging any trade-related event.
    """
    def __init__(self, mode: str):
        if mode not in ['trade', 'test', 'backtest']:
            raise ValueError(f"Invalid mode '{mode}' provided to TradeLogger.")
        self.mode = mode
        self.bucket_name = self._get_bucket_for_mode(mode)

        # Instantiate DB manager here to be used by the log_trade method
        db_config = config_manager.get_db_config()
        db_config['bucket'] = self.bucket_name
        self.db_manager = DatabaseManager(config=db_config)
        logger.info(f"TradeLogger initialized for mode '{self.mode}' writing to bucket '{self.bucket_name}'.")

    def _get_bucket_for_mode(self, mode: str) -> str:
        """Selects the correct InfluxDB bucket based on the operating mode."""
        if mode == 'trade':
            return config_manager.get('INFLUXDB', 'bucket_live')
        elif mode == 'test':
            return config_manager.get('INFLUXDB', 'bucket_testnet')
        elif mode == 'backtest':
            return config_manager.get('INFLUXDB', 'bucket_backtest')

    def log_trade(self, trade_data: Dict[str, Any]):
        """
        Constructs a TradePoint and logs it to the database, ensuring
        all data types are correct.

        Args:
            trade_data (Dict[str, Any]): A dictionary containing all necessary
                                         fields to create a TradePoint.
        """
        try:
            # --- DATA TYPE ENFORCEMENT ---
            # This is the critical step. We explicitly cast each piece of data
            # to the type defined in the TradePoint dataclass. This prevents
            # errors where data from an API (like price as a string) would
            # cause a schema collision in InfluxDB.

            trade_point = TradePoint(
                # --- TAGS ---
                run_id=str(trade_data['run_id']),
                environment=str(self.mode),
                strategy_name=str(trade_data.get('strategy_name', 'default')),
                symbol=str(trade_data['symbol']),
                trade_id=str(trade_data['trade_id']),
                exchange=str(trade_data.get('exchange', 'binance')),
                status=str(trade_data['status']),

                # --- FIELDS ---
                order_type=str(trade_data['order_type']),
                price=float(trade_data['price']),
                quantity=float(trade_data['quantity']),
                usd_value=float(trade_data['usd_value']),
                commission=float(trade_data.get('commission', 0.0)),
                commission_asset=str(trade_data.get('commission_asset', 'USDT')),

                # --- Optional & Contextual Fields ---
                timestamp=trade_data.get('timestamp', datetime.datetime.now(datetime.timezone.utc)),
                exchange_order_id=str(trade_data.get('exchange_order_id')) if trade_data.get('exchange_order_id') else None,
                decision_context=trade_data.get('decision_context'),

                # --- Fields for BUY trades ---
                sell_target_price=float(trade_data.get('sell_target_price')) if trade_data.get('sell_target_price') is not None else None,

                # --- Fields for SELL trades ---
                commission_usd=float(trade_data.get('commission_usd')) if trade_data.get('commission_usd') is not None else None,
                realized_pnl_usd=float(trade_data.get('realized_pnl_usd')) if trade_data.get('realized_pnl_usd') is not None else None,
                hodl_asset_amount=float(trade_data.get('hodl_asset_amount')) if trade_data.get('hodl_asset_amount') is not None else None,
                hodl_asset_value_at_sell=float(trade_data.get('hodl_asset_value_at_sell')) if trade_data.get('hodl_asset_value_at_sell') is not None else None,
            )

            self.db_manager.log_trade(trade_point)
            logger.info(f"Successfully logged '{trade_point.order_type}' trade for trade_id: {trade_point.trade_id}")
            return True

        except KeyError as e:
            logger.error(f"TradeLogger: Missing essential key in trade_data to create TradePoint: {e}")
            return False
        except (ValueError, TypeError) as e:
            logger.error(f"TradeLogger: Data type conversion failed. Check the input data. Error: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"TradeLogger: An unexpected error occurred while logging trade: {e}", exc_info=True)
            return False
