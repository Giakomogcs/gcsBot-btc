import json
import logging
import uuid
from typing import Optional, Iterator
import pandas as pd
from sqlalchemy import create_engine, desc, and_, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from jules_bot.core.schemas import TradePoint
from jules_bot.database.models import Base, Trade, BotStatus, PriceHistory
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
        Logs a trade to the database.
        If the trade_id already exists, it updates the record with sell information.
        Otherwise, it creates a new record for a new buy trade.
        """
        with self.get_db() as db:
            try:
                existing_trade = db.query(Trade).filter(Trade.trade_id == trade_point.trade_id).first()

                if existing_trade:
                    # This is an update for a sell, closing a buy.
                    # We selectively update fields. Crucially, order_type is NOT changed.
                    logger.info(f"Updating existing trade {trade_point.trade_id} with status '{trade_point.status}'.")
                    
                    existing_trade.status = trade_point.status
                    existing_trade.timestamp = trade_point.timestamp # Update to sell time
                    
                    # Update fields to reflect the sell transaction details
                    existing_trade.price = trade_point.price
                    existing_trade.quantity = trade_point.quantity
                    existing_trade.usd_value = trade_point.usd_value
                    existing_trade.commission = trade_point.commission

                    # Add sell-specific financial details
                    existing_trade.realized_pnl_usd = trade_point.realized_pnl_usd
                    existing_trade.commission_usd = trade_point.commission_usd
                    existing_trade.hodl_asset_amount = trade_point.hodl_asset_amount
                    existing_trade.hodl_asset_value_at_sell = trade_point.hodl_asset_value_at_sell
                    
                    # Update context to reflect the sell decision
                    existing_trade.decision_context = trade_point.decision_context

                else:
                    # This is a new trade (a buy)
                    logger.info(f"Creating new trade record for trade_id: {trade_point.trade_id}")
                    new_trade = Trade(**trade_point.__dict__)
                    db.add(new_trade)

                db.commit()
                # Clarify log message
                action_type = "buy" if not existing_trade else "sell (update)"
                logger.info(f"Successfully logged '{action_type}' for trade_id: {trade_point.trade_id}")

            except Exception as e:
                db.rollback()
                logger.error(f"Failed to log trade to PostgreSQL: {e}", exc_info=True)

    def get_price_data(self, measurement: str, start_date: str = "-30d", end_date: str = "now()") -> pd.DataFrame:
        with self.get_db() as db:
            try:
                # This is a simplified version. A more robust implementation would parse the date strings.
                query = db.query(PriceHistory).filter(PriceHistory.symbol == measurement).order_by(PriceHistory.timestamp)
                df = pd.read_sql(query.statement, self.engine)
                df = df.rename(columns={"timestamp": "timestamp"}).set_index('timestamp')
                return df
            except Exception as e:
                logger.error(f"Failed to get price data: {e}", exc_info=True)
                return pd.DataFrame()

    def get_open_positions(self, environment: str, bot_id: Optional[str] = None) -> list:
        """
        Fetches open positions for a given environment.
        If bot_id is provided, it also filters by bot_id (for backtesting).
        Returns a list of Trade model instances.
        """
        with self.get_db() as db:
            try:
                query = db.query(Trade).filter(
                    and_(
                        Trade.status == "OPEN",
                        Trade.environment == environment
                    )
                )
                if bot_id:
                    query = query.filter(Trade.run_id == bot_id)
                
                trades = query.all()
                return trades
            except Exception as e:
                logger.error(f"Failed to get open positions from DB: {e}")
                raise

    def get_trade_by_id(self, trade_id: str) -> Optional[pd.Series]:
        with self.get_db() as db:
            try:
                trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
                if trade:
                    return pd.Series(trade.__dict__)
                return None
            except Exception as e:
                logger.error(f"Failed to get trade by ID '{trade_id}': {e}", exc_info=True)
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

    def get_all_trades_in_range(self, mode: Optional[str] = None, start_date: str = "-90d", end_date: str = "now()"):
        with self.get_db() as db:
            try:
                # This is a simplified version. A more robust implementation would parse the date strings.
                query = db.query(Trade).order_by(Trade.timestamp)
                if mode:
                    query = query.filter(Trade.environment == mode)

                trades = query.all()
                return trades

            except Exception as e:
                logger.error(f"Failed to get all trades from DB: {e}", exc_info=True)
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
