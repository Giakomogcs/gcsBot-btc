import json
import logging
import uuid
from typing import Optional
import pandas as pd
from sqlalchemy import create_engine, desc, and_
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

    def create_tables(self):
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def get_db(self) -> Session:
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
        with self.get_db() as db:
            try:
                trade = Trade(**trade_point.__dict__)
                db.add(trade)
                db.commit()
                logger.info(f"Successfully logged {trade.order_type} trade {trade.trade_id} to database.")
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

    def get_open_positions(self, bot_id: str) -> list[dict]:
        with self.get_db() as db:
            try:
                trades = db.query(Trade).filter(and_(Trade.run_id == bot_id, Trade.status == "OPEN")).all()
                return [trade.__dict__ for trade in trades]
            except Exception as e:
                logger.error(f"Error getting open positions: {e}")
                return []

    def get_trade_by_id(self, trade_id: str) -> Optional[pd.Series]:
        with self.get_db() as db:
            try:
                trade = db.query(Trade).filter(Trade.trade_id == trade_id).first()
                if trade:
                    return pd.Series(trade.__dict__)
                return None
            except Exception as e:
                logger.error(f"Falha ao buscar trade pelo ID '{trade_id}': {e}", exc_info=True)
                return None

    def has_open_positions(self) -> bool:
        with self.get_db() as db:
            try:
                return db.query(Trade).filter(Trade.status == "OPEN").first() is not None
            except Exception as e:
                logger.error(f"Falha ao verificar se existem posições abertas: {e}", exc_info=True)
                return False

    def get_all_trades_in_range(self, start_date: str = "-90d", end_date: str = "now()"):
        with self.get_db() as db:
            try:
                # This is a simplified version. A more robust implementation would parse the date strings.
                query = db.query(Trade).order_by(Trade.timestamp)
                df = pd.read_sql(query.statement, self.engine)
                return df
            except Exception as e:
                logger.error(f"Falha ao buscar todos os trades do DB: {e}", exc_info=True)
                return pd.DataFrame()

    def clear_all_tables(self):
        with self.get_db() as db:
            try:
                db.execute(text("TRUNCATE TABLE trades, bot_status, price_history RESTART IDENTITY;"))
                db.commit()
                logger.info("All tables cleared successfully.")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to clear tables: {e}")
