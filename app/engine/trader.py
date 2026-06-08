"""
交易引擎核心

负责策略执行、订单路由、并发控制等核心功能。
支持多交易所、多策略并行运行。
"""

import asyncio
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from loguru import logger

from app.exchanges.base import ExchangeBase
from app.strategies.base import StrategyBase, Signal, SignalAction
from app.engine.risk_manager import RiskManager, RiskConfig
from app.engine.position_manager import PositionManager
from app.models.order import Order, OrderSide, OrderType, OrderStatus


class TradingEngine:
    """交易引擎
    
    核心功能：
    - 多交易所连接管理
    - 多策略并行执行
    - 订单执行与跟踪
    - 风险控制
    - 持仓管理
    - 高并发支持
    """
    
    def __init__(
        self,
        risk_config: Optional[RiskConfig] = None,
        max_concurrent_orders: int = 10
    ):
        self._exchanges: Dict[str, ExchangeBase] = {}
        self._strategies: Dict[str, StrategyBase] = {}
        self._running = False
        
        # 核心组件
        self.risk_manager = RiskManager(risk_config)
        self.position_manager = PositionManager()
        
        # 并发控制
        self._order_semaphore = asyncio.Semaphore(max_concurrent_orders)
        self._tasks: List[asyncio.Task] = []
        
        # 回调函数
        self._on_signal_callbacks: List[Callable] = []
        self._on_order_callbacks: List[Callable] = []
        
        logger.info("交易引擎初始化完成")
    
    def add_exchange(self, name: str, exchange: ExchangeBase):
        """添加交易所"""
        self._exchanges[name.lower()] = exchange
        logger.info(f"添加交易所：{name}")
    
    def add_strategy(self, name: str, strategy: StrategyBase):
        """添加策略"""
        self._strategies[name] = strategy
        logger.info(f"添加策略：{name}")
    
    def on_signal(self, callback: Callable):
        """注册信号回调"""
        self._on_signal_callbacks.append(callback)
    
    def on_order(self, callback: Callable):
        """注册订单回调"""
        self._on_order_callbacks.append(callback)
    
    async def start(self):
        """启动交易引擎"""
        if self._running:
            logger.warning("交易引擎已在运行中")
            return
        
        self._running = True
        logger.info("交易引擎启动")
        
        # 启动所有策略
        for name, strategy in self._strategies.items():
            await strategy.start()
            logger.info(f"策略 {name} 已启动")
    
    async def stop(self):
        """停止交易引擎"""
        if not self._running:
            return
        
        self._running = False
        logger.info("交易引擎停止中...")
        
        # 取消所有任务
        for task in self._tasks:
            task.cancel()
        
        # 等待任务完成
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # 停止所有策略
        for name, strategy in self._strategies.items():
            await strategy.stop()
        
        # 关闭所有交易所连接
        for name, exchange in self._exchanges.items():
            await exchange.close()
        
        logger.info("交易引擎已停止")
    
    async def process_market_data(
        self,
        exchange_name: str,
        symbol: str,
        data: Dict[str, Any]
    ):
        """处理行情数据
        
        将行情数据分发给所有策略
        """
        # 更新持仓价格
        price = float(data.get('last_price', data.get('close', 0)))
        if price > 0:
            await self.position_manager.update_price(exchange_name, symbol, price)
        
        # 通知所有策略
        tasks = []
        for name, strategy in self._strategies.items():
            tasks.append(strategy.on_market_data(symbol, data))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def check_and_execute_signals(
        self,
        exchange_name: str,
        symbol: str
    ) -> List[Signal]:
        """检查并执行交易信号"""
        if exchange_name not in self._exchanges:
            logger.error(f"交易所 {exchange_name} 未找到")
            return []
        
        exchange = self._exchanges[exchange_name]
        executed_signals = []
        
        # 为每个策略生成信号
        signal_tasks = []
        for name, strategy in self._strategies.items():
            signal_tasks.append(self._generate_signal(strategy, symbol))
        
        signals = await asyncio.gather(*signal_tasks, return_exceptions=True)
        
        # 执行有效信号
        for signal in signals:
            if isinstance(signal, Signal) and signal.is_actionable:
                # 通知回调
                for callback in self._on_signal_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(signal)
                        else:
                            callback(signal)
                    except Exception as e:
                        logger.error(f"信号回调错误：{e}")
                
                # 执行订单
                await self._execute_signal(exchange, signal)
                executed_signals.append(signal)
        
        return executed_signals
    
    async def _generate_signal(
        self,
        strategy: StrategyBase,
        symbol: str
    ) -> Optional[Signal]:
        """生成交易信号"""
        try:
            return await strategy.generate_signals(symbol)
        except Exception as e:
            logger.error(f"策略 {strategy.name} 生成信号失败：{e}")
            return None
    
    async def _execute_signal(self, exchange: ExchangeBase, signal: Signal):
        """执行交易信号"""
        async with self._order_semaphore:
            # 风控检查
            price = signal.price or 0
            if price <= 0:
                # 获取当前价格
                try:
                    ticker = await exchange.get_ticker(signal.symbol)
                    price = float(ticker.get('last_price', 0))
                except Exception as e:
                    logger.error(f"获取价格失败：{e}")
                    return
            
            quantity = signal.quantity or 0.001  # 默认数量
            
            allowed, reason = await self.risk_manager.check_order(
                signal.symbol,
                signal.action.value,
                quantity,
                price
            )
            
            if not allowed:
                logger.warning(f"订单被风控拦截：{reason}")
                return
            
            # 计算止损止盈
            stop_loss = signal.stop_loss or self.risk_manager.calculate_stop_loss(
                price, signal.action.value
            )
            take_profit = signal.take_profit or self.risk_manager.calculate_take_profit(
                price, signal.action.value
            )
            
            # 下单
            try:
                result = await exchange.place_order(
                    symbol=signal.symbol,
                    side=signal.action.value,
                    order_type=signal.order_type,
                    quantity=quantity,
                    price=signal.price,
                )
                
                logger.info(
                    f"订单执行成功："
                    f"{signal.action.value.upper()} {signal.symbol} "
                    f"qty={quantity} @ {price}"
                )
                
                # 更新持仓
                await self.position_manager.update_position(
                    exchange.name,
                    signal.symbol,
                    quantity,
                    price,
                    signal.action.value
                )
                
                # 通知订单回调
                for callback in self._on_order_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(result)
                        else:
                            callback(result)
                    except Exception as e:
                        logger.error(f"订单回调错误：{e}")
                
            except Exception as e:
                logger.error(f"订单执行失败：{e}")
    
    async def sync_positions(self, exchange_name: str):
        """同步交易所持仓"""
        if exchange_name not in self._exchanges:
            return
        
        exchange = self._exchanges[exchange_name]
        
        try:
            # 同步余额
            balances = await exchange.get_account_balance()
            for currency, amount in balances.items():
                await self.position_manager.update_balance(
                    exchange_name, currency, amount, amount
                )
            
            logger.info(f"{exchange_name} 持仓同步完成")
        except Exception as e:
            logger.error(f"{exchange_name} 持仓同步失败：{e}")
    
    async def get_status(self) -> Dict[str, Any]:
        """获取引擎状态"""
        risk_status = await self.risk_manager.get_risk_status()
        position_summary = await self.position_manager.get_position_summary()
        
        return {
            'running': self._running,
            'exchanges': list(self._exchanges.keys()),
            'strategies': list(self._strategies.keys()),
            'risk': risk_status,
            'positions': position_summary,
            'timestamp': datetime.utcnow().isoformat(),
        }
