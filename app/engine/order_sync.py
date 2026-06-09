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
        self._local_orders: Dict[str, Order] = {}  # 订单号 -> 本地订单模型
        self._callbacks: List = []
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # ── 生命周期 ──────────────────────────────────────────────

    def start(self) -> None:
        """启动后台订单同步循环。"""

        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(f"OrderSync started (interval={self.interval_seconds}s)")

    async def stop(self) -> None:
        """停止后台订单同步循环。"""

        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        logger.info("OrderSync stopped")

    # ── 订单注册 ──────────────────────────────────────────────

    def track(self, order: Order) -> None:
        """登记本进程提交的订单，后续用于同步状态。"""

        if order.order_id:
            self._local_orders[order.order_id] = order

    def forget(self, order_id: str) -> None:
        """从本地跟踪列表移除已结束订单。"""

        self._local_orders.pop(order_id, None)

    def on_sync(self, callback) -> None:
        """注册订单状态变化回调。

        回调签名：``async def callback(order: Order, changed: bool)``
        """

        self._callbacks.append(callback)

    # ── 单次同步 ──────────────────────────────────────────────

    async def sync(self, exchange: ExchangeBase, symbol: Optional[str] = None) -> int:
        """从交易所拉取挂单并更新本地订单记录。

        返回状态发生变化的订单数量。
        """

        changed = 0
        try:
            open_orders = await exchange.get_open_orders(symbol)
        except Exception as exc:
            logger.warning(f"OrderSync: get_open_orders failed: {exc}")
            return 0

        # 先收集交易所侧仍处于挂单状态的订单 ID。
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

                    # 订单进入终态后就不再继续跟踪。
                    if new_status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
                        self.forget(oid)

            elif raw_status in ("filled", "partially_filled", "new", "open"):
                # 本进程不知道的订单，可能来自手动下单或其他进程，先纳入本地跟踪。
                parsed = self._parse_exchange_order(raw, exchange.name)
                if parsed is not None:
                    self._local_orders[oid] = parsed
                    await self._notify(parsed)

        # 本地还活跃、但交易所挂单列表里消失的订单，按已撤销处理。
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
        """后台同步循环。"""

        while self._running:
            await asyncio.sleep(self.interval_seconds)

    async def _notify(self, order: Order) -> None:
        """触发单个订单的同步回调。"""

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
        """把交易所状态字符串映射成统一 OrderStatus。"""

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
        """把交易所原始订单字典转换成本地 Order 模型。"""

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
