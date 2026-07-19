"""
持仓管理模块

负责持仓跟踪、盈亏计算、仓位调整等功能。
"""

import asyncio
from typing import Any

from app.engine.portfolio_exposure import PortfolioExposure
from app.models.balance import Balance
from app.models.position import Position


class PositionManager:
    """持仓管理器

    负责：
    - 持仓跟踪
    - 盈亏计算
    - 仓位调整
    - 多交易所持仓管理
    """

    def __init__(self):
        self._positions: dict[str, Position] = {}  # 键格式：exchange:symbol
        self._balances: dict[str, dict[str, Balance]] = {}  # 结构：exchange -> currency -> Balance
        self._lock = asyncio.Lock()

    def _make_key(self, exchange: str, symbol: str) -> str:
        """生成持仓键"""
        return f"{exchange}:{symbol}"

    async def get_position(self, exchange: str, symbol: str) -> Position | None:
        """获取持仓"""
        key = self._make_key(exchange, symbol)
        return self._positions.get(key)

    async def get_all_positions(self) -> dict[str, Position]:
        """获取所有持仓"""
        return self._positions.copy()

    async def get_exposure_snapshot(
        self,
        symbol: str | None = None,
        reference_price: float | None = None,
    ) -> PortfolioExposure:
        """Return gross local exposure, overriding the checked symbol's price.

        PositionSync and strategy fills maintain this local view. The reference
        price from the incoming order replaces a potentially stale price for its
        own symbol, while other symbols retain their latest synchronized mark.
        """
        overrides = (
            {symbol.upper(): reference_price}
            if symbol is not None and reference_price is not None and reference_price > 0
            else None
        )
        async with self._lock:
            return PortfolioExposure.from_positions(
                self._positions.values(),
                price_overrides=overrides,
            )

    async def update_position(
        self, exchange: str, symbol: str, quantity: float, price: float, side: str
    ) -> float:
        """更新持仓信息，并返回该笔成交新增的已实现盈亏。"""
        async with self._lock:
            key = self._make_key(exchange, symbol)

            if key not in self._positions:
                self._positions[key] = Position(
                    symbol=symbol,
                    exchange=exchange,
                    quantity=0,
                    avg_entry_price=0,
                )

            # 根据买卖方向调整数量
            if side.lower() == "buy":
                qty_change = quantity
            else:
                qty_change = -quantity

            realized_pnl = self._positions[key].update_position(qty_change, price)
        # Outside the lock — gauge sync is cheap and idempotent.
        self.sync_positions_gauge()
        return realized_pnl

    async def update_price(self, exchange: str, symbol: str, price: float):
        """更新持仓价格"""
        key = self._make_key(exchange, symbol)
        if key in self._positions:
            self._positions[key].update_price(price)

    async def remove_position(self, exchange: str, symbol: str):
        """移除空仓"""
        key = self._make_key(exchange, symbol)
        async with self._lock:
            if key in self._positions and self._positions[key].is_flat():
                del self._positions[key]
        self.sync_positions_gauge()

    async def get_total_pnl(self) -> dict[str, float]:
        """获取总盈亏"""
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        realized = sum(p.realized_pnl for p in self._positions.values())
        return {
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "total_pnl": unrealized + realized,
        }

    async def update_balance(
        self, exchange: str, currency: str, total: float, available: float, frozen: float = None
    ):
        """更新余额"""
        async with self._lock:
            if exchange not in self._balances:
                self._balances[exchange] = {}

            if currency not in self._balances[exchange]:
                self._balances[exchange][currency] = Balance(
                    currency=currency,
                    exchange=exchange,
                    total=total,
                    available=available,
                    frozen=frozen or (total - available),
                )
            else:
                self._balances[exchange][currency].update_balance(total, available, frozen)

    async def get_balance(self, exchange: str, currency: str) -> Balance | None:
        """获取余额"""
        if exchange in self._balances:
            return self._balances[exchange].get(currency)
        return None

    async def get_all_balances(self, exchange: str | None = None) -> dict[str, Balance]:
        """获取所有余额"""
        if exchange:
            return self._balances.get(exchange, {})

        # 返回所有交易所的余额
        all_balances = {}
        for ex_balances in self._balances.values():
            all_balances.update(ex_balances)
        return all_balances

    async def get_portfolio_value(self, prices: dict[str, float]) -> float:
        """计算组合总价值

        Args:
            prices: 币种到价格的映射 (以 USDT 计价)
        """
        total_value = 0.0

        for exchange, balances in self._balances.items():
            for currency, balance in balances.items():
                if currency == "USDT":
                    total_value += balance.total
                elif currency in prices:
                    total_value += balance.total * prices[currency]

        return total_value

    async def get_position_summary(self) -> dict[str, Any]:
        """获取持仓汇总"""
        pnl = await self.get_total_pnl()
        positions = []

        for pos in self._positions.values():
            if not pos.is_flat():
                positions.append(
                    {
                        "symbol": pos.symbol,
                        "exchange": pos.exchange,
                        "quantity": pos.quantity,
                        "avg_entry_price": pos.avg_entry_price,
                        "current_price": pos.current_price,
                        "unrealized_pnl": pos.unrealized_pnl,
                        "pnl_pct": pos.pnl_percentage,
                    }
                )

        return {
            "total_unrealized_pnl": pnl["unrealized_pnl"],
            "total_realized_pnl": pnl["realized_pnl"],
            "total_pnl": pnl["total_pnl"],
            "active_positions": len(positions),
            "positions": positions,
        }

    def sync_positions_gauge(self) -> None:
        """Recompute qt_positions_active from in-memory state.

        Called after any mutation that adds / removes / fills positions.
        Cheap O(N) over self._positions; safe to invoke from sync hot paths.
        Wrapped defensively so a missing metrics module never breaks trades.
        """
        try:
            from app.engine.metrics import POSITIONS_ACTIVE
        except Exception:
            return
        by_exchange: dict[str, int] = {}
        for pos in self._positions.values():
            if not pos.is_flat():
                by_exchange[pos.exchange] = by_exchange.get(pos.exchange, 0) + 1
        for exchange_name, count in by_exchange.items():
            POSITIONS_ACTIVE.labels(exchange=exchange_name).set(count)
        # Zero out any exchange label that's no longer represented so
        # dashboards reflect 0 instead of a stale number.
        try:
            for metric in POSITIONS_ACTIVE.collect():
                for sample in metric.samples:
                    if sample.name.endswith("_active"):
                        label_exchange = sample.labels.get("exchange", "")
                        if label_exchange and label_exchange not in by_exchange:
                            POSITIONS_ACTIVE.labels(exchange=label_exchange).set(0)
        except Exception:
            pass
