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
    def to_dict(self):
        """Converts the object to a dictionary."""
        # A more robust way to convert SQLAlchemy model to dict
        result = {}
        for key in self.__mapper__.c.keys():
            value = getattr(self, key)
            if isinstance(value, datetime.datetime):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result
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
    binance_trade_id = Column(Integer)
    decision_context = Column(JSON)
    sell_target_price = Column(Float)
    commission_usd = Column(Float)
    realized_pnl_usd = Column(Float)
    hodl_asset_amount = Column(Float)
    hodl_asset_value_at_sell = Column(Float)
    backtest_id = Column(String)
    realized_pnl = Column(Float)
    held_quantity = Column(Float)

class PortfolioSnapshot(Base):
    __tablename__ = 'portfolio_snapshots'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    bot_id = Column(String, nullable=False)
    mode = Column(String, nullable=False)

    # Portfolio Value
    total_portfolio_value_usd = Column(Float)
    btc_balance = Column(Float)
    usdt_balance = Column(Float)

    # Investment Performance
    cumulative_deposits_usd = Column(Float)
    cumulative_realized_pnl_usd = Column(Float)
    net_portfolio_growth_usd = Column(Float) # total_value - deposits

    # Trade Status
    open_positions_count = Column(Integer)
    avg_entry_price = Column(Float)

class Deposit(Base):
    __tablename__ = 'deposits'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    amount_usd = Column(Float, nullable=False)
    notes = Column(String)
