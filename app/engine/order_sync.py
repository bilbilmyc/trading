"""订单同步模块。

同步交易所挂单状态，并把本地的执行意图按交易所订单号或客户端订单号重新关联。
提交超时的订单会保持 ``unknown``，直到交易所侧可证明其结果；绝不因为一次
open-orders 查询没有返回而把未知订单误判成已撤销。
"""

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from app.exchanges.base import ExchangeBase
from app.models.order import Order, OrderSide, OrderStatus, OrderType

_TERMINAL_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
}


class OrderSync:
    """维护本地订单视图，并从交易所挂单列表进行状态对账。"""

    def __init__(self, interval_seconds: int = 10):
        self.interval_seconds = interval_seconds
        # Key is either an exchange order id or ``client:<client_order_id>``.
        self._local_orders: dict[str, Order] = {}
        self._callbacks: list = []

    @staticmethod
    def _key(order: Order) -> str | None:
        if order.order_id:
            return str(order.order_id)
        if order.client_order_id:
            return f"client:{order.client_order_id}"
        return None

    @staticmethod
    def _exchange_name_matches(order: Order, exchange: ExchangeBase) -> bool:
        return order.exchange.strip().lower() == exchange.name.strip().lower()

    @staticmethod
    def _raw_order_id(raw: dict[str, Any]) -> str | None:
        value = raw.get("order_id") or raw.get("orderId") or raw.get("ordId")
        return str(value) if value not in (None, "") else None

    @staticmethod
    def _raw_client_order_id(raw: dict[str, Any]) -> str | None:
        value = (
            raw.get("client_order_id")
            or raw.get("clientOrderId")
            or raw.get("clientOid")
            or raw.get("clOrdId")
        )
        return str(value) if value not in (None, "") else None

    # ── 订单注册 ──────────────────────────────────────────────

    def track(self, order: Order) -> None:
        """登记本进程提交或恢复的订单。必须具备至少一个稳定标识。"""

        key = self._key(order)
        if key:
            self._local_orders[key] = order

    def forget(self, order_id: str) -> None:
        """按任一订单标识移除已结束订单。"""

        order = self._local_orders.pop(order_id, None)
        if order is None:
            order = self._local_orders.pop(f"client:{order_id}", None)
        if order is not None:
            key = self._key(order)
            if key:
                self._local_orders.pop(key, None)

    def on_sync(self, callback) -> None:
        """注册订单状态变化回调。

        回调签名：``async def callback(order: Order, changed: bool)``。
        """

        self._callbacks.append(callback)

    def _find_local(self, order_id: str | None, client_order_id: str | None) -> Order | None:
        if order_id and (local := self._local_orders.get(order_id)) is not None:
            return local
        if client_order_id:
            return self._local_orders.get(f"client:{client_order_id}")
        return None

    def _bind_exchange_order_id(self, order: Order, order_id: str | None) -> None:
        if not order_id or order.order_id == order_id:
            return
        old_key = self._key(order)
        order.order_id = order_id
        if old_key and old_key != order_id:
            self._local_orders.pop(old_key, None)
        self._local_orders[order_id] = order

    # ── 单次同步 ──────────────────────────────────────────────

    async def sync(self, exchange: ExchangeBase, symbol: str | None = None) -> int:
        """拉取交易所挂单，按订单号/客户端订单号对账。

        ``unknown`` / ``submitting`` 订单只会在交易所返回可关联的订单时转为
        已知状态；它们不在本轮挂单中时保留为未知，避免网络超时后的重复下单。
        """

        changed = 0
        try:
            open_orders = await exchange.get_open_orders(symbol)
        except Exception as exc:
            logger.warning(f"OrderSync: get_open_orders failed: {exc}")
            return 0

        exchange_ids: set[str] = set()
        for raw in open_orders:
            if not isinstance(raw, dict):
                continue
            order_id = self._raw_order_id(raw)
            client_order_id = self._raw_client_order_id(raw)
            if order_id:
                exchange_ids.add(order_id)

            local = self._find_local(order_id, client_order_id)
            raw_status = str(raw.get("status", "")).lower()
            new_status = self._translate_status(raw_status)

            if local is not None:
                self._bind_exchange_order_id(local, order_id)
                if client_order_id and not local.client_order_id:
                    local.client_order_id = client_order_id

                before_fill = (local.filled_quantity, local.avg_fill_price)
                self._apply_exchange_fields(local, raw)
                state_changed = bool(new_status and local.status != new_status)
                fill_changed = before_fill != (local.filled_quantity, local.avg_fill_price)
                if state_changed:
                    local.status = new_status
                    local.updated_at = datetime.utcnow()
                if state_changed or fill_changed:
                    changed += 1
                    await self._notify(local)

                if local.status in _TERMINAL_STATUSES:
                    self.forget(self._key(local) or "")
                continue

            if new_status in {
                OrderStatus.PENDING,
                OrderStatus.PARTIALLY_FILLED,
                OrderStatus.FILLED,
            }:
                parsed = self._parse_exchange_order(raw, exchange.name)
                if parsed is not None:
                    self.track(parsed)
                    await self._notify(parsed)
                    if parsed.status in _TERMINAL_STATUSES:
                        self.forget(self._key(parsed) or "")

        # Only reconcile orders belonging to this venue. A missing active order is
        # normally cancelled, except ambiguous submissions where absence is not proof.
        for key, local in list(self._local_orders.items()):
            if not self._exchange_name_matches(local, exchange):
                continue
            if local.status in {OrderStatus.UNKNOWN, OrderStatus.SUBMITTING}:
                continue
            if local.is_active and local.order_id and local.order_id not in exchange_ids:
                local.status = OrderStatus.CANCELLED
                local.updated_at = datetime.utcnow()
                changed += 1
                await self._notify(local)
                self.forget(key)

        return changed

    # ── 内部 ──────────────────────────────────────────────────

    @staticmethod
    def _apply_exchange_fields(order: Order, raw: dict[str, Any]) -> None:
        filled = raw.get("filled_quantity") or raw.get("executedQty") or raw.get("filled")
        if filled is not None:
            try:
                order.filled_quantity = max(0.0, float(filled))
            except (TypeError, ValueError):
                pass
        avg_price = raw.get("avg_fill_price") or raw.get("avgPrice") or raw.get("average")
        if avg_price is not None:
            try:
                order.avg_fill_price = float(avg_price)
            except (TypeError, ValueError):
                pass

    async def _notify(self, order: Order) -> None:
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(order, True)
                else:
                    callback(order, True)
            except Exception as exc:
                logger.warning(f"OrderSync callback error: {exc}")

    @staticmethod
    def _translate_status(raw: str) -> OrderStatus | None:
        mapping = {
            "submitting": OrderStatus.SUBMITTING,
            "submitted": OrderStatus.SUBMITTED,
            "unknown": OrderStatus.UNKNOWN,
            "new": OrderStatus.PENDING,
            "open": OrderStatus.PENDING,
            "pending": OrderStatus.PENDING,
            "live": OrderStatus.PENDING,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "partiallyfilled": OrderStatus.PARTIALLY_FILLED,
            "partial": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "closed": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
            "expired": OrderStatus.EXPIRED,
        }
        return mapping.get(raw)

    @classmethod
    def _parse_exchange_order(cls, raw: dict[str, Any], exchange_name: str) -> Order | None:
        order_id = cls._raw_order_id(raw)
        client_order_id = cls._raw_client_order_id(raw)
        if not order_id and not client_order_id:
            return None
        try:
            side = OrderSide(str(raw.get("side", "buy")).lower())
            order_type = OrderType(str(raw.get("type") or raw.get("order_type") or "limit").lower())
            quantity = float(raw.get("quantity") or raw.get("origQty") or raw.get("size") or 0)
            if quantity <= 0:
                return None
            status = (
                cls._translate_status(str(raw.get("status", "new")).lower()) or OrderStatus.PENDING
            )
            price_value = raw.get("price")
            price = float(price_value) if price_value not in (None, "", "0") else None
            order = Order(
                order_id=order_id,
                client_order_id=client_order_id,
                exchange=exchange_name,
                symbol=str(raw.get("symbol") or raw.get("instId") or "UNKNOWN"),
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                status=status,
            )
            cls._apply_exchange_fields(order, raw)
            return order
        except (TypeError, ValueError) as exc:
            logger.debug(f"OrderSync: skip malformed exchange order: {exc}")
            return None

    @property
    def tracked_count(self) -> int:
        """Number of distinct locally tracked orders."""

        return len({id(order) for order in self._local_orders.values()})

    @property
    def open_orders(self) -> list[Order]:
        return list(
            {id(order): order for order in self._local_orders.values() if order.is_active}.values()
        )
