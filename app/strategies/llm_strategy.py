"""
LLM 大模型交易策略

支持三种模式：
- signal（D）：只发信号，引擎不执行
- paper（过渡）：模拟盘执行
- live（A）：全自动执行

防全仓机制：通过 default_order_amount_usdt 控制单笔最大金额。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.strategies.base import StrategyBase, Signal, SignalAction
from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalysisResult


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
        allowed_symbols: Optional[List[str]] = None,
    ):
        super().__init__(name=name)
        self.analyzer = analyzer
        self.default_order_amount_usdt = default_order_amount_usdt
        self.min_confidence = min_confidence
        self.min_candles = min_candles
        self.max_candles = max_candles
        # None or empty list = all symbols allowed. Otherwise an exact-match
        # set (case-sensitive) of symbol codes the LLM may trade.
        self.allowed_symbols: Optional[set] = (
            set(allowed_symbols) if allowed_symbols else None
        )

        # 缓存最近的 K 线数据，键为 symbol
        self._klines: Dict[str, List[Dict[str, Any]]] = {}
        # 上次分析结果缓存
        self._last_result: Dict[str, Optional[LLMAnalysisResult]] = {}
        self._last_signal: Dict[str, Optional[Signal]] = {}

    # ── 生命周期 ──────────────────────────────────────────────

    async def start(self):
        self._klines.clear()
        self._last_result.clear()
        self._last_signal.clear()

    async def stop(self):
        self._klines.clear()
        self._last_result.clear()
        self._last_signal.clear()

    # ── 行情处理 ──────────────────────────────────────────────

    async def on_market_data(self, symbol: str, data: Dict[str, Any]):
        """缓存 K 线数据供 generate_signals 使用。"""

        if symbol not in self._klines:
            self._klines[symbol] = []
        self._klines[symbol].append(data)
        # 只保留最近 max_candles 根
        self._klines[symbol] = self._klines[symbol][-self.max_candles:]

    # ── 信号生成 ──────────────────────────────────────────────

    async def generate_signals(self, symbol: str) -> Optional[Signal]:
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
        try:
            result = await self.analyzer.analyze_raw(
                ticker=ticker,
                klines=klines,
                symbol=symbol,
                interval="",  # 由调用方决定周期
                position_context=None,
            )
        except Exception as exc:
            self._last_result[symbol] = None
            self._last_signal[symbol] = None
            return None

        self._last_result[symbol] = result

        # 决策过滤
        if result.decision == "hold":
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

    # ── 查询方法 ──────────────────────────────────────────────

    def get_last_result(self, symbol: str) -> Optional[LLMAnalysisResult]:
        """获取最近一次 LLM 分析结果。"""
        return self._last_result.get(symbol)

    def get_last_signal(self, symbol: str) -> Optional[Signal]:
        """获取最近一次生成的信号。"""
        return self._last_signal.get(symbol)

    def get_kline_count(self, symbol: str) -> int:
        """获取缓存的 K 线数量。"""
        return len(self._klines.get(symbol, []))
