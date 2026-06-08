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
from app.engine.paper_trading import PaperTradingAccount
from app.engine.order_sync import OrderSync
from app.engine.position_sync import PositionSync
from app.engine.monitor import Monitor, Alert, AlertLevel, AlertCategory, build_engine_checkers
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
        max_concurrent_orders: int = 10,
        order_sync_interval: int = 10,
        position_sync_interval: int = 15,
        monitor_check_interval: int = 30,
        monitor_max_alerts: int = 100,
    ):
        self._exchanges: Dict[str, ExchangeBase] = {}
        self._strategies: Dict[str, StrategyBase] = {}
        self._strategy_configs: Dict[str, Dict[str, Any]] = {}
        self._recent_signals: List[Dict[str, Any]] = []
        self._running = False
        
        # 核心组件
        self.risk_manager = RiskManager(risk_config)
        self.position_manager = PositionManager()
        self.paper_account = PaperTradingAccount()
        
        # 实盘同步组件（阶段 5）
        self.order_sync = OrderSync(interval_seconds=order_sync_interval)
        self.position_sync = PositionSync(
            position_manager=self.position_manager,
            interval_seconds=position_sync_interval,
        )
        self.monitor = Monitor(
            check_interval_seconds=monitor_check_interval,
            max_alerts=monitor_max_alerts,
        )
        
        # 并发控制
        self._order_semaphore = asyncio.Semaphore(max_concurrent_orders)
        self._tasks: List[asyncio.Task] = []
        self._sync_tasks: List[asyncio.Task] = []
        self._signal_runner_task: Optional[asyncio.Task] = None
        self._signal_runner_status: Dict[str, Any] = {
            "running": False,
            "poll_seconds": None,
            "last_cycle_at": None,
            "last_error": None,
            "cycles": 0,
            "signals_generated": 0,
        }
        
        # 回调函数
        self._on_signal_callbacks: List[Callable] = []
        self._on_order_callbacks: List[Callable] = []
        
        logger.info("交易引擎初始化完成（含 stage-5 实盘同步组件）")
    
    def add_exchange(self, name: str, exchange: ExchangeBase):
        """添加交易所"""
        self._exchanges[name.lower()] = exchange
        logger.info(f"添加交易所：{name}")
    
    def add_strategy(
        self,
        name: str,
        strategy: StrategyBase,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        interval: str = "1m",
        enabled: bool = False,
        mode: str = "signal",
    ):
        """添加策略"""
        self._strategies[name] = strategy
        self._strategy_configs[name] = {
            "exchange": exchange,
            "symbol": symbol,
            "interval": interval,
            "enabled": enabled,
            "mode": mode,
            "updated_at": datetime.utcnow().isoformat(),
        }
        logger.info(f"添加策略：{name}")

    def remove_strategy(self, name: str) -> bool:
        """Remove one strategy instance."""

        existed = name in self._strategies
        self._strategies.pop(name, None)
        self._strategy_configs.pop(name, None)
        return existed

    def set_strategy_enabled(self, name: str, enabled: bool) -> Dict[str, Any]:
        """Enable or disable one strategy instance."""

        if name not in self._strategies:
            raise KeyError(name)
        config = self._strategy_configs.setdefault(name, {})
        config["enabled"] = enabled
        config["updated_at"] = datetime.utcnow().isoformat()
        return config

    def set_strategy_mode(self, name: str, mode: str) -> Dict[str, Any]:
        """Set one strategy execution mode."""

        if name not in self._strategies:
            raise KeyError(name)
        if mode not in {"signal", "paper"}:
            raise ValueError("mode must be signal or paper")
        config = self._strategy_configs.setdefault(name, {})
        config["mode"] = mode
        config["updated_at"] = datetime.utcnow().isoformat()
        return config

    def get_signal_runner_status(self) -> Dict[str, Any]:
        """Return background signal runner status."""

        return {
            **self._signal_runner_status,
            "running": self._signal_runner_task is not None and not self._signal_runner_task.done(),
        }

    def get_paper_summary(self) -> Dict[str, Any]:
        """Return paper trading account summary."""

        return self.paper_account.summary()

    async def start_signal_runner(self, poll_seconds: int = 60, candle_limit: int = 80) -> Dict[str, Any]:
        """Start a background loop that generates strategy signals only."""

        if self._signal_runner_task is not None and not self._signal_runner_task.done():
            return self.get_signal_runner_status()

        self._signal_runner_status.update(
            {
                "running": True,
                "poll_seconds": poll_seconds,
                "last_error": None,
            }
        )
        self._signal_runner_task = asyncio.create_task(
            self._signal_runner_loop(poll_seconds=poll_seconds, candle_limit=candle_limit)
        )
        return self.get_signal_runner_status()

    async def stop_signal_runner(self) -> Dict[str, Any]:
        """Stop the background signal runner."""

        if self._signal_runner_task is not None:
            self._signal_runner_task.cancel()
            await asyncio.gather(self._signal_runner_task, return_exceptions=True)
            self._signal_runner_task = None
        self._signal_runner_status["running"] = False
        return self.get_signal_runner_status()

    def list_strategies(self) -> List[Dict[str, Any]]:
        """Return lightweight strategy metadata for dashboards."""

        strategies = []
        for name, strategy in self._strategies.items():
            config = self._strategy_configs.get(name, {})
            strategies.append(
                {
                    "name": name,
                    "class_name": strategy.__class__.__name__,
                    "initialized_at": strategy.initialized_at.isoformat(),
                    "running": bool(config.get("enabled", False)),
                    "exchange": config.get("exchange"),
                    "symbol": config.get("symbol"),
                    "interval": config.get("interval", "1m"),
                    "mode": config.get("mode", "signal"),
                    "updated_at": config.get("updated_at"),
                    "parameters": {
                        key: value
                        for key, value in vars(strategy).items()
                        if not key.startswith("_") and isinstance(value, (str, int, float, bool, type(None)))
                    },
                }
            )
        return strategies

    def get_recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the newest generated strategy signals."""

        return self._recent_signals[-limit:]

    def _record_signal(self, exchange_name: str, strategy_name: str, signal: Signal) -> None:
        """Store recent signals in memory for UI/audit visibility."""

        self._recent_signals.append(
            {
                "exchange": exchange_name,
                "strategy": strategy_name,
                "symbol": signal.symbol,
                "action": signal.action.value,
                "strength": signal.strength,
                "quantity": signal.quantity,
                "price": signal.price,
                "order_type": signal.order_type,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "metadata": signal.metadata,
                "actionable": signal.is_actionable,
                "timestamp": signal.timestamp.isoformat(),
            }
        )
        self._recent_signals = self._recent_signals[-200:]
    
    def on_signal(self, callback: Callable):
        """注册信号回调"""
        self._on_signal_callbacks.append(callback)
    
    def on_order(self, callback: Callable):
        """注册订单回调"""
        self._on_order_callbacks.append(callback)
    
    async def start(self):
        """启动交易引擎

        阶段 5 增强：同步三个实盘子系统的后台任务并启动监控。
        """

        if self._running:
            logger.warning("交易引擎已在运行中")
            return
        
        self._running = True
        logger.info("交易引擎启动")
        
        # ── 启动所有策略 ──
        for name, strategy in self._strategies.items():
            await strategy.start()
            logger.info(f"策略 {name} 已启动")
        
        # ── 阶段 5：启动订单同步 ──
        self.order_sync.start()
        self._sync_tasks.append(
            asyncio.create_task(self._order_sync_loop())
        )
        
        # ── 阶段 5：启动持仓同步 ──
        self.position_sync.start()
        self._sync_tasks.append(
            asyncio.create_task(self._position_sync_loop())
        )
        
        # ── 阶段 5：启动监控告警 ──
        # 注册标准检查器
        checkers = build_engine_checkers(self._exchanges, self)
        for checker in checkers:
            self.monitor.add_checker(checker)
        self.monitor.start()

        self.monitor.push(
            Alert(
                level=AlertLevel.INFO,
                category=AlertCategory.ENGINE,
                title="Engine started",
                message=f"Trading engine started with {len(self._exchanges)} exchange(s) and {len(self._strategies)} strategy(ies)",
                details={
                    "exchanges": list(self._exchanges.keys()),
                    "strategies": list(self._strategies.keys()),
                },
            )
        )
        logger.info("交易引擎 + 实盘子系统已启动")
    
    async def stop(self):
        """停止交易引擎"""
        if not self._running:
            return
        
        self._running = False
        logger.info("交易引擎停止中...")
        
        # 取消所有用户任务
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # 停止信号运行器
        await self.stop_signal_runner()
        
        # ── 阶段 5：停止实盘子系统 ──
        await self.order_sync.stop()
        await self.position_sync.stop()
        await self.monitor.stop()
        
        # 取消同步循环
        for task in self._sync_tasks:
            task.cancel()
        if self._sync_tasks:
            await asyncio.gather(*self._sync_tasks, return_exceptions=True)
        
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
            if self._strategy_matches(name, exchange_name, symbol, include_disabled=True):
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
        signal_tasks = [
            (name, self._generate_signal(strategy, symbol))
            for name, strategy in self._strategies.items()
            if self._strategy_matches(name, exchange_name, symbol)
        ]

        signals = await asyncio.gather(*(task for _, task in signal_tasks), return_exceptions=True)

        # 执行有效信号
        for (strategy_name, _), signal in zip(signal_tasks, signals):
            if isinstance(signal, Signal) and signal.is_actionable:
                self._record_signal(exchange_name, strategy_name, signal)
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

    async def evaluate_signals(
        self,
        exchange_name: str,
        symbol: str,
        record: bool = True,
    ) -> List[Dict[str, Any]]:
        """Generate strategy signals without sending orders to an exchange."""

        generated: List[Dict[str, Any]] = []
        signal_tasks = [
            (name, self._generate_signal(strategy, symbol))
            for name, strategy in self._strategies.items()
            if self._strategy_matches(name, exchange_name, symbol, include_disabled=True)
        ]
        if not signal_tasks:
            return generated

        signals = await asyncio.gather(*(task for _, task in signal_tasks), return_exceptions=True)
        for (strategy_name, _), signal in zip(signal_tasks, signals):
            if isinstance(signal, Signal):
                if record:
                    self._record_signal(exchange_name, strategy_name, signal)
                generated.append(
                    {
                        "exchange": exchange_name,
                        "strategy": strategy_name,
                        "symbol": signal.symbol,
                        "action": signal.action.value,
                        "strength": signal.strength,
                        "quantity": signal.quantity,
                        "price": signal.price,
                        "order_type": signal.order_type,
                        "stop_loss": signal.stop_loss,
                        "take_profit": signal.take_profit,
                        "metadata": signal.metadata,
                        "actionable": signal.is_actionable,
                        "timestamp": signal.timestamp.isoformat(),
                    }
                )
        return generated

    async def run_signal_cycle(self, candle_limit: int = 80) -> Dict[str, Any]:
        """Run one signal-only cycle for all enabled configured strategies."""

        cycle_started = datetime.utcnow()
        processed = 0
        generated: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []

        for strategy_name, strategy in list(self._strategies.items()):
            config = self._strategy_configs.get(strategy_name, {})
            if not config.get("enabled", False):
                continue

            exchange_name = str(config.get("exchange") or "").lower()
            symbol = str(config.get("symbol") or "")
            interval = str(config.get("interval") or "1m")
            exchange = self._exchanges.get(exchange_name)
            if exchange is None or not symbol:
                errors.append(
                    {
                        "strategy": strategy_name,
                        "error": f"Missing exchange or symbol: {exchange_name}/{symbol}",
                    }
                )
                continue

            try:
                klines = await exchange.get_klines(symbol, interval=interval, limit=candle_limit)
                for candle in sorted(klines, key=lambda item: item.get("open_time", "")):
                    await self._process_market_data_for_strategy(strategy, exchange_name, symbol, candle)
                signal = await self._generate_signal(strategy, symbol)
                processed += 1
                if isinstance(signal, Signal):
                    self._record_signal(exchange_name, strategy_name, signal)
                    serialized = self._serialize_signal(exchange_name, strategy_name, signal)
                    paper_order = await self._maybe_apply_paper_signal(
                        exchange,
                        exchange_name,
                        strategy_name,
                        signal,
                    )
                    if paper_order:
                        serialized["paper_order"] = paper_order
                    generated.append(serialized)
            except Exception as exc:
                errors.append({"strategy": strategy_name, "error": str(exc)})

        self._signal_runner_status.update(
            {
                "last_cycle_at": cycle_started.isoformat(),
                "last_error": errors[-1]["error"] if errors else None,
                "cycles": int(self._signal_runner_status.get("cycles") or 0) + 1,
                "signals_generated": int(self._signal_runner_status.get("signals_generated") or 0)
                + len(generated),
            }
        )
        return {
            "processed_strategies": processed,
            "signals": generated,
            "errors": errors,
            "status": self.get_signal_runner_status(),
        }

    async def _signal_runner_loop(self, poll_seconds: int, candle_limit: int) -> None:
        """Background signal-only strategy loop."""

        try:
            while True:
                await self.run_signal_cycle(candle_limit=candle_limit)
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._signal_runner_status["last_error"] = str(exc)
            logger.exception("Signal runner stopped unexpectedly")
        finally:
            self._signal_runner_status["running"] = False

    # ── 阶段 5：实盘同步循环 ──────────────────────────────────

    async def _order_sync_loop(self) -> None:
        """Background loop pulling open orders from all exchanges."""

        while self._running:
            for name, exchange in list(self._exchanges.items()):
                try:
                    changed = await self.order_sync.sync(exchange)
                    if changed > 0:
                        self.monitor.push(
                            Alert(
                                level=AlertLevel.INFO,
                                category=AlertCategory.ORDER,
                                title="Orders synced",
                                message=f"{changed} order(s) changed on {name}",
                                exchange=name,
                            )
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.monitor.push(
                        Alert(
                            level=AlertLevel.WARNING,
                            category=AlertCategory.ORDER,
                            title="Order sync error",
                            message=f"Failed to sync orders on {name}: {exc}",
                            exchange=name,
                        )
                    )
            await asyncio.sleep(self.order_sync.interval_seconds)

    async def _position_sync_loop(self) -> None:
        """Background loop pulling positions from all exchanges."""

        while self._running:
            for name, exchange in list(self._exchanges.items()):
                try:
                    changed = await self.position_sync.sync(exchange, name)
                    if changed > 0:
                        logger.debug(f"PositionSync [{name}]: {changed} item(s) updated")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.monitor.push(
                        Alert(
                            level=AlertLevel.WARNING,
                            category=AlertCategory.POSITION,
                            title="Position sync error",
                            message=f"Failed to sync positions on {name}: {exc}",
                            exchange=name,
                        )
                    )
            await asyncio.sleep(self.position_sync.interval_seconds)

    async def _process_market_data_for_strategy(
        self,
        strategy: StrategyBase,
        exchange_name: str,
        symbol: str,
        data: Dict[str, Any],
    ) -> None:
        """Feed one market data point to one strategy instance."""

        price = float(data.get("last_price", data.get("close", 0)))
        if price > 0:
            await self.position_manager.update_price(exchange_name, symbol, price)
        await strategy.on_market_data(symbol, data)

    def _serialize_signal(self, exchange_name: str, strategy_name: str, signal: Signal) -> Dict[str, Any]:
        """Serialize a Signal for API/UI responses."""

        return {
            "exchange": exchange_name,
            "strategy": strategy_name,
            "symbol": signal.symbol,
            "action": signal.action.value,
            "strength": signal.strength,
            "quantity": signal.quantity,
            "price": signal.price,
            "order_type": signal.order_type,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "metadata": signal.metadata,
            "actionable": signal.is_actionable,
            "timestamp": signal.timestamp.isoformat(),
        }

    async def _maybe_apply_paper_signal(
        self,
        exchange: ExchangeBase,
        exchange_name: str,
        strategy_name: str,
        signal: Signal,
    ) -> Optional[Dict[str, Any]]:
        """Apply actionable signals to the paper account when strategy mode is paper."""

        config = self._strategy_configs.get(strategy_name, {})
        if config.get("mode") != "paper" or not signal.is_actionable:
            return None

        price = signal.price or 0
        if price <= 0:
            ticker = await exchange.get_ticker(signal.symbol)
            price = float(ticker.get("last_price", 0))
        return self.paper_account.apply_signal(exchange_name, strategy_name, signal, price)

    def _strategy_matches(
        self,
        strategy_name: str,
        exchange_name: str,
        symbol: str,
        include_disabled: bool = False,
    ) -> bool:
        """Check whether a strategy instance is bound to an exchange/symbol."""

        config = self._strategy_configs.get(strategy_name, {})
        if not include_disabled and not config.get("enabled", False):
            return False
        configured_exchange = config.get("exchange")
        configured_symbol = config.get("symbol")
        if configured_exchange and configured_exchange.lower() != exchange_name.lower():
            return False
        if configured_symbol and configured_symbol.upper() != symbol.upper():
            return False
        return True
    
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
            # ── 获取价格 ──
            price = signal.price or 0
            if price <= 0:
                try:
                    ticker = await exchange.get_ticker(signal.symbol)
                    price = float(ticker.get('last_price', 0))
                except Exception as e:
                    logger.error(f"获取价格失败：{e}")
                    self.monitor.push(
                        Alert(
                            level=AlertLevel.ERROR,
                            category=AlertCategory.ORDER,
                            title="Price fetch failed",
                            message=f"Cannot get price for {signal.symbol}: {e}",
                            exchange=exchange.name,
                            symbol=signal.symbol,
                        )
                    )
                    return

            quantity = signal.quantity or 0.001

            # ── 风控检查 ──
            allowed, reason = await self.risk_manager.check_order(
                signal.symbol,
                signal.action.value,
                quantity,
                price,
            )

            if not allowed:
                logger.warning(f"订单被风控拦截：{reason}")
                self.monitor.push(
                    Alert(
                        level=AlertLevel.WARNING,
                        category=AlertCategory.RISK,
                        title="Order rejected by risk",
                        message=reason,
                        exchange=exchange.name,
                        symbol=signal.symbol,
                        details={"action": signal.action.value, "quantity": quantity, "price": price},
                    )
                )
                return

            # ── 计算止损止盈 ──
            stop_loss = signal.stop_loss or self.risk_manager.calculate_stop_loss(
                price, signal.action.value
            )
            take_profit = signal.take_profit or self.risk_manager.calculate_take_profit(
                price, signal.action.value
            )

            # ── 下单 ──
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

                # 阶段 5：注册到订单同步器
                order = Order(
                    symbol=signal.symbol,
                    exchange=exchange.name,
                    side=OrderSide.BUY if signal.action.value == "buy" else OrderSide.SELL,
                    order_type=OrderType.MARKET if signal.order_type == "market" else OrderType.LIMIT,
                    quantity=quantity,
                    price=signal.price,
                    order_id=str(result.get("order_id", "")),
                )
                self.order_sync.track(order)

                # 更新持仓
                await self.position_manager.update_position(
                    exchange.name,
                    signal.symbol,
                    quantity,
                    price,
                    signal.action.value,
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

                # 监控告警：订单已提交
                self.monitor.push(
                    Alert(
                        level=AlertLevel.INFO,
                        category=AlertCategory.ORDER,
                        title="Order placed",
                        message=f"{signal.action.value.upper()} {quantity} {signal.symbol} @ {price}",
                        exchange=exchange.name,
                        symbol=signal.symbol,
                        details={
                            "order_id": order.order_id,
                            "action": signal.action.value,
                            "quantity": quantity,
                            "price": price,
                        },
                    )
                )

            except Exception as e:
                logger.error(f"订单执行失败：{e}")
                self.monitor.push(
                    Alert(
                        level=AlertLevel.ERROR,
                        category=AlertCategory.ORDER,
                        title="Order execution failed",
                        message=f"{signal.action.value.upper()} {signal.symbol}: {e}",
                        exchange=exchange.name,
                        symbol=signal.symbol,
                    )
                )
    
    async def sync_positions(self, exchange_name: str):
        """同步交易所持仓 (单次调用版本，建议使用 PositionSync)"""
        if exchange_name not in self._exchanges:
            return
        
        exchange = self._exchanges[exchange_name]
        
        try:
            changed = await self.position_sync.sync(exchange, exchange_name)
            logger.info(f"{exchange_name} 持仓同步完成 ({changed} 项更新)")
        except Exception as e:
            logger.error(f"{exchange_name} 持仓同步失败：{e}")
            self.monitor.push(
                Alert(
                    level=AlertLevel.ERROR,
                    category=AlertCategory.POSITION,
                    title="Position sync failed",
                    message=f"{exchange_name}: {e}",
                    exchange=exchange_name,
                )
            )
    
    async def get_status(self) -> Dict[str, Any]:
        """获取引擎状态"""
        risk_status = await self.risk_manager.get_risk_status()
        position_summary = await self.position_manager.get_position_summary()
        
        return {
            'running': self._running,
            'exchanges': list(self._exchanges.keys()),
            'strategies': list(self._strategies.keys()),
            'strategy_details': self.list_strategies(),
            'recent_signals': self.get_recent_signals(limit=10),
            'signal_runner': self.get_signal_runner_status(),
            'paper': self.get_paper_summary(),
            'risk': risk_status,
            'positions': position_summary,
            # 阶段 5：实盘同步 + 监控状态
            'order_sync': {
                'running': self.order_sync._running,
                'tracked_orders': self.order_sync.tracked_count,
            },
            'position_sync': {
                'running': self.position_sync.is_running,
            },
            'monitor': self.monitor.summary(),
            'timestamp': datetime.utcnow().isoformat(),
        }
