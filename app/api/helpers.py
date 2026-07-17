"""Stateless helpers for the HTTP layer.

These functions are pure utilities that don't depend on `AppState`,
`get_state`, or any closure — they can be imported and called from
anywhere. Stateful helpers (e.g. `call_exchange` which needs the
running engine) stay in `server.py`.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime
from typing import Any

from app.models.contract import ContractOrderRequest, LiquidityType


def extract_order_id(result: Any) -> str | None:
    """尽量从不同交易所返回里取订单号。

    Binance、OKX、Bitget 的字段名不完全一样，所以这里做一层兼容。
    后续引入正式 OMS 后，订单号抽取应该下沉到各交易所适配器。
    """

    if not isinstance(result, dict):
        return None
    for key in ("order_id", "orderId", "ordId", "clientOid", "clOrdId"):
        value = result.get(key)
        if value:
            return str(value)
    raw = result.get("raw")
    if isinstance(raw, dict):
        return extract_order_id(raw)
    return None


def generate_client_order_id() -> str:
    """生成交易所可接受的客户端订单号。

    这个 ID 会写入交易所订单请求，也会进入 SQLite 审计事件。
    前端先调用 preview 拿到这个 ID，再用同一个 ID 提交订单，方便排查和重试。
    """

    return f"qt{datetime.utcnow():%y%m%d%H%M%S}{secrets.token_hex(5)}"


def ensure_client_order_id(request: Any) -> Any:
    """Return a request with a stable client id, preserving the input type."""

    if getattr(request, "client_order_id", None):
        return request
    return request.model_copy(update={"client_order_id": generate_client_order_id()})


def ensure_contract_client_order_id(request: ContractOrderRequest) -> ContractOrderRequest:
    """保证合约订单一定带 client_order_id。"""

    return ensure_client_order_id(request)


def execution_fingerprint(request: Any) -> str:
    """Hash the economic order intent, excluding its idempotency key.

    A reused client id must describe precisely the same requested trade;
    otherwise retrying it could accidentally turn a stale request into a
    different order.
    """

    payload = request.model_dump(mode="json")
    payload.pop("client_order_id", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def infer_liquidity(order_type: str) -> LiquidityType:
    """按订单类型推断预估手续费用 maker 还是 taker 费率。"""

    normalized = order_type.lower()
    if normalized in {"market", "ioc", "fok"}:
        return LiquidityType.TAKER
    return LiquidityType.MAKER


__all__ = [
    "extract_order_id",
    "generate_client_order_id",
    "ensure_client_order_id",
    "ensure_contract_client_order_id",
    "execution_fingerprint",
    "infer_liquidity",
]
