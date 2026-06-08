"""
Contract trading models.

These models describe perpetual/futures orders in a unified shape before each
exchange adapter translates them to native OKX/Binance fields.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MarketType(str, Enum):
    """Supported market categories."""

    SPOT = "spot"
    SWAP = "swap"


class MarginMode(str, Enum):
    """Contract margin mode."""

    CROSS = "cross"
    ISOLATED = "isolated"


class PositionSide(str, Enum):
    """Position side used by contract exchanges."""

    NET = "net"
    LONG = "long"
    SHORT = "short"


class LiquidityType(str, Enum):
    """Whether an order is expected to add or remove liquidity."""

    MAKER = "maker"
    TAKER = "taker"


class ContractOrderIntent(str, Enum):
    """High-level action requested by the strategy or API."""

    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"
    OPEN_SHORT = "open_short"
    CLOSE_SHORT = "close_short"


class FeeRate(BaseModel):
    """Maker/taker fee rates for a symbol."""

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    maker: float = Field(..., description="Maker fee rate, e.g. 0.0002")
    taker: float = Field(..., description="Taker fee rate, e.g. 0.0005")
    raw: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ContractOrderRequest(BaseModel):
    """Unified request for opening or closing a contract position."""

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, description="BTC-USDT-SWAP or BTCUSDT")
    intent: ContractOrderIntent
    quantity: float = Field(..., gt=0)
    order_type: str = Field("limit", pattern="^(market|limit|post_only|ioc|fok|MARKET|LIMIT|POST_ONLY|IOC|FOK)$")
    price: Optional[float] = Field(None, gt=0)
    margin_mode: MarginMode = MarginMode.CROSS
    position_side: PositionSide = PositionSide.NET
    leverage: Optional[int] = Field(None, gt=0)
    reduce_only: Optional[bool] = None
    client_order_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CostEstimate(BaseModel):
    """Local estimate of execution cost before sending an order."""

    exchange: str
    symbol: str
    notional: float = Field(..., ge=0)
    liquidity: LiquidityType
    fee_rate: float
    estimated_fee: float
    raw_fee: FeeRate
    notes: list[str] = Field(default_factory=list)
