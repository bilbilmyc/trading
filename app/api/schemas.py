"""Pydantic request/response models for the HTTP layer.

Extracted from `app/api/server.py` so the models live next to the FastAPI
app but separately from route handlers. Pydantic schemas are pure data
shapes — they don't depend on `state`, `get_state()`, or any closure —
so they're safe to live in a leaf module that anyone can import.

Route handlers stay in `server.py`; the split is gradual and conservative.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Trading orders ────────────────────────────────────────────────


class OrderRequest(BaseModel):
    """现货下单请求体。

    FastAPI 会根据这个 Pydantic 模型校验前端传入的 JSON。
    校验通过后，路由函数里拿到的 request 就是一个 OrderRequest 对象。
    """

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., pattern="^(buy|sell|BUY|SELL)$")
    order_type: str = Field("market", pattern="^(market|limit|MARKET|LIMIT)$")
    quantity: float = Field(..., gt=0)
    price: float | None = Field(None, gt=0)
    quote_order_qty: float | None = Field(None, gt=0)
    # Optional caller-supplied idempotency key. The server creates one when
    # omitted and returns it in the response so an ambiguous retry is safe.
    client_order_id: str | None = Field(None, min_length=4, max_length=64)


# ── Strategy management ───────────────────────────────────────────


class SMAStrategyRequest(BaseModel):
    """创建 SMA 策略时前端传入的请求体。"""

    name: str | None = Field(None, min_length=1, max_length=64)
    exchange: str = Field("binance_usdm", min_length=1)
    symbol: str = Field("BTCUSDT", min_length=1)
    interval: str = Field("1m", min_length=1, max_length=16)
    short_window: int = Field(5, ge=1)
    long_window: int = Field(20, ge=2)
    min_data_points: int | None = Field(None, ge=2)
    enabled: bool = False
    mode: str = Field("signal", pattern="^(signal|paper)$")


class StrategyModeRequest(BaseModel):
    """切换策略运行模式的请求体。

    `live` 表示策略希望执行实盘（仍受全局 `enable_live_trading` 开关
    与 `LiveTradingGuard` 熔断保护）。
    """

    mode: str = Field(..., pattern="^(signal|paper|live)$")


class SignalRunnerRequest(BaseModel):
    """启动或手动运行信号运行器的请求体。"""

    poll_seconds: int = Field(60, ge=5, le=3600)
    candle_limit: int = Field(80, ge=20, le=500)


# ── Paper trading & risk ──────────────────────────────────────────


class PaperResetRequest(BaseModel):
    """重置模拟盘账户的请求体。"""

    initial_cash: float | None = Field(None, gt=0)


class KillSwitchRequest(BaseModel):
    """全局 Kill Switch 切换请求体。

    enabled=true 表示立即熔断全部真实交易；enabled=false 表示恢复交易权限。
    reason 会写入 SQLite 审计事件，方便复盘是谁因为什么原因切换了风控状态。
    """

    enabled: bool
    reason: str = Field("manual", min_length=1, max_length=200)


# ── LLM strategies ───────────────────────────────────────────────


class LLMStrategyCreateRequest(BaseModel):
    """创建 LLM 策略实例的请求体。"""

    name: str | None = Field(None, min_length=1, max_length=64)
    exchange: str = Field("binance_usdm", min_length=1)
    symbol: str = Field("BTCUSDT", min_length=1)
    interval: str = Field("1h", min_length=1, max_length=16)
    default_order_amount: float | None = Field(None, gt=0)
    min_confidence: float = Field(0.5, ge=0.0, le=1.0)
    enabled: bool = False
    mode: str = Field("signal", pattern="^(signal|paper|live)$")


# ── AI analysis & backtest ────────────────────────────────────────


class AIAnalyzeRequest(BaseModel):
    """AI 市场分析请求体。"""

    exchange: str = Field("binance_usdm", min_length=1)
    symbol: str = Field("BTCUSDT", min_length=1)
    interval: str = Field("1h", min_length=1, max_length=8)
    limit: int = Field(30, ge=10, le=100)


class SizingRequest(BaseModel):
    """Position-sizing request body.

    The frontend uses this to preview how many contracts to buy for a
    given risk budget, and the engine's risk check uses the same shape
    before approving a live order.
    """

    account_equity: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    stop_loss_price: float = Field(..., gt=0)
    take_profit_price: float | None = Field(None, gt=0)
    leverage: float = Field(1.0, gt=0)
    risk_pct: float = Field(0.02, gt=0, lt=1)
    contract_size: float = Field(1.0, gt=0)
    min_quantity: float = Field(0.001, gt=0)


class BacktestRequest(BaseModel):
    """SMA backtest request; all execution assumptions are explicit."""

    klines: list[dict[str, Any]] = Field(..., min_length=1, max_length=10_000)
    short_window: int = Field(5, gt=0)
    long_window: int = Field(20, gt=0)
    initial_capital: float = Field(10_000.0, gt=0)
    position_size_pct: float = Field(1.0, gt=0, le=1.0)
    fee_rate: float = Field(0.001, ge=0.0, lt=1.0)
    slippage_rate: float = Field(0.0, ge=0.0, lt=1.0)
    stop_loss_pct: float | None = Field(None, gt=0.0, lt=1.0)
    take_profit_pct: float | None = Field(None, gt=0.0, lt=1.0)


class WalkForwardCandidate(BaseModel):
    """One SMA pair evaluated only within each walk-forward training segment."""

    short_window: int = Field(..., gt=0)
    long_window: int = Field(..., gt=0)


class WalkForwardRequest(BacktestRequest):
    """Strictly out-of-sample walk-forward validation request."""

    train_size: int = Field(..., ge=3, le=9_000)
    test_size: int = Field(..., ge=3, le=9_000)
    step_size: int | None = Field(None, ge=1, le=9_000)
    candidate_parameters: list[WalkForwardCandidate] = Field(default_factory=list, max_length=24)


class StrategyPromotionEvaluateRequest(BaseModel):
    """Operator-selected minimum paper-trading evidence for a promotion review."""

    min_closed_trades: int = Field(10, ge=1, le=10_000)
    min_win_rate: float = Field(0.45, ge=0.0, le=1.0)
    min_profit_factor: float = Field(1.05, gt=0.0, le=100.0)
    min_total_pnl: float = Field(0.0)


class StrategyPromotionDecisionRequest(BaseModel):
    """A manual decision on an eligible promotion review; never changes live mode."""

    approved: bool
    decided_by: str = Field("operator", min_length=1, max_length=80)
    note: str = Field(..., min_length=3, max_length=300)


class SuggestRequest(BaseModel):
    """Strategy-suggestion request — picks SMA vs RSI from kline stats."""

    klines: list[dict[str, Any]] = Field(..., min_length=1)
    prefer: str | None = None


# ── Position management & data sources ───────────────────────────


class ClosePositionRequest(BaseModel):
    """平仓请求体。"""

    symbol: str
    exchange: str
    exit_quantity: float | None = Field(default=None, gt=0)
    position_size_pct: float = Field(1.0, gt=0, le=1.0)


class ReconciliationRecoveryRequest(BaseModel):
    """Explicit operator acknowledgement after account/position reconciliation."""

    note: str = Field(..., min_length=3, max_length=300)


class CustomSourceRequest(BaseModel):
    """注册自定义数据源的请求体。"""

    name: str = Field(..., min_length=1, max_length=64)
    base_url: str = Field(..., min_length=1)
    ticker_path: str = "/ticker/{symbol}"
    klines_path: str = "/klines"
    trades_path: str = "/trades"
    klines_array_key: str | None = None


__all__ = [
    "OrderRequest",
    "SMAStrategyRequest",
    "StrategyModeRequest",
    "SignalRunnerRequest",
    "PaperResetRequest",
    "KillSwitchRequest",
    "LLMStrategyCreateRequest",
    "AIAnalyzeRequest",
    "SizingRequest",
    "BacktestRequest",
    "WalkForwardCandidate",
    "WalkForwardRequest",
    "StrategyPromotionEvaluateRequest",
    "StrategyPromotionDecisionRequest",
    "SuggestRequest",
    "ClosePositionRequest",
    "ReconciliationRecoveryRequest",
    "CustomSourceRequest",
]
