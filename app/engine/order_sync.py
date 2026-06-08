"""
订单同步模块

定时从交易所拉取挂单 / 成交状态，更新本地 Order 记录。
确保引擎内部的订单视图与交易所实际状态保持一致。
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from app.exchanges.base import ExchangeBase
from app.models.order import Order, OrderSide, OrderStatus, OrderType


class OrderSync:
    """订单同步器

    周期性地：
    1. 拉取交易所所有未成交订单
    2. 对比本地记录，更新已成交 / 已取消的订单
    3. 推送状态变更回调
    """

    def __init__(self, interval_seconds: int = 10):
        self.interval_seconds = interval_seconds
        self._local_orders: Dict[str, Order] = {}  # order_id -> Order
        self._callbacks: List = []
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # ── 生命周期 ──────────────────────────────────────────────

    def start(self) -> None:
        """Start the background sync loop (caller must await the task loop)."""

        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(f"OrderSync started (interval={self.interval_seconds}s)")

    async def stop(self) -> None:
        """Stop the background sync loop."""

        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        logger.info("OrderSync stopped")

    # ── 订单注册 ──────────────────────────────────────────────

    def track(self, order: Order) -> None:
        """Register a locally-placed order for syncing."""

        if order.order_id:
            self._local_orders[order.order_id] = order

    def forget(self, order_id: str) -> None:
        """Remove a completed order from local tracking."""

        self._local_orders.pop(order_id, None)

    def on_sync(self, callback) -> None:
        """Register a callback invoked for each order status change.

        Callback signature: ``async def callback(order: Order, changed: bool)``
        """

        self._callbacks.append(callback)

    # ── 单次同步 ──────────────────────────────────────────────

    async def sync(self, exchange: ExchangeBase, symbol: Optional[str] = None) -> int:
        """Pull open orders from the exchange and update local records.

        Returns the number of orders whose status changed.
        """

        changed = 0
        try:
            open_orders = await exchange.get_open_orders(symbol)
        except Exception as exc:
            logger.warning(f"OrderSync: get_open_orders failed: {exc}")
            return 0

        # Build a set of exchange-side open order IDs
        exchange_ids: Set[str] = set()
        for raw in open_orders:
            oid = str(raw.get("order_id") or raw.get("orderId") or "")
            if not oid:
                continue
            exchange_ids.add(oid)

            local = self._local_orders.get(oid)
            raw_status = str(raw.get("status", "")).lower()

            if local is not None:
                new_status = self._translate_status(raw_status)
                if new_status and local.status != new_status:
                    local.status = new_status
                    local.updated_at = datetime.utcnow()
                    changed += 1
                    await self._notify(local)

                    # Clean up terminal statuses
                    if new_status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
                        self.forget(oid)

            elif raw_status in ("filled", "partially_filled", "new", "open"):
                # Unknown order — created outside this process, track it
                parsed = self._parse_exchange_order(raw, exchange.name)
                if parsed is not None:
                    self._local_orders[oid] = parsed
                    await self._notify(parsed)

        # Mark locally-tracked orders that disappeared on exchange as cancelled
        for oid, local in list(self._local_orders.items()):
            if local.is_active and oid not in exchange_ids:
                local.status = OrderStatus.CANCELLED
                local.updated_at = datetime.utcnow()
                changed += 1
                await self._notify(local)
                self.forget(oid)

        return changed

    # ── 内部 ──────────────────────────────────────────────────

    async def _sync_loop(self) -> None:
        """Background sync loop."""

        while self._running:
            await asyncio.sleep(self.interval_seconds)

    async def _notify(self, order: Order) -> None:
        """Fire callbacks for one order."""

        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(order, True)
                else:
                    cb(order, True)
            except Exception as exc:
                logger.warning(f"OrderSync callback error: {exc}")

    @staticmethod
    def _translate_status(raw: str) -> Optional[OrderStatus]:
        """Map exchange status strings to OrderStatus enum."""

        mapping = {
            "new": OrderStatus.PENDING,
            "open": OrderStatus.PENDING,
            "pending": OrderStatus.PENDING,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
            "expired": OrderStatus.EXPIRED,
        }
        return mapping.get(raw)

    @staticmethod
    def _parse_exchange_order(raw: Dict[str, Any], exchange_name: str) -> Optional[Order]:
        """Build an Order model from an exchange's raw order dict."""

        try:
            oid = str(raw.get("order_id") or raw.get("orderId") or "")
            sym = str(raw.get("symbol") or "")
            side_raw = str(raw.get("side", "")).lower()
            raw_status = str(raw.get("status", "")).lower()
            qty = float(raw.get("quantity") or raw.get("origQty") or 0)
            price = float(raw.get("price") or 0) or None

            if not oid or not sym or not side_raw:
                return None

            side = OrderSide.BUY if side_raw in ("buy", "BUY") else OrderSide.SELL
            order_type = OrderType.MARKET if str(raw.get("order_type") or raw.get("type", "")).lower() == "market" else OrderType.LIMIT
            status = OrderSync._translate_status(raw_status) or OrderStatus.PENDING

            return Order(
                symbol=sym,
                exchange=exchange_name,
                side=side,
                order_type=order_type,
                quantity=qty,
                price=price,
                order_id=oid,
                status=status,
                filled_quantity=float(raw.get("filled_quantity") or raw.get("executedQty") or 0),
                avg_fill_price=float(raw.get("avg_fill_price") or raw.get("avgPrice") or 0) or None,
            )
        except Exception as exc:
            logger.debug(f"OrderSync: failed to parse exchange order: {exc}")
            return None

    @property
    def tracked_count(self) -> int:
        return len(self._local_orders)

    @property
    def open_orders(self) -> List[Order]:
        return [o for o in self._local_orders.values() if o.is_active]
