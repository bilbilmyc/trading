"""
SMA 双均线策略

简单移动平均线交叉策略：
- 当短期均线上穿长期均线时生成买入信号
- 当短期均线下穿长期均线时生成卖出信号
"""

from collections import deque
from typing import Any

import numpy as np

from app.strategies.base import Signal, SignalAction, StrategyBase


class SMAStrategy(StrategyBase):
    """SMA 双均线交叉策略
    
    Attributes:
        short_window: 短期均线周期
        long_window: 长期均线周期
        min_data_points: 最小数据点数
    """

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        min_data_points: int = 20,
        max_data_points: int = 200,
        name: str | None = None,
    ):
        if name is None:
            name = f"SMA_{short_window}_{long_window}"
        super().__init__(name=name)

        if short_window >= long_window:
            raise ValueError("短期均线周期必须小于长期均线周期")

        self.short_window = short_window
        self.long_window = long_window
        self.min_data_points = min_data_points

        # 存储价格历史 (使用 deque 提高性能)
        self._price_history: dict[str, deque[float]] = {}
        # 存储上一周期的均线值用于检测交叉
        self._prev_sma: dict[str, dict[str, float | None]] = {}

    async def on_market_data(self, symbol: str, data: dict[str, Any]):
        """处理行情数据"""
        price = float(data.get('last_price', data.get('close', 0)))

        if price <= 0:
            return

        # 初始化价格历史
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=self.long_window * 2)
            self._prev_sma[symbol] = {'short': None, 'long': None}

        # 添加新价格
        self._price_history[symbol].append(price)

    def _calculate_sma(self, prices: deque[float], window: int) -> float | None:
        """计算简单移动平均线
        
        使用 numpy 提高计算性能
        """
        if len(prices) < window:
            return None
        return float(np.mean(list(prices)[-window:]))

    def _detect_crossover(
        self,
        current_short: float,
        current_long: float,
        prev_short: float | None,
        prev_long: float | None
    ) -> SignalAction | None:
        """检测均线交叉
        
        Returns:
            SignalAction.BUY: 金叉 (短线上穿长线)
            SignalAction.SELL: 死叉 (短线下穿长线)
            None: 无交叉
        """
        if prev_short is None or prev_long is None:
            return None

        # 金叉：之前短线 <= 长线，现在短线 > 长线
        if prev_short <= prev_long and current_short > current_long:
            return SignalAction.BUY

        # 死叉：之前短线 >= 长线，现在短线 < 长线
        if prev_short >= prev_long and current_short < current_long:
            return SignalAction.SELL

        return None

    async def generate_signals(self, symbol: str) -> Signal | None:
        """生成交易信号"""
        if symbol not in self._price_history:
            return None

        prices = self._price_history[symbol]

        # 检查数据是否足够
        if len(prices) < self.min_data_points:
            return None

        # 计算当前均线
        current_short = self._calculate_sma(prices, self.short_window)
        current_long = self._calculate_sma(prices, self.long_window)

        if current_short is None or current_long is None:
            return None

        # 获取上一周期的均线值
        prev_short = self._prev_sma[symbol]['short']
        prev_long = self._prev_sma[symbol]['long']

        # 检测交叉
        action = self._detect_crossover(
            current_short, current_long,
            prev_short, prev_long
        )

        # 更新上一周期的均线值
        self._prev_sma[symbol]['short'] = current_short
        self._prev_sma[symbol]['long'] = current_long

        if action is None:
            return None

        # 检查信号间隔
        if not self.should_generate_signal(symbol, min_interval_seconds=60):
            return None

        # 创建信号
        signal = Signal(
            symbol=symbol,
            action=action,
            strength=1.0,
            order_type='market',
            metadata={
                'short_sma': current_short,
                'long_sma': current_long,
                'crossover_type': 'golden' if action == SignalAction.BUY else 'death',
            }
        )

        self._update_signal_time(symbol)
        return signal

    async def stop(self):
        """停止策略，清理资源"""
        self._price_history.clear()
        self._prev_sma.clear()

    def get_current_sma(self, symbol: str) -> dict[str, float | None]:
        """获取当前均线值"""
        if symbol not in self._price_history:
            return {'short': None, 'long': None}

        prices = self._price_history[symbol]
        return {
            'short': self._calculate_sma(prices, self.short_window),
            'long': self._calculate_sma(prices, self.long_window),
        }

    def get_price_history_length(self, symbol: str) -> int:
        """获取价格历史长度"""
        if symbol not in self._price_history:
            return 0
        return len(self._price_history[symbol])
