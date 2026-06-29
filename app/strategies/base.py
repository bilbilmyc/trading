"""
策略基类

定义所有交易策略必须实现的接口。
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SignalAction(str, Enum):
    """信号动作"""
    BUY = 'buy'
    SELL = 'sell'
    HOLD = 'hold'


class Signal(BaseModel):
    """交易信号
    
    Attributes:
        symbol: 交易对
        action: 买卖动作
        strength: 信号强度 (0-1)
        quantity: 建议数量
        price: 目标价格
        order_type: 订单类型
        stop_loss: 止损价
        take_profit: 止盈价
        metadata: 额外信息
        timestamp: 信号时间
    """

    symbol: str = Field(..., min_length=1, description="交易对")
    action: SignalAction = Field(..., description="买卖动作")
    strength: float = Field(1.0, ge=0, le=1, description="信号强度")
    quantity: float | None = Field(None, gt=0, description="建议数量")
    price: float | None = Field(None, gt=0, description="目标价格")
    order_type: str = Field('market', description="订单类型")
    stop_loss: float | None = Field(None, gt=0, description="止损价")
    take_profit: float | None = Field(None, gt=0, description="止盈价")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外信息")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="信号时间")

    @property
    def is_actionable(self) -> bool:
        """信号是否可执行"""
        return self.action in [SignalAction.BUY, SignalAction.SELL] and self.strength > 0.5


class StrategyBase(ABC):
    """策略基类
    
    所有交易策略必须继承此类并实现抽象方法。
    """

    def __init__(self, name: str = 'BaseStrategy'):
        """初始化策略
        
        Args:
            name: 策略名称
        """
        self.name = name
        self._initialized_at = datetime.utcnow()
        self._last_signal_time: dict[str, datetime] = {}

    @property
    def initialized_at(self) -> datetime:
        """策略初始化时间"""
        return self._initialized_at

    @abstractmethod
    async def on_market_data(self, symbol: str, data: dict[str, Any]):
        """处理行情数据
        
        Args:
            symbol: 交易对
            data: 行情数据
        """
        pass

    @abstractmethod
    async def generate_signals(self, symbol: str) -> Signal | None:
        """生成交易信号
        
        Args:
            symbol: 交易对
            
        Returns:
            交易信号，无信号返回 None
        """
        pass

    async def on_order_filled(self, symbol: str, order_info: dict[str, Any]):
        """订单成交回调
        
        Args:
            symbol: 交易对
            order_info: 订单信息
        """
        pass

    async def on_position_update(self, symbol: str, position_info: dict[str, Any]):
        """持仓更新回调
        
        Args:
            symbol: 交易对
            position_info: 持仓信息
        """
        pass

    async def start(self):
        """启动策略"""
        pass

    async def stop(self):
        """停止策略"""
        pass

    def get_last_signal_time(self, symbol: str) -> datetime | None:
        """获取上次信号时间"""
        return self._last_signal_time.get(symbol)

    def _update_signal_time(self, symbol: str):
        """更新信号时间"""
        self._last_signal_time[symbol] = datetime.utcnow()

    def should_generate_signal(self, symbol: str, min_interval_seconds: int = 60) -> bool:
        """检查是否应该生成新信号 (防止频繁信号)
        
        Args:
            symbol: 交易对
            min_interval_seconds: 最小间隔秒数
            
        Returns:
            是否可以生成新信号
        """
        last_time = self.get_last_signal_time(symbol)
        if last_time is None:
            return True

        elapsed = (datetime.utcnow() - last_time).total_seconds()
        return elapsed >= min_interval_seconds
