import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import numpy as np

@dataclass
class PriceHistoryPoint:
    """
    Represents a single point of OHLCV price data for a specific symbol.
    This structure ensures that all price data conforms to a standard contract.
    """
    timestamp: datetime.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str # e.g., 'BTCUSDT'

@dataclass
class TradePoint:
    """
    Represents a single trade event, ensuring a consistent data structure for
    all trade records written to the database. This schema acts as a contract
    for what constitutes a valid trade record.
    """
    # --- TAGS (indexed for fast queries) ---
    run_id: str
    environment: str  # e.g., 'backtest', 'paper_trade', 'live_trade'
    strategy_name: str
    symbol: str
    trade_id: str
    exchange: str
    status: str # e.g., 'OPEN', 'CLOSED', 'TREASURED'

    # --- FIELDS (not indexed) ---
    order_type: str  # 'buy' or 'sell'
    price: float
    quantity: float
    usd_value: float
    commission: float  # Original commission in asset terms (e.g., BNB, USDT)
    commission_asset: str

    # --- Optional & Contextual Fields ---
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    exchange_order_id: Optional[str] = None
    binance_trade_id: Optional[int] = None
    decision_context: Optional[Dict[str, Any]] = None  # Stores RSI, MACD, etc.

    # --- Fields for BUY trades ---
    sell_target_price: Optional[float] = None

    # --- Fields for SELL trades ---
    commission_usd: Optional[float] = None
    realized_pnl_usd: Optional[float] = None
    hodl_asset_amount: Optional[float] = None
    hodl_asset_value_at_sell: Optional[float] = None

    # --- Legacy Fields (to be deprecated) ---
    backtest_id: Optional[str] = None
    realized_pnl: Optional[float] = None
    held_quantity: Optional[float] = None

