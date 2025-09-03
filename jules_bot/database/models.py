from sqlalchemy import Column, Integer, String, DateTime, JSON, Boolean, Numeric
from sqlalchemy.sql import func
import datetime
from decimal import Decimal
from .base import Base

class PriceHistory(Base):
    __tablename__ = 'price_history'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    open = Column(Numeric(20, 8))
    high = Column(Numeric(20, 8))
    low = Column(Numeric(20, 8))
    close = Column(Numeric(20, 8))
    volume = Column(Numeric(20, 8))
    symbol = Column(String)

class Trade(Base):
    def to_dict(self):
        result = {}
        for key in self.__mapper__.c.keys():
            value = getattr(self, key)
            if isinstance(value, datetime.datetime):
                result[key] = value.isoformat()
            elif isinstance(value, Decimal):
                result[key] = str(value)
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
    linked_trade_id = Column(String, nullable=True, index=True) # Used to link a SELL back to a BUY
    exchange = Column(String, nullable=False)
    status = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    usd_value = Column(Numeric(20, 8), nullable=False)
    commission = Column(Numeric(20, 8))
    commission_asset = Column(String)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    exchange_order_id = Column(String)
    binance_trade_id = Column(Integer)
    decision_context = Column(JSON)
    sell_target_price = Column(Numeric(20, 8))
    sell_price = Column(Numeric(20, 8))
    sell_usd_value = Column(Numeric(20, 8))
    commission_usd = Column(Numeric(20, 8))
    realized_pnl_usd = Column(Numeric(20, 8))
    hodl_asset_amount = Column(Numeric(20, 8))
    hodl_asset_value_at_sell = Column(Numeric(20, 8))
    backtest_id = Column(String)

    # Fields for Trailing Take-Profit
    is_trailing = Column(Boolean, default=False, nullable=False)
    highest_price_since_breach = Column(Numeric(20, 8), nullable=True)

    # Fields for Intelligent Trailing Stop
    is_smart_trailing_active = Column(Boolean, default=False, nullable=False)
    smart_trailing_activation_price = Column(Numeric(20, 8), nullable=True)
    smart_trailing_highest_price = Column(Numeric(20, 8), nullable=True)
    smart_trailing_activation_threshold = Column(Numeric(20, 8), nullable=True)


class BotStatus(Base):
    __tablename__ = 'bot_status'
    id = Column(Integer, primary_key=True)
    bot_id = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    is_running = Column(Boolean, default=False)
    session_pnl_usd = Column(Numeric(20, 8), default=0.0)
    session_pnl_percent = Column(Numeric(20, 8), default=0.0)
    open_positions = Column(Integer, default=0)
    portfolio_value_usd = Column(Numeric(20, 8), default=0.0)
    market_regime = Column(Integer)
    operating_mode = Column(String)
    buy_target = Column(Numeric(20, 8))
    buy_progress = Column(Numeric(5, 2))
    last_buy_condition = Column(String) # To store detailed feedback
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
