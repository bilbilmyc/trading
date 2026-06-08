"""
策略模块

提供策略基类和示例策略实现。
"""

from app.strategies.base import StrategyBase, Signal, SignalAction
from app.strategies.sma import SMAStrategy

__all__ = [
    'StrategyBase',
    'Signal',
    'SignalAction',
    'SMAStrategy',
]
