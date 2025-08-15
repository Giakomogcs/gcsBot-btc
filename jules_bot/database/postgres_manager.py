import json
import logging
import uuid
from typing import Optional, Iterator
import pandas as pd
from sqlalchemy import create_engine, desc, and_, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from jules_bot.core.schemas import TradePoint
from jules_bot.database.base import Base
from jules_bot.database.models import Trade, BotStatus, PriceHistory
from jules_bot.database.portfolio_models import PortfolioSnapshot, FinancialMovement
from jules_bot.utils.logger import logger

class PostgresManager:
    def __init__(self, config: dict):
        self.db_url = f"postgresql+psycopg2://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{config['dbname']}"
        self.engine = create_engine(self.db_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.create_tables()
        self._run_migrations()

    def _run_migrations(self):
        inspector = inspect(self.engine)
        with self.engine.connect() as connection:
            try:
                if not inspector.has_table("trades"):
                    return
                columns = [c['name'] for c in inspector.get_columns('trades')]
                if 'binance_trade_id' not in columns:
                    logger.info("Adding missing column 'binance_trade_id' to table 'trades'")
                    with connection.begin():
                        connection.execute(text('ALTER TABLE trades ADD COLUMN binance_trade_id INTEGER'))
            except Exception as e:
                logger.error(f"Failed to run migration: {e}")

    def create_tables(self):
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def get_db(self) -> Iterator[Session]:
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def write_bot_status(self, bot_id: str, mode: str, status_data: dict):
        with self.get_db() as db:
            try:
                bot_status = db.query(BotStatus).filter(BotStatus.bot_id == bot_id).first()
                if bot_status:
                    for key, value in status_data.items():
                        setattr(bot_status, key, value)
                else:
                    bot_status = BotStatus(bot_id=bot_id, mode=mode, **status_data)
                    db.add(bot_status)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to write bot status to PostgreSQL: {e}")

    def log_trade(self, trade_point: TradePoint):
        """
        Logs a trade to the database by creating a new record.
        Updates to existing trades should be handled by specific update methods.
        """
        with self.get_db() as db:
            try:
                logger.info(f"Creating new trade record for trade_id: {trade_point.trade_id}")
                new_trade = Trade(**trade_point.__dict__)
                db.add(new_trade)
                db.commit()
                logger.info(f"Successfully logged '{new_trade.order_type}' for trade_id: {trade_point.trade_id}")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to log trade to PostgreSQL: {e}", exc_info=True)

    def update_trade_on_sell(self, trade_id: str, sell_data: dict):
        """
        Updates an existing trade record with sell-side information, marking it as 'CLOSED'.
        """
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"DB: Could not find trade with trade_id '{trade_id}' to update with sell data.")
                    return

                logger.info(f"DB: Updating and closing trade {trade_id} with sell information.")

                trade_to_update.status = 'CLOSED'
                trade_to_update.order_type = 'sell' # Reflects the last action on the trade
                
                # Update all relevant fields from the sell_data dictionary
                trade_to_update.price = sell_data.get('price', trade_to_update.price)
                trade_to_update.quantity = sell_data.get('quantity', trade_to_update.quantity)
                trade_to_update.usd_value = sell_data.get('usd_value', trade_to_update.usd_value)
                trade_to_update.commission = sell_data.get('commission', trade_to_update.commission)
                trade_to_update.timestamp = sell_data.get('timestamp', trade_to_update.timestamp)
                trade_to_update.decision_context = sell_data.get('decision_context', trade_to_update.decision_context)
                trade_to_update.commission_usd = sell_data.get('commission_usd')
                trade_to_update.realized_pnl_usd = sell_data.get('realized_pnl_usd')
                trade_to_update.hodl_asset_amount = sell_data.get('hodl_asset_amount')
                trade_to_update.hodl_asset_value_at_sell = sell_data.get('hodl_asset_value_at_sell')

                db.commit()
                logger.info(f"DB: Successfully updated and closed trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"DB: Failed to update trade on sell for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def get_price_data(self, measurement: str, start_date: str = "-30d", end_date: str = "now()") -> pd.DataFrame:
        """
        Fetches price data from the database for a specific measurement within a given date range.
        `start_date` and `end_date` should be in a format that PostgreSQL can understand,
        e.g., 'YYYY-MM-DD HH:MI:SS' or relative like '-30d'.
        """
        logger.info(f"DB: Fetching price data for {measurement} from {start_date} to {end_date}")
        with self.get_db() as db:
            try:
                # The query now correctly uses the date range to filter data at the database level.
                query = db.query(PriceHistory).filter(
                    PriceHistory.symbol == measurement,
                    PriceHistory.timestamp >= text(f"now() - interval '{start_date.replace('-', '')}'") if '-' in start_date else text(f"'{start_date}'"),
                    PriceHistory.timestamp <= text("now()") if end_date == "now()" else text(f"'{end_date}'")
                ).order_by(PriceHistory.timestamp)

                df = pd.read_sql(query.statement, self.engine, index_col='timestamp')

                if df.empty:
                    logger.warning(f"DB: No price data found for {measurement} in the specified range.")
                
                return df
            except Exception as e:
                logger.error(f"DB: Failed to get price data: {e}", exc_info=True)
                return pd.DataFrame()

    def get_open_positions(self, environment: str, bot_id: Optional[str] = None, symbol: Optional[str] = None) -> list:
        """
        Fetches open positions for a given environment.
        Can optionally filter by bot_id (for backtesting) and symbol.
        Returns a list of Trade model instances.
        """
        with self.get_db() as db:
            try:
                filters = [
                    Trade.status == "OPEN",
                    Trade.environment == environment
                ]
                if bot_id:
                    filters.append(Trade.run_id == bot_id)
                if symbol:
                    filters.append(Trade.symbol == symbol)
                
                query = db.query(Trade).filter(and_(*filters))
                
                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get open positions from DB: {e}")
                raise

    def get_treasury_positions(self, environment: str, bot_id: Optional[str] = None) -> list:
        """
        Fetches all trades marked as 'TREASURY' for the current environment.
        """
        with self.get_db() as db:
            try:
                query = db.query(Trade).filter(
                    and_(
                        Trade.status == "TREASURY",
                        Trade.environment == environment
                    )
                )
                if bot_id:
                    query = query.filter(Trade.run_id == bot_id)

                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get treasury positions from DB: {e}", exc_info=True)
                return []

    def get_trade_by_trade_id(self, trade_id: str) -> Optional[Trade]:
        """Fetches a trade by its unique trade_id and returns the SQLAlchemy model instance."""
        with self.get_db() as db:
            try:
                trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
                return trade
            except Exception as e:
                logger.error(f"Failed to get trade by trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def update_trade_status(self, trade_id: str, new_status: str):
        """Updates the status of a specific trade in the database."""
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update status.")
                    return

                logger.info(f"Updating status for trade {trade_id} from '{trade_to_update.status}' to '{new_status}'.")
                trade_to_update.status = new_status
                db.commit()
                logger.info(f"Successfully updated status for trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update trade status for trade_id '{trade_id}': {e}", exc_info=True)
                raise
    
    def get_trade_by_binance_trade_id(self, binance_trade_id: int) -> Optional[Trade]:
        with self.get_db() as db:
            try:
                trade = db.query(Trade).filter(Trade.binance_trade_id == binance_trade_id).first()
                return trade
            except Exception as e:
                logger.error(f"Failed to get trade by binance_trade_id '{binance_trade_id}': {e}")
                return None

    def has_open_positions(self) -> bool:
        with self.get_db() as db:
            try:
                return db.query(Trade).filter(Trade.status == "OPEN").first() is not None
            except Exception as e:
                logger.error(f"Failed to check for open positions: {e}", exc_info=True)
                raise

    def get_all_trades_in_range(self, mode: Optional[str] = None, symbol: Optional[str] = None, start_date: str = "-90d", end_date: str = "now()"):
        with self.get_db() as db:
            try:
                # This is a simplified version. A more robust implementation would parse the date strings.
                query = db.query(Trade).order_by(Trade.timestamp)
                if mode:
                    query = query.filter(Trade.environment == mode)
                if symbol:
                    query = query.filter(Trade.symbol == symbol)

                trades = query.all()
                return trades

            except Exception as e:
                logger.error(f"Failed to get all trades from DB: {e}", exc_info=True)
                raise

    def get_trades_by_run_id(self, run_id: str) -> list:
        """Fetches all trades associated with a specific run_id."""
        with self.get_db() as db:
            try:
                query = db.query(Trade).filter(Trade.run_id == run_id).order_by(Trade.timestamp)
                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get trades by run_id '{run_id}': {e}", exc_info=True)
                raise

    def get_last_trade_id(self, environment: str) -> int:
        """
        Fetches the ID of the last trade for a given environment from the database.
        """
        with self.get_db() as db:
            try:
                last_trade = db.query(Trade).filter(Trade.environment == environment).order_by(desc(Trade.binance_trade_id)).first()
                if last_trade and last_trade.binance_trade_id is not None:
                    return last_trade.binance_trade_id
                return 0
            except Exception as e:
                logger.error(f"Failed to get last trade ID from DB: {e}", exc_info=True)
                return 0

    def update_trade_quantity(self, trade_id: str, new_quantity: float):
        """
        Updates the quantity of a specific trade in the database.
        This is used for partial sell logic, where the original buy position's
        quantity is reduced.
        """
        with self.get_db() as db:
            try:
                trade_to_update = db.query(Trade).filter(Trade.trade_id == trade_id).first()

                if not trade_to_update:
                    logger.error(f"Could not find trade with trade_id '{trade_id}' to update quantity.")
                    return

                logger.info(f"Updating quantity for trade {trade_id} from {trade_to_update.quantity} to {new_quantity}.")
                trade_to_update.quantity = new_quantity
                db.commit()
                logger.info(f"Successfully updated quantity for trade {trade_id}.")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to update trade quantity for trade_id '{trade_id}': {e}", exc_info=True)
                raise

    def clear_all_tables(self):
        with self.get_db() as db:
            try:
                db.execute(text("TRUNCATE TABLE trades, bot_status, price_history RESTART IDENTITY;"))
                db.commit()
                logger.info("All tables cleared successfully.")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to clear tables: {e}")

    def query_first_timestamp(self, measurement: str) -> Optional[pd.Timestamp]:
        """
        Queries the very first timestamp for a specific measurement in the table.
        """
        logger.info(f"Querying first timestamp for measurement '{measurement}'...")
        with self.get_db() as db:
            try:
                from jules_bot.database.models import PriceHistory
                from sqlalchemy import asc
                first_record = db.query(PriceHistory).filter(PriceHistory.symbol == measurement).order_by(asc(PriceHistory.timestamp)).first()
                if not first_record:
                    logger.info(f"No data found in measurement '{measurement}'.")
                    return None
                first_timestamp = pd.to_datetime(first_record.timestamp).tz_localize('UTC')
                logger.info(f"First timestamp found in DB: {first_timestamp}")
                return first_timestamp
            except Exception as e:
                logger.error(f"Error querying first timestamp from PostgreSQL for measurement '{measurement}': {e}", exc_info=True)
                return None

    def clear_backtest_trades(self):
        """Deletes all trades from the 'trades' table where the environment is 'backtest'."""
        with self.get_db() as db:
            try:
                # Using text for a simple delete statement for clarity
                statement = text("DELETE FROM trades WHERE environment = :env")
                result = db.execute(statement, {"env": "backtest"})
                db.commit()
                logger.info(f"Successfully cleared {result.rowcount} backtest trades from the database.")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to clear backtest trades: {e}", exc_info=True)
                raise

    def clear_testnet_trades(self):
        """Deletes all trades from the 'trades' table where the environment is 'test'."""
        with self.get_db() as db:
            try:
                statement = text("DELETE FROM trades WHERE environment = :env")
                result = db.execute(statement, {"env": "test"})
                db.commit()
                logger.info(f"Successfully cleared {result.rowcount} testnet trades from the database.")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to clear testnet trades: {e}", exc_info=True)
                raise
