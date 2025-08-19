from sqlalchemy import Column, Integer, String, Numeric, DateTime, Text
from sqlalchemy.sql import func
import datetime
from .base import Base

class PortfolioSnapshot(Base):
    __tablename__ = 'portfolio_snapshots'
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    total_portfolio_value_usd = Column(Numeric(20, 8), nullable=False)
    usd_balance = Column(Numeric(20, 8), nullable=False)
    open_positions_value_usd = Column(Numeric(20, 8), nullable=False)
    realized_pnl_usd = Column(Numeric(20, 8), nullable=False)
    btc_treasury_amount = Column(Numeric(20, 8), nullable=False)
    btc_treasury_value_usd = Column(Numeric(20, 8), nullable=False)
    evolution_percent_vs_previous = Column(Numeric(20, 8))

class FinancialMovement(Base):
    __tablename__ = 'financial_movements'
    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String, unique=True, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    movement_type = Column(String, nullable=False)  # 'DEPOSIT' or 'WITHDRAWAL'
    amount_usd = Column(Numeric(20, 8), nullable=False)
    notes = Column(Text)
