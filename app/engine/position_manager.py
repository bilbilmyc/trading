"""
持仓管理模块

负责持仓跟踪、盈亏计算、仓位调整等功能。
"""

import asyncio
from typing import Any

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

    async def update_position(
        self,
        exchange: str,
        symbol: str,
        quantity: float,
        price: float,
        side: str
    ):
        """更新持仓信息"""
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
            if side.lower() == 'buy':
                qty_change = quantity
            else:
                qty_change = -quantity

            self._positions[key].update_position(qty_change, price)

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

    async def get_total_pnl(self) -> dict[str, float]:
        """获取总盈亏"""
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        realized = sum(p.realized_pnl for p in self._positions.values())
        return {
            'unrealized_pnl': unrealized,
            'realized_pnl': realized,
            'total_pnl': unrealized + realized,
        }

    async def update_balance(
        self,
        exchange: str,
        currency: str,
        total: float,
        available: float,
        frozen: float = None
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
                self._balances[exchange][currency].update_balance(
                    total, available, frozen
                )

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
                if currency == 'USDT':
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
                positions.append({
                    'symbol': pos.symbol,
                    'exchange': pos.exchange,
                    'quantity': pos.quantity,
                    'avg_entry_price': pos.avg_entry_price,
                    'current_price': pos.current_price,
                    'unrealized_pnl': pos.unrealized_pnl,
                    'pnl_pct': pos.pnl_percentage,
                })

        return {
            'total_unrealized_pnl': pnl['unrealized_pnl'],
            'total_realized_pnl': pnl['realized_pnl'],
            'total_pnl': pnl['total_pnl'],
            'active_positions': len(positions),
            'positions': positions,
        }
