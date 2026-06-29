"""
交易引擎核心

负责策略执行、订单路由、并发控制等核心功能。
支持多交易所、多策略并行运行。
"""

import asyncio
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from loguru import logger

from app.core.sqlite_store import SQLiteStore
from app.exchanges.base import ExchangeBase
from app.strategies.base import StrategyBase, Signal, SignalAction
from app.engine.risk_manager import RiskManager, RiskConfig
from app.engine.position_manager import PositionManager
from app.engine.paper_trading import PaperTradingAccount
from app.engine.order_sync import OrderSync
from app.engine.position_sync import PositionSync
from app.engine.monitor import Monitor, Alert, AlertLevel, AlertCategory, build_engine_checkers
from app.engine.live_order_pipeline import LiveOrderPipeline
from app.engine.order_tracker import OrderTrackerAdapter
from app.engine.position_recorder import PositionRecorderAdapter
from app.engine.composite_observer import CompositeObserver
from app.engine.live_trading_guard import LiveTradingGuard
from app.engine.strategy_registry import StrategyRegistry
from app.models.order import Order, OrderSide, OrderType, OrderStatus


class _NoOpGuard:
    """Fallback TradingGuard when no guard was injected (legacy callers)."""

    async def is_open(self) -> bool:
        return True

    @property
    def kill_switch_enabled(self) -> bool:
        return False


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
        store: Optional[SQLiteStore] = None,
        trading_guard: Optional["LiveTradingGuard"] = None,
        llm_allowed_symbols: Optional[List[str]] = None,
    ):
        self._exchanges: Dict[str, ExchangeBase] = {}
        self._pipelines: Dict[str, LiveOrderPipeline] = {}
        self._strategies: Dict[str, StrategyBase] = {}
        self._strategy_configs: Dict[str, Dict[str, Any]] = {}
        self._recent_signals: List[Dict[str, Any]] = []
        self._running = False
        self.store = store
        self.trading_guard = trading_guard
        # Snapshot of the symbol whitelist at engine-construction time.
        # Restored LLM strategies get this passed in so they remain gated
        # after a process restart.
        self._llm_allowed_symbols: Optional[List[str]] = (
            list(llm_allowed_symbols) if llm_allowed_symbols else None
        )

        # 核心组件
        self.risk_manager = RiskManager(risk_config, trading_guard=trading_guard)
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
        
        # 信号过滤器（B 方案：LLM 二次确认）
        # 过滤器签名：async (exchange_name, strategy_name, signal) -> bool
        self._signal_filters: List[Callable] = []
        self._signal_filter_rejects: List[Dict[str, Any]] = []
        
        logger.info("交易引擎初始化完成（含 stage-5 实盘同步组件）")

        if self.store:
            self._recent_signals = self.store.recent_signals(limit=200)
            self.paper_account.load_state(**self.store.load_paper_state())

        # ── Phase D: LiveOrderPipeline (deep module + 6 ports) ──
        self._order_tracker = OrderTrackerAdapter(self.order_sync)
        self._position_recorder = PositionRecorderAdapter(self.position_manager)
        self._observer = CompositeObserver(self.monitor, self.store)
        self._pipeline_semaphore = asyncio.Semaphore(max_concurrent_orders)
        # Pipeline is per-exchange (created on demand in add_exchange)

        # ── Phase G: StrategyRegistry — round-trip persistence ──
        self.strategy_registry = StrategyRegistry()
        self._register_default_strategies()

    def _register_default_strategies(self) -> None:
        """Register built-in strategy snapshot/restore pairs."""
        from app.strategies.sma import SMAStrategy

        def _sma_snap(s: SMAStrategy) -> dict:
            return {
                "short_window": s.short_window,
                "long_window": s.long_window,
            }

        def _sma_restore(data: dict) -> SMAStrategy:
            return SMAStrategy(
                short_window=int(data.get("short_window", 5)),
                long_window=int(data.get("long_window", 20)),
            )

        self.strategy_registry.register(
            cls=SMAStrategy, snapshot=_sma_snap, restore=_sma_restore
        )

        # LLM strategy: round-trip non-primitive config (model, analyzer, prompt).
        try:
            from app.strategies.llm_strategy import LLMStrategy

            def _llm_snap(s: LLMStrategy) -> dict:
                state: dict = {
                    "symbol": s.symbol,
                    "interval": s.interval,
                }
                cfg = getattr(s, "_config", None)
                if cfg is not None:
                    state["llm"] = {
                        "model": getattr(cfg, "model", ""),
                        "base_url": getattr(cfg, "base_url", ""),
                        "temperature": getattr(cfg, "temperature", 0.0),
                        "max_tokens": getattr(cfg, "max_tokens", 0),
                        "system_prompt": getattr(cfg, "system_prompt", ""),
                        "decision_prompt": getattr(cfg, "decision_prompt", ""),
                    }
                return state

            def _llm_restore(data: dict) -> LLMStrategy:
                strategy = LLMStrategy(
                    symbol=data.get("symbol"),
                    interval=data.get("interval", "1m"),
                )
                llm = data.get("llm") or {}
                if llm:
                    from app.strategies.llm_strategy import LLMConfig

                    cfg = LLMConfig(
                        model=llm.get("model", ""),
                        base_url=llm.get("base_url", "") or None,
                        temperature=float(llm.get("temperature", 0.0) or 0.0),
                        max_tokens=int(llm.get("max_tokens", 0) or 0),
                        system_prompt=llm.get("system_prompt", ""),
                        decision_prompt=llm.get("decision_prompt", ""),
                    )
                    strategy._config = cfg
                # Re-apply the configured symbol whitelist so restored
                # strategies respect the same gate as freshly-created ones.
                if self._llm_allowed_symbols is not None:
                    strategy.allowed_symbols = set(self._llm_allowed_symbols)
                return strategy

            self.strategy_registry.register(
                cls=LLMStrategy, snapshot=_llm_snap, restore=_llm_restore
            )
        except ImportError:
            logger.info("LLMStrategy not importable — skipping registration")
    
    def add_exchange(self, name: str, exchange: ExchangeBase):
        """添加交易所"""
        self._exchanges[name.lower()] = exchange
        # Build per-exchange LiveOrderPipeline (deep module + 6 ports).
        self._pipelines[name.lower()] = LiveOrderPipeline(
            exchange=exchange,
            trading_guard=self.trading_guard or _NoOpGuard(),
            risk_gate=self.risk_manager,
            order_tracker=self._order_tracker,
            position_recorder=self._position_recorder,
            observer=self._observer,
            semaphore=self._pipeline_semaphore,
            signal_filters=tuple(self._signal_filters),
        )
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
        self._persist_strategy(name)
        logger.info(f"添加策略：{name}")

    def remove_strategy(self, name: str) -> bool:
        """移除一个策略实例。"""

        existed = name in self._strategies
        self._strategies.pop(name, None)
        self._strategy_configs.pop(name, None)
        if existed and self.store:
            self.store.delete_strategy(name)
        return existed

    def set_strategy_enabled(self, name: str, enabled: bool) -> Dict[str, Any]:
        """启用或停用一个策略实例。"""

        if name not in self._strategies:
            raise KeyError(name)
        config = self._strategy_configs.setdefault(name, {})
        config["enabled"] = enabled
        config["updated_at"] = datetime.utcnow().isoformat()
        self._persist_strategy(name)
        return config

    def set_strategy_mode(self, name: str, mode: str) -> Dict[str, Any]:
        """设置单个策略的执行模式。"""

        if name not in self._strategies:
            raise KeyError(name)
        if mode not in {"signal", "paper"}:
            raise ValueError("mode must be signal or paper")
        config = self._strategy_configs.setdefault(name, {})
        config["mode"] = mode
        config["updated_at"] = datetime.utcnow().isoformat()
        self._persist_strategy(name)
        return config

    def get_signal_runner_status(self) -> Dict[str, Any]:
        """返回后台信号运行器状态。"""

        return {
            **self._signal_runner_status,
            "running": self._signal_runner_task is not None and not self._signal_runner_task.done(),
        }

    def get_paper_summary(self) -> Dict[str, Any]:
        """返回模拟盘账户汇总。"""

        return self.paper_account.summary()

    def reset_paper_account(self, initial_cash: Optional[float] = None) -> Dict[str, Any]:
        """重置模拟盘账户并持久化。"""

        self.paper_account.reset(initial_cash=initial_cash)
        summary = self.paper_account.summary()
        if self.store:
            self.store.save_paper_state(summary)
            self.store.clear_paper_orders()
        return summary

    async def start_signal_runner(self, poll_seconds: int = 60, candle_limit: int = 80) -> Dict[str, Any]:
        """启动只生成信号、不真实下单的后台循环。"""

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
        """停止后台信号运行器。"""

        if self._signal_runner_task is not None:
            self._signal_runner_task.cancel()
            await asyncio.gather(self._signal_runner_task, return_exceptions=True)
            self._signal_runner_task = None
        self._signal_runner_status["running"] = False
        return self.get_signal_runner_status()

    def list_strategies(self) -> List[Dict[str, Any]]:
        """返回前端仪表盘需要的轻量策略信息。"""

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

    def _strategy_snapshot(self, name: str) -> Optional[Dict[str, Any]]:
        """把一个策略转换成 API/SQLite 共用的元数据结构。"""

        strategy = self._strategies.get(name)
        if strategy is None:
            return None
        config = self._strategy_configs.get(name, {})
        return {
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

    def _persist_strategy(self, name: str) -> None:
        """如果配置了 SQLite，就持久化一个策略。"""

        if not self.store:
            return
        snapshot = self._strategy_snapshot(name)
        if snapshot:
            self.store.upsert_strategy(snapshot)

    def restore_persisted_strategies(self) -> int:
        """从 SQLite 恢复已注册的策略定义。

        通过 StrategyRegistry 调度：每个策略类自带 snapshot/restore，
        round-trip 任意可序列化的字段（不再过滤到 primitives）。
        未注册的 class_name 静默跳过（forward-compat）。
        """

        if not self.store:
            return 0

        restored = 0
        for item in self.store.list_strategies():
            snapshot = {
                "class_name": item.get("class_name"),
                "state": item.get("parameters") or {},
            }
            strategy = self.strategy_registry.restore(snapshot)
            if strategy is None:
                continue
            try:
                strategy._initialized_at = datetime.fromisoformat(str(item["initialized_at"]))
            except (KeyError, ValueError):
                pass
            self.add_strategy(
                str(item["name"]),
                strategy,
                exchange=item.get("exchange"),
                symbol=item.get("symbol"),
                interval=str(item.get("interval") or "1m"),
                enabled=bool(item.get("enabled")),
                mode=str(item.get("mode") or "signal"),
            )
            self._strategy_configs[str(item["name"])]["updated_at"] = item.get("updated_at")
            self._persist_strategy(str(item["name"]))
            restored += 1
        return restored

    def get_recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """返回最近生成的策略信号。"""

        return self._recent_signals[-limit:]

    def _record_signal(self, exchange_name: str, strategy_name: str, signal: Signal) -> None:
        """把最新信号写入内存和 SQLite，供 UI/审计查看。"""

        row = self._serialize_signal(exchange_name, strategy_name, signal)
        self._recent_signals.append(row)
        self._recent_signals = self._recent_signals[-200:]
        if self.store:
            self.store.append_signal(row)

    def _record_event(
        self,
        *,
        category: str,
        event_type: str,
        message: str,
        level: str = "info",
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        order_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """持久化审计事件；失败只记日志，不中断交易路径。"""

        if not self.store:
            return
        try:
            self.store.append_event(
                {
                    "category": category,
                    "event_type": event_type,
                    "level": level,
                    "exchange": exchange,
                    "symbol": symbol,
                    "strategy": strategy,
                    "order_id": order_id,
                    "message": message,
                    "details": details or {},
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )
        except Exception as exc:
            logger.error(f"事件持久化失败：{exc}")
    
    def on_signal(self, callback: Callable):
        """注册信号回调"""
        self._on_signal_callbacks.append(callback)
    
    def on_order(self, callback: Callable):
        """注册订单回调"""
        self._on_order_callbacks.append(callback)

    def add_signal_filter(self, filter_fn: Callable) -> None:
        """注册信号过滤器（B 方案用）。

        async (exchange_name, strategy_name, signal) -> bool
        返回 False 表示拒绝该信号。
        """
        self._signal_filters.append(filter_fn)

    def get_rejected_signals(self, limit: int = 20) -> List[Dict[str, Any]]:
        """返回最近被过滤器拒绝的信号。"""
        return list(self._signal_filter_rejects[-limit:])
    
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
        
        # ── 阶段 5：启动订单同步循环（由引擎驱动；OrderSync 不再自管循环） ──
        self._sync_tasks.append(
            asyncio.create_task(self._order_sync_loop())
        )

        # ── 阶段 5：启动持仓同步循环（同上） ──
        self._sync_tasks.append(
            asyncio.create_task(self._position_sync_loop())
        )
        
        # ── 阶段 5：启动监控告警 ──
        # 注册标准检查器
        checkers = build_engine_checkers(self._exchanges, self)
        for checker in checkers:
            self.monitor.add_checker(checker)
        self._observer.start()
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
        
        # ── 阶段 5：停止实盘子系统（OrderSync/PositionSync 不再自管循环；引擎统一取消） ──
        await self._observer.stop()
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
                
                # 注入策略名到 metadata（供过滤器使用）
                if signal.metadata is None:
                    signal.metadata = {}
                signal.metadata["strategy_name"] = strategy_name
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
        """只生成策略信号，不向交易所下单。"""

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
        """为所有已启用策略手动运行一轮信号评估。"""

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
        """后台信号运行循环。"""

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
        """后台订单同步循环，从所有交易所拉取挂单状态。"""

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
        """后台持仓同步循环，从所有交易所拉取持仓状态。"""

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
        """把一条行情数据喂给匹配的策略实例。"""

        price = float(data.get("last_price", data.get("close", 0)))
        if price > 0:
            await self.position_manager.update_price(exchange_name, symbol, price)
        await strategy.on_market_data(symbol, data)

    def _serialize_signal(self, exchange_name: str, strategy_name: str, signal: Signal) -> Dict[str, Any]:
        """把 Signal 序列化成 API/UI 使用的字典。"""

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
        """策略处于 paper 模式时，把可执行信号应用到模拟盘。"""

        config = self._strategy_configs.get(strategy_name, {})
        if config.get("mode") != "paper" or not signal.is_actionable:
            return None

        price = signal.price or 0
        if price <= 0:
            ticker = await exchange.get_ticker(signal.symbol)
            price = float(ticker.get("last_price", 0))
        order = self.paper_account.apply_signal(exchange_name, strategy_name, signal, price)
        if order:
            if self.store:
                self.store.save_paper_order(order)
                self.store.save_paper_state(self.paper_account.summary())
                # 审计事件：纸盘成交（独立于实盘路径，按 ADR-0001 保持分离）。
                self.store.append_event({
                    "category": "paper",
                    "event_type": "paper_order_filled",
                    "level": "info",
                    "exchange": exchange_name,
                    "symbol": signal.symbol,
                    "strategy": strategy_name,
                    "order_id": str(order.get("order_id", "")) or None,
                    "message": f"{signal.action.value.upper()} {signal.symbol} @ {price} (paper)",
                    "details": {
                        "side": signal.action.value,
                        "quantity": order.get("quantity"),
                        "price": price,
                        "fee": order.get("fee"),
                        "realized_pnl": order.get("realized_pnl"),
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                })
        return order

    def _strategy_matches(
        self,
        strategy_name: str,
        exchange_name: str,
        symbol: str,
        include_disabled: bool = False,
    ) -> bool:
        """判断一个策略实例是否绑定到当前交易所和交易对。"""

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
        """Execute one Signal end-to-end via LiveOrderPipeline.

        The pipeline owns gating, filtering, risk, placement, tracking,
        position update, and observer emission — see app/engine/live_order_pipeline.py.
        This wrapper is kept for backward compatibility with callers that
        hold an ExchangeBase reference directly.
        """
        pipeline = self._pipelines.get(exchange.name.lower())
        if pipeline is None:
            logger.error(f"未找到 {exchange.name} 的 LiveOrderPipeline，请先 add_exchange")
            return
        result = await pipeline.execute(signal)

        # 订单回调仍然由引擎调度（pipeline 不拥有引擎级回调注册表）。
        from app.core.result import Ok
        if isinstance(result, Ok):
            receipt = result.unwrap()
            for callback in self._on_order_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(receipt)
                    else:
                        callback(receipt)
                except Exception as e:
                    logger.error(f"订单回调错误：{e}")
    
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
            # 阶段 5：实盘同步 + 监控状态（loop 状态由引擎统一报告）
            'order_sync': {
                'running': self._running,
                'tracked_orders': self.order_sync.tracked_count,
            },
            'position_sync': {
                'running': self._running,
            },
            'monitor': self.monitor.summary(),
            'timestamp': datetime.utcnow().isoformat(),
        }
