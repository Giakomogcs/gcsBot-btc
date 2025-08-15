from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
import datetime
from .base import Base

class PortfolioSnapshot(Base):
    __tablename__ = 'portfolio_snapshots'
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    total_portfolio_value_usd = Column(Float, nullable=False)
    usd_balance = Column(Float, nullable=False)
    open_positions_value_usd = Column(Float, nullable=False)
    realized_pnl_usd = Column(Float, nullable=False)
    btc_treasury_amount = Column(Float, nullable=False)
    btc_treasury_value_usd = Column(Float, nullable=False)
    evolution_percent_vs_previous = Column(Float)

class FinancialMovement(Base):
    __tablename__ = 'financial_movements'
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    movement_type = Column(String, nullable=False)  # 'DEPOSIT' or 'WITHDRAWAL'
    amount_usd = Column(Float, nullable=False)
    notes = Column(Text)
