"""
模拟盘账户。

模拟盘和真实交易所执行完全分离：它消费策略信号，用公开行情价格模拟成交，
并维护一个虚拟 USDT 账户，供前端验证策略效果和后续持久化使用。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.strategies.base import Signal


class PaperTradingAccount:
    """用于验证信号的简化 USDT 模拟账户。"""

    def __init__(self, initial_cash: float = 10000.0, fee_rate: float = 0.0005):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.fee_rate = fee_rate
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.orders: List[Dict[str, Any]] = []
        self.enabled = True

    def reset(self, initial_cash: Optional[float] = None) -> None:
        """重置模拟账户状态。"""

        if initial_cash is not None:
            self.initial_cash = initial_cash
        self.cash = self.initial_cash
        self.positions.clear()
        self.orders.clear()

    def load_state(
        self,
        account: Optional[Dict[str, Any]],
        positions: List[Dict[str, Any]],
        orders: List[Dict[str, Any]],
    ) -> None:
        """从 SQLite 恢复模拟账户状态。"""

        if account:
            self.initial_cash = float(account.get("initial_cash", self.initial_cash))
            self.cash = float(account.get("cash", self.initial_cash))
            self.fee_rate = float(account.get("fee_rate", self.fee_rate))
            self.enabled = bool(account.get("enabled", self.enabled))

        self.positions = {
            self._position_key(str(position["exchange"]), str(position["symbol"])): {
                "exchange": position["exchange"],
                "symbol": position["symbol"],
                "quantity": float(position["quantity"]),
                "avg_entry_price": float(position["avg_entry_price"]),
                "current_price": float(position["current_price"]),
                "realized_pnl": float(position["realized_pnl"]),
                "unrealized_pnl": float(position["unrealized_pnl"]),
                "updated_at": position["updated_at"],
            }
            for position in positions
        }
        self.orders = [
            {
                "order_id": order["order_id"],
                "exchange": order["exchange"],
                "strategy": order["strategy"],
                "symbol": order["symbol"],
                "side": order["side"],
                "quantity": float(order["quantity"]),
                "price": float(order["price"]),
                "fee": float(order["fee"]),
                "realized_pnl": float(order["realized_pnl"]),
                "status": order["status"],
                "timestamp": order["timestamp"],
                "signal_metadata": order.get("signal_metadata", {}),
            }
            for order in orders
        ][-200:]

    def _position_key(self, exchange: str, symbol: str) -> str:
        return f"{exchange}:{symbol}"

    def mark_price(self, exchange: str, symbol: str, price: float) -> None:
        """更新单个模拟持仓的标记价格。"""

        key = self._position_key(exchange, symbol)
        position = self.positions.get(key)
        if not position:
            return
        position["current_price"] = price
        quantity = position["quantity"]
        avg_price = position["avg_entry_price"]
        if quantity > 0:
            position["unrealized_pnl"] = (price - avg_price) * quantity
        elif quantity < 0:
            position["unrealized_pnl"] = (avg_price - price) * abs(quantity)
        else:
            position["unrealized_pnl"] = 0.0
        position["updated_at"] = datetime.utcnow().isoformat()

    def apply_signal(
        self,
        exchange: str,
        strategy_name: str,
        signal: Signal,
        fill_price: float,
        default_quantity: float = 0.001,
    ) -> Optional[Dict[str, Any]]:
        """把一个可执行信号模拟为完全成交。"""

        if not self.enabled or not signal.is_actionable or fill_price <= 0:
            return None

        quantity = signal.quantity or default_quantity
        signed_quantity = quantity if signal.action.value == "buy" else -quantity
        key = self._position_key(exchange, signal.symbol)
        position = self.positions.setdefault(
            key,
            {
                "exchange": exchange,
                "symbol": signal.symbol,
                "quantity": 0.0,
                "avg_entry_price": 0.0,
                "current_price": fill_price,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "updated_at": datetime.utcnow().isoformat(),
            },
        )

        old_quantity = float(position["quantity"])
        old_avg = float(position["avg_entry_price"])
        fee = abs(quantity * fill_price) * self.fee_rate
        realized = 0.0

        if old_quantity == 0 or old_quantity * signed_quantity > 0:
            new_quantity = old_quantity + signed_quantity
            old_cost = abs(old_quantity) * old_avg
            new_cost = old_cost + abs(signed_quantity) * fill_price
            position["quantity"] = new_quantity
            position["avg_entry_price"] = new_cost / abs(new_quantity)
        else:
            closing_quantity = min(abs(old_quantity), abs(signed_quantity))
            if old_quantity > 0:
                realized = (fill_price - old_avg) * closing_quantity
            else:
                realized = (old_avg - fill_price) * closing_quantity

            new_quantity = old_quantity + signed_quantity
            position["realized_pnl"] += realized
            if new_quantity == 0:
                position["quantity"] = 0.0
                position["avg_entry_price"] = 0.0
            elif old_quantity * new_quantity > 0:
                position["quantity"] = new_quantity
            else:
                position["quantity"] = new_quantity
                position["avg_entry_price"] = fill_price

        self.cash += realized - fee
        self.mark_price(exchange, signal.symbol, fill_price)

        order = {
            "order_id": f"paper_{uuid4().hex[:12]}",
            "exchange": exchange,
            "strategy": strategy_name,
            "symbol": signal.symbol,
            "side": signal.action.value,
            "quantity": quantity,
            "price": fill_price,
            "fee": fee,
            "realized_pnl": realized,
            "status": "filled",
            "timestamp": datetime.utcnow().isoformat(),
            "signal_metadata": signal.metadata,
        }
        self.orders.append(order)
        self.orders = self.orders[-200:]
        return order

    def summary(self) -> Dict[str, Any]:
        """返回模拟账户汇总，供 API 和前端展示。"""

        active_positions = [
            position
            for position in self.positions.values()
            if abs(float(position.get("quantity", 0))) > 0
        ]
        unrealized = sum(float(position.get("unrealized_pnl", 0)) for position in active_positions)
        realized = sum(float(position.get("realized_pnl", 0)) for position in self.positions.values())
        equity = self.cash + unrealized
        return {
            "enabled": self.enabled,
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "equity": equity,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": equity - self.initial_cash,
            "fee_rate": self.fee_rate,
            "active_positions": len(active_positions),
            "positions": active_positions,
            "orders": self.orders[-20:],
        }
