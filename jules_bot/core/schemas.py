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
    held_quantity: Optional[float] = None

    def to_influxdb_point(self):
        """Converts the dataclass to an InfluxDB Point structure."""
        from influxdb_client import Point

        p = Point("trades") \
            .tag("run_id", self.run_id) \
            .tag("environment", self.environment) \
            .tag("strategy_name", self.strategy_name) \
            .tag("symbol", self.symbol) \
            .tag("trade_id", self.trade_id) \
            .tag("exchange", self.exchange) \
            .tag("status", self.status) \
            .field("order_type", self.order_type) \
            .field("price", self.price) \
            .field("quantity", self.quantity) \
            .field("usd_value", self.usd_value) \
            .field("commission", self.commission) \
            .field("commission_asset", self.commission_asset) \
            .time(self.timestamp)

        # --- Add Optional and Contextual Fields ---
        if self.exchange_order_id is not None:
            p = p.field("exchange_order_id", self.exchange_order_id)

        if self.sell_target_price is not None:
            p = p.field("sell_target_price", self.sell_target_price)

        if self.decision_context:
            for key, value in self.decision_context.items():
                if isinstance(value, (int, float, str, bool, np.int64, np.float64)):
                     p = p.field(key, value)

        # --- Add Fields for SELL trades ---
        if self.order_type == 'sell':
            if self.commission_usd is not None:
                p = p.field("commission_usd", self.commission_usd)
            if self.realized_pnl_usd is not None:
                p = p.field("realized_pnl_usd", self.realized_pnl_usd)
            if self.hodl_asset_amount is not None:
                p = p.field("hodl_asset_amount", self.hodl_asset_amount)
            if self.hodl_asset_value_at_sell is not None:
                p = p.field("hodl_asset_value_at_sell", self.hodl_asset_value_at_sell)

        # --- Add Legacy Fields for Backwards Compatibility ---
        if self.backtest_id:
            p = p.tag("backtest_id", self.backtest_id)
        if self.held_quantity is not None:
            p = p.field("held_quantity", self.held_quantity)

        return p
