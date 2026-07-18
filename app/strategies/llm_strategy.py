"""
LLM 大模型交易策略

支持三种模式：
- signal（D）：只发信号，引擎不执行
- paper（过渡）：模拟盘执行
- live（A）：全自动执行

防全仓机制：通过 default_order_amount_usdt 控制单笔最大金额。
"""

from typing import Any, Protocol

from app.strategies.base import Signal, SignalAction, StrategyBase
from app.strategies.llm_analyzer import LLMAnalysisResult, LLMAnalyzer


class LLMContextProvider(Protocol):
    """Source of risk + trade-history context for LLM signal generation.

    The strategy doesn't know about RiskManager or SQLiteStore directly —
    anything implementing these two methods can feed the prompt. This keeps
    the strategy unit-testable without spinning up the engine, and lets
    the wiring live in the API layer.

    Both methods are async because the engine's RiskManager exposes an
    async `get_risk_status`. Implementations may choose to return None
    for either block to omit it from the prompt.
    """

    async def get_risk_context(self) -> dict[str, Any] | None:
        """Return current risk metrics (daily_pnl, drawdown, kill switch, ...)."""
        ...

    async def get_trade_history(self, symbol: str) -> dict[str, Any] | None:
        """Return trade history stats for a symbol (win rate, streaks, ...)."""
        ...

    async def get_backtest_performance(self, symbol: str) -> dict[str, Any] | None:
        """Return the latest compatible backtest summary when available."""
        ...

    async def get_recent_ai_decisions(self, symbol: str) -> list[dict[str, Any]] | None:
        """Return recent decisions and outcomes used for prompt grounding."""
        ...


class LLMStrategy(StrategyBase):
    """基于大模型分析的交易策略。

    用法::

        analyzer = LLMAnalyzer(config)
        strategy = LLMStrategy(analyzer=analyzer, default_order_amount_usdt=50)
        engine.add_strategy("llm_btc", strategy, exchange="binance_usdm",
                            symbol="BTCUSDT", interval="1h", mode="signal")
    """

    def __init__(
        self,
        analyzer: LLMAnalyzer,
        name: str = "LLM",
        default_order_amount_usdt: float = 50.0,
        min_confidence: float = 0.5,
        min_candles: int = 10,
        max_candles: int = 80,
        allowed_symbols: list[str] | None = None,
        context_provider: LLMContextProvider | None = None,
        fallback_strategy: StrategyBase | None = None,
    ):
        super().__init__(name=name)
        self.analyzer = analyzer
        self.default_order_amount_usdt = default_order_amount_usdt
        self.min_confidence = min_confidence
        self.min_candles = min_candles
        self.max_candles = max_candles
        # None or empty list = all symbols allowed. Otherwise an exact-match
        # set (case-sensitive) of symbol codes the LLM may trade.
        self.allowed_symbols: set | None = (
            set(allowed_symbols) if allowed_symbols else None
        )
        # Optional provider for risk + trade-history blocks in the LLM prompt.
        # None = those blocks are omitted (backward compat for personal use
        # that doesn't want to wire the engine context in).
        self.context_provider: LLMContextProvider | None = context_provider
        # Optional deterministic strategy used only when the AI call itself
        # fails or is safety-rejected. A normal hold/observe never invokes it.
        self.fallback_strategy = fallback_strategy

        # 缓存最近的 K 线数据，键为 symbol
        self._klines: dict[str, list[dict[str, Any]]] = {}
        # 上次分析结果缓存
        self._last_result: dict[str, LLMAnalysisResult | None] = {}
        self._last_signal: dict[str, Signal | None] = {}

    # ── 生命周期 ──────────────────────────────────────────────

    async def start(self):
        self._klines.clear()
        self._last_result.clear()
        self._last_signal.clear()
        if self.fallback_strategy is not None:
            await self.fallback_strategy.start()

    async def stop(self):
        self._klines.clear()
        self._last_result.clear()
        self._last_signal.clear()
        if self.fallback_strategy is not None:
            await self.fallback_strategy.stop()

    # ── 行情处理 ──────────────────────────────────────────────

    async def on_market_data(self, symbol: str, data: dict[str, Any]):
        """缓存 K 线数据供 generate_signals 使用。"""

        if symbol not in self._klines:
            self._klines[symbol] = []
        self._klines[symbol].append(data)
        # 只保留最近 max_candles 根
        self._klines[symbol] = self._klines[symbol][-self.max_candles:]
        if self.fallback_strategy is not None:
            await self.fallback_strategy.on_market_data(symbol, data)

    # ── 信号生成 ──────────────────────────────────────────────

    async def generate_signals(self, symbol: str) -> Signal | None:
        """调用 LLM 分析并生成交易信号。"""

        # Symbol whitelist gate: refuse symbols not on the configured list
        # *before* spending tokens on the LLM. An empty/None whitelist
        # means "no restriction" (backward compat for personal use).
        if self.allowed_symbols is not None and symbol not in self.allowed_symbols:
            return None

        klines = self._klines.get(symbol, [])
        if not klines:
            return None

        if len(klines) < self.min_candles:
            return None

        # 从最后一根 K 线提取最新价格构建 ticker
        last = klines[-1]
        current_price = float(last.get("close", last.get("last_price", 0)))
        if current_price <= 0:
            return None

        ticker = {
            "symbol": symbol,
            "last_price": current_price,
            "price_change_pct_24h": float(last.get("price_change_pct_24h", 0)),
            "volume_24h": float(last.get("volume_24h", 0)),
            "quote_volume_24h": float(last.get("quote_volume_24h", 0)),
        }

        # 调用 LLM 分析
        # If a context provider is configured, pull live risk metrics and
        # recent trade history so the prompt template (Slice 1 of P1-4)
        # can show the LLM what's actually going on.
        risk_context = None
        trade_history = None
        backtest_performance = None
        recent_ai_decisions = None
        if self.context_provider is not None:
            try:
                risk_context = await self.context_provider.get_risk_context()
            except Exception:
                risk_context = None
            try:
                trade_history = await self.context_provider.get_trade_history(symbol)
            except Exception:
                trade_history = None
            get_backtest = getattr(self.context_provider, "get_backtest_performance", None)
            if get_backtest is not None:
                try:
                    backtest_performance = await get_backtest(symbol)
                except Exception:
                    backtest_performance = None
            get_recent_ai = getattr(self.context_provider, "get_recent_ai_decisions", None)
            if get_recent_ai is not None:
                try:
                    recent_ai_decisions = await get_recent_ai(symbol)
                except Exception:
                    recent_ai_decisions = None

        try:
            result = await self.analyzer.analyze_raw(
                ticker=ticker,
                klines=klines,
                symbol=symbol,
                interval="",  # 由调用方决定周期
                position_context=None,
                risk_context=risk_context,
                trade_history=trade_history,
                backtest_performance=backtest_performance,
                recent_ai_decisions=recent_ai_decisions,
            )
        except Exception:
            self._last_result[symbol] = None
            return await self._rule_fallback(symbol, current_price, "llm_exception")

        self._last_result[symbol] = result
        if result.error_kind is not None:
            return await self._rule_fallback(symbol, current_price, result.error_kind)

        # 决策过滤
        if result.decision in {"hold", "observe"}:
            self._last_signal[symbol] = None
            return None

        if result.confidence < self.min_confidence:
            self._last_signal[symbol] = None
            return None

        # 计算数量：default_order_amount / current_price
        quantity = self.default_order_amount_usdt / current_price
        # 四舍五入到 6 位小数
        quantity = round(quantity, 6)

        action = SignalAction.BUY if result.decision == "buy" else SignalAction.SELL

        signal = Signal(
            symbol=symbol,
            action=action,
            strength=result.confidence,
            quantity=quantity,
            price=current_price,
            order_type="market",
            stop_loss=result.stop_loss,
            take_profit=result.take_profit,
            metadata={
                "reason": result.reason,
                "risk_level": result.risk_level,
                "risk_note": result.risk_note,
                "model": result.model,
                "default_order_amount_usdt": self.default_order_amount_usdt,
                "analysis_time": result.analysis_time,
                "source": "llm_strategy",
            },
        )

        self._update_signal_time(symbol)
        self._last_signal[symbol] = signal
        return signal

    async def _rule_fallback(
        self,
        symbol: str,
        current_price: float,
        failure_reason: str,
    ) -> Signal | None:
        """Ask the configured deterministic rule strategy for a safe fallback."""
        if self.fallback_strategy is None:
            self._last_signal[symbol] = None
            return None
        try:
            fallback = await self.fallback_strategy.generate_signals(symbol)
        except Exception:
            self._last_signal[symbol] = None
            return None
        if fallback is None or fallback.action == SignalAction.HOLD:
            self._last_signal[symbol] = None
            return None
        quantity = fallback.quantity or round(self.default_order_amount_usdt / current_price, 6)
        metadata = dict(fallback.metadata)
        metadata.update(
            {
                "source": "rule_strategy_fallback",
                "fallback_strategy": self.fallback_strategy.name,
                "llm_failure": failure_reason,
            }
        )
        signal = fallback.model_copy(
            update={
                "quantity": quantity,
                "price": fallback.price or current_price,
                "metadata": metadata,
            }
        )
        self._update_signal_time(symbol)
        self._last_signal[symbol] = signal
        return signal

    # ── 查询方法 ──────────────────────────────────────────────

    def get_last_result(self, symbol: str) -> LLMAnalysisResult | None:
        """获取最近一次 LLM 分析结果。"""
        return self._last_result.get(symbol)

    def get_last_signal(self, symbol: str) -> Signal | None:
        """获取最近一次生成的信号。"""
        return self._last_signal.get(symbol)

    def get_kline_count(self, symbol: str) -> int:
        """获取缓存的 K 线数量。"""
        return len(self._klines.get(symbol, []))
