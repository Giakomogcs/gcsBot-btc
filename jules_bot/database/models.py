from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import datetime

Base = declarative_base()

class PriceHistory(Base):
    __tablename__ = 'price_history'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    symbol = Column(String)

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    run_id = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    strategy_name = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    trade_id = Column(String, nullable=False, unique=True)
    exchange = Column(String, nullable=False)
    status = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    usd_value = Column(Float, nullable=False)
    commission = Column(Float)
    commission_asset = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    exchange_order_id = Column(String)
    decision_context = Column(JSON)
    sell_target_price = Column(Float)
    commission_usd = Column(Float)
    realized_pnl_usd = Column(Float)
    hodl_asset_amount = Column(Float)
    hodl_asset_value_at_sell = Column(Float)
    backtest_id = Column(String)
    realized_pnl = Column(Float)
    held_quantity = Column(Float)

class BotStatus(Base):
    __tablename__ = 'bot_status'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    is_running = Column(Boolean, default=False)
    session_pnl_usd = Column(Float, default=0.0)
    session_pnl_percent = Column(Float, default=0.0)
    open_positions = Column(Integer, default=0)
    portfolio_value_usd = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
