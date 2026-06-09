"""
合约交易模型。

API 和策略先生成统一的合约请求模型，然后各交易所适配器再把它翻译成
Binance / Bitget / OKX 自己的字段。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class MarketType(str, Enum):
    """支持的市场类型。"""

    SPOT = "spot"
    SWAP = "swap"


class MarginMode(str, Enum):
    """合约保证金模式。"""

    CROSS = "cross"
    ISOLATED = "isolated"


class PositionSide(str, Enum):
    """合约持仓方向。"""

    NET = "net"
    LONG = "long"
    SHORT = "short"


class LiquidityType(str, Enum):
    """订单预期是挂单还是吃单，用于估算手续费。"""

    MAKER = "maker"
    TAKER = "taker"


class ContractOrderIntent(str, Enum):
    """策略或前端表达的高级交易意图。"""

    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"
    OPEN_SHORT = "open_short"
    CLOSE_SHORT = "close_short"


class FeeRate(BaseModel):
    """单个合约的 maker/taker 手续费率。"""

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    maker: float = Field(..., description="Maker 手续费率，例如 0.0002")
    taker: float = Field(..., description="Taker 手续费率，例如 0.0005")
    raw: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ContractOrderRequest(BaseModel):
    """统一合约下单请求，用于开仓或平仓。"""

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, description="例如 BTC-USDT-SWAP 或 BTCUSDT")
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
    """下单前的本地成本估算。"""

    exchange: str
    symbol: str
    notional: float = Field(..., ge=0)
    liquidity: LiquidityType
    fee_rate: float
    estimated_fee: float
    raw_fee: FeeRate
    notes: list[str] = Field(default_factory=list)
