import datetime
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

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
    all trade records written to the database.

    This schema acts as a contract for what constitutes a valid trade record.
    """
    # Tags (indexed for fast queries)
    mode: str  # 'live', 'testnet', or 'backtest'
    strategy_name: str
    symbol: str
    trade_id: str
    exchange: str

    # Fields (the actual data points)
    order_type: str  # 'buy' or 'sell'
    price: float
    quantity: float
    usd_value: float
    commission: float
    commission_asset: str
    exchange_order_id: Optional[str] = None

    # Fields specific to 'sell' orders
    realized_pnl: Optional[float] = None
    held_quantity: Optional[float] = None # The amount of the asset held before this sell

    # Timestamp for the record
    # Using field to ensure a UTC timestamp is generated if not provided
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_influxdb_point(self):
        """Converts the dataclass to an InfluxDB Point structure."""
        from influxdb_client import Point

        p = Point("trades") \
            .tag("mode", self.mode) \
            .tag("strategy_name", self.strategy_name) \
            .tag("symbol", self.symbol) \
            .tag("trade_id", self.trade_id) \
            .tag("exchange", self.exchange) \
            .field("order_type", self.order_type) \
            .field("price", self.price) \
            .field("quantity", self.quantity) \
            .field("usd_value", self.usd_value) \
            .field("commission", self.commission) \
            .field("commission_asset", self.commission_asset) \
            .time(self.timestamp)

        if self.exchange_order_id is not None:
            p = p.field("exchange_order_id", self.exchange_order_id)

        if self.order_type == 'sell':
            if self.realized_pnl is not None:
                p = p.field("realized_pnl", self.realized_pnl)
            if self.held_quantity is not None:
                p = p.field("held_quantity", self.held_quantity)

        return p
