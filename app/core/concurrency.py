"""
并发控制模块

提供速率限制、信号量等并发控制工具。
"""

import asyncio
import time
from typing import Optional
from collections import deque


class RateLimiter:
    """异步速率限制器
    
    使用令牌桶算法限制请求频率，防止触发交易所 API 限流。
    
    Example:
        limiter = RateLimiter(rate=10, period=1.0)  # 每秒 10 次
        async with limiter:
            await make_api_call()
    """
    
    def __init__(self, rate: int = 10, period: float = 1.0):
        """初始化速率限制器
        
        Args:
            rate: 允许的请求次数
            period: 时间窗口（秒）
        """
        self.rate = rate
        self.period = period
        self._timestamps: deque = deque(maxlen=rate)
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """获取许可，如果超过限制则等待"""
        async with self._lock:
            now = time.monotonic()
            
            # 清理过期的时间戳
            while self._timestamps and self._timestamps[0] <= now - self.period:
                self._timestamps.popleft()
            
            # 如果达到限制，计算需要等待的时间
            if len(self._timestamps) >= self.rate:
                wait_time = self._timestamps[0] + self.period - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    # 重新检查并清理
                    now = time.monotonic()
                    while self._timestamps and self._timestamps[0] <= now - self.period:
                        self._timestamps.popleft()
            
            # 记录当前请求时间
            self._timestamps.append(time.monotonic())
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class AsyncSemaphore:
    """异步信号量包装器
    
    用于控制并发任务数量，防止资源耗尽。
    
    Example:
        semaphore = AsyncSemaphore(max_concurrent=5)
        async with semaphore:
            await process_item()
    """
    
    def __init__(self, max_concurrent: int = 10):
        """初始化信号量
        
        Args:
            max_concurrent: 最大并发数
        """
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._current_count = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """获取信号量"""
        await self._semaphore.acquire()
        async with self._lock:
            self._current_count += 1
    
    async def release(self):
        """释放信号量"""
        async with self._lock:
            self._current_count -= 1
        self._semaphore.release()
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()
    
    @property
    def current_count(self) -> int:
        """当前正在执行的任务数"""
        return self._current_count
    
    @property
    def available(self) -> int:
        """可用的并发槽位数"""
        return self._max_concurrent - self._current_count
