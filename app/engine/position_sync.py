"""
持仓同步模块

定时从交易所拉取账户余额和持仓信息，同步到本地 PositionManager。
支持纯现货交易所和永续合约交易所的不同数据格式。
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from app.exchanges.base import ExchangeBase
from app.exchanges.contract_base import ContractExchangeBase
from app.engine.position_manager import PositionManager
from app.models.position import Position


class PositionSync:
    """持仓同步器

    周期性：
    1. 从交易所拉取余额
    2. 从交易所拉取合约持仓（如果支持）
    3. 同步到本地 PositionManager
    """

    def __init__(
        self,
        position_manager: PositionManager,
        interval_seconds: int = 15,
    ):
        self.position_manager = position_manager
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._callbacks: List = []

    # ── 生命周期 ──────────────────────────────────────────────

    def start(self) -> None:
        """启动后台持仓同步循环。"""

        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info(f"PositionSync started (interval={self.interval_seconds}s)")

    async def stop(self) -> None:
        """停止后台持仓同步循环。"""

        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        logger.info("PositionSync stopped")

    def on_sync(self, callback) -> None:
        """注册每轮同步完成后的回调。

        回调签名：``async def callback(exchange_name: str, changed: bool)``
        """

        self._callbacks.append(callback)

    # ── 同步逻辑 ──────────────────────────────────────────────

    async def sync(
        self,
        exchange: ExchangeBase,
        exchange_name: str,
        symbol: Optional[str] = None,
    ) -> int:
        """执行一次持仓同步，返回更新的持仓/余额数量。"""

        updated = 0

        # 1) 余额同步
        try:
            balances = await exchange.get_account_balance()
            for currency, total in balances.items():
                # 有些交易所返回 total/available 字典，有些只返回一个总余额数字。
                available = total
                if isinstance(total, dict):
                    available = float(total.get("available", total.get("free", 0)))
                    total_val = float(total.get("total", total.get("balance", 0)))
                else:
                    total_val = float(total)

                await self.position_manager.update_balance(
                    exchange_name,
                    currency,
                    total_val,
                    available,
                )
                updated += 1
        except Exception as exc:
            logger.warning(f"PositionSync [{exchange_name}] balance sync failed: {exc}")

        # 2) 合约持仓同步（仅合约交易所支持）
        if isinstance(exchange, ContractExchangeBase) and symbol:
            try:
                positions = await exchange.get_positions(symbol)
                for pos_raw in positions:
                    pos_symbol = str(pos_raw.get("symbol") or symbol)
                    quantity = float(pos_raw.get("quantity") or pos_raw.get("pos") or pos_raw.get("positionAmt") or 0)
                    avg_price = float(pos_raw.get("avg_price") or pos_raw.get("avgPx") or pos_raw.get("entryPrice") or 0)
                    current_price = float(pos_raw.get("current_price") or pos_raw.get("markPx") or pos_raw.get("markPrice") or 0)

                    local = await self.position_manager.get_position(exchange_name, pos_symbol)
                    if local is None and quantity != 0:
                        local = Position(
                            symbol=pos_symbol,
                            exchange=exchange_name,
                            quantity=quantity,
                            avg_entry_price=avg_price,
                            current_price=current_price,
                        )
                        await self._upsert_position(exchange_name, pos_symbol, local)
                        updated += 1
                    elif local is not None:
                        needs_update = (
                            local.quantity != quantity
                            or local.avg_entry_price != avg_price
                            or local.current_price != current_price
                        )
                        if needs_update:
                            local.quantity = quantity
                            local.avg_entry_price = avg_price
                            local.current_price = current_price
                            local.update_price(current_price)
                            await self._upsert_position(exchange_name, pos_symbol, local)
                            updated += 1
            except Exception as exc:
                logger.warning(f"PositionSync [{exchange_name}] contract positions sync failed: {exc}")

        # 有更新时通知回调。
        if updated > 0:
            for cb in self._callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(exchange_name, updated > 0)
                    else:
                        cb(exchange_name, updated > 0)
                except Exception as exc:
                    logger.warning(f"PositionSync callback error: {exc}")

        return updated

    # ── 内部 ──────────────────────────────────────────────────

    async def _sync_loop(self) -> None:
        """后台同步循环；真正绑定交易所的逻辑由 TradingEngine 负责。"""

        while self._running:
            await asyncio.sleep(self.interval_seconds)

    async def _upsert_position(self, exchange_name: str, symbol: str, position: Position) -> None:
        """直接写入持仓，绕过 update_position 的成交均价计算逻辑。"""

        key = f"{exchange_name}:{symbol}"
        self.position_manager._positions[key] = position

    @property
    def is_running(self) -> bool:
        return self._running
