"""
风险管理模块

负责仓位控制、止损止盈、最大回撤等风险管理功能。
"""

from typing import Dict, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field
import asyncio

from app.engine.live_trading_guard import LiveTradingGuard
from app.engine.pipeline_types import RiskDecision
from app.strategies.base import Signal


class RiskConfig(BaseModel):
    """风险配置"""
    
    max_position_size: float = Field(1.0, gt=0, description="最大持仓数量")
    max_position_value: float = Field(100000, gt=0, description="最大持仓金额")
    stop_loss_pct: float = Field(0.05, gt=0, le=1, description="止损百分比")
    take_profit_pct: float = Field(0.10, gt=0, description="止盈百分比")
    max_daily_loss: float = Field(1000, gt=0, description="每日最大亏损")
    max_drawdown_pct: float = Field(0.20, gt=0, le=1, description="最大回撤百分比")
    max_orders_per_minute: int = Field(10, gt=0, description="每分钟最大订单数")


class RiskManager:
    """风险管理器
    
    负责：
    - 仓位大小控制
    - 止损止盈计算
    - 交易频率限制
    - 每日亏损限制
    - 最大回撤监控
    """
    
    def __init__(
        self,
        config: Optional[RiskConfig] = None,
        trading_guard: Optional[LiveTradingGuard] = None,
    ):
        self.config = config or RiskConfig()
        self._daily_pnl = 0.0
        self._peak_value = 0.0
        self._current_value = 0.0
        self._order_timestamps: list = []
        self._trading_enabled = True
        self._guard = trading_guard
        self._lock = asyncio.Lock()
    
    @property
    def is_trading_enabled(self) -> bool:
        """Kill switch state — True iff kill switch is NOT engaged.

        Live-trading-enabled is a separate concern owned by TradingGuard.
        Use TradingGuard.is_open() to ask the full question.
        """
        if self._guard is not None:
            return not self._guard.kill_switch_enabled
        return self._trading_enabled
    
    @property
    def daily_pnl(self) -> float:
        """当日盈亏"""
        return self._daily_pnl
    
    @property
    def current_drawdown(self) -> float:
        """当前回撤百分比"""
        if self._peak_value == 0:
            return 0.0
        return (self._peak_value - self._current_value) / self._peak_value
    
    async def check_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float
    ) -> tuple[bool, str]:
        """检查订单是否符合风控要求

        Returns:
            (是否允许，原因)
        """
        async with self._lock:
            if not self._trading_enabled:
                return False, "交易已禁用"

            # 检查交易频率
            if not self._check_rate_limit():
                return False, "超出交易频率限制"

            # 检查订单价值
            order_value = quantity * price
            if order_value > self.config.max_position_value:
                return False, f"订单价值 {order_value} 超过限制 {self.config.max_position_value}"

            # 检查每日亏损
            if self._daily_pnl < -self.config.max_daily_loss:
                return False, "触及每日最大亏损限制"

            # 检查回撤
            if self.current_drawdown > self.config.max_drawdown_pct:
                return False, "触及最大回撤限制"

            return True, "通过风控检查"

    async def check(self, signal: Signal, price: float) -> RiskDecision:
        """RiskGate port surface — returns a typed RiskDecision.

        Used by LiveOrderPipeline. Same checks as check_order() but in the
        shape the pipeline expects, plus advisory stop_loss / take_profit.
        """
        quantity = signal.quantity or 0.001
        allowed, reason = await self.check_order(
            symbol=signal.symbol,
            side=signal.action.value,
            quantity=quantity,
            price=price,
        )
        if not allowed:
            return RiskDecision(allowed=False, reason=reason)

        sl = self.calculate_stop_loss(price, signal.action.value)
        tp = self.calculate_take_profit(price, signal.action.value)
        return RiskDecision(allowed=True, reason=reason, stop_loss=sl, take_profit=tp)
    
    def _check_rate_limit(self) -> bool:
        """检查交易频率限制"""
        now = datetime.utcnow()
        
        # 清理 60 秒前的记录
        self._order_timestamps = [
            ts for ts in self._order_timestamps
            if (now - ts).total_seconds() < 60
        ]
        
        if len(self._order_timestamps) >= self.config.max_orders_per_minute:
            return False
        
        self._order_timestamps.append(now)
        return True
    
    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """计算止损价"""
        if side.lower() == 'buy':
            return entry_price * (1 - self.config.stop_loss_pct)
        else:
            return entry_price * (1 + self.config.stop_loss_pct)
    
    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """计算止盈价"""
        if side.lower() == 'buy':
            return entry_price * (1 + self.config.take_profit_pct)
        else:
            return entry_price * (1 - self.config.take_profit_pct)
    
    def update_portfolio_value(self, value: float):
        """更新组合价值用于回撤计算"""
        self._current_value = value
        if value > self._peak_value:
            self._peak_value = value
    
    def update_daily_pnl(self, pnl: float):
        """更新当日盈亏"""
        self._daily_pnl += pnl
    
    def reset_daily_pnl(self):
        """重置每日盈亏 (每日调用)"""
        self._daily_pnl = 0.0
    
    def enable_trading(self):
        """启用交易"""
        if self._guard is not None:
            self._guard.enable_trading()
            return
        self._trading_enabled = True

    def disable_trading(self):
        """禁用交易"""
        if self._guard is not None:
            self._guard.disable_trading()
            return
        self._trading_enabled = False
    
    async def get_risk_status(self) -> Dict[str, Any]:
        """获取风险状态"""
        return {
            'trading_enabled': self.is_trading_enabled,
            'daily_pnl': self._daily_pnl,
            'current_drawdown': self.current_drawdown,
            'orders_last_minute': len(self._order_timestamps),
            'max_orders_per_minute': self.config.max_orders_per_minute,
        }
