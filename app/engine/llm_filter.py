"""
LLM 信号过滤器（B 方案）

当策略（如 SMA）产生交易信号后，调用大模型进行二次确认。
仅在 LLM 也认为应该交易时才放行，否则拒绝。

用法::

    # 在 API 或 main.py 中
    from app.engine.llm_filter import LLMSignalFilter
    filter_ = LLMSignalFilter(analyzer, default_order_amount_usdt=50)
    engine.add_signal_filter(filter_)
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.strategies.base import Signal

if TYPE_CHECKING:
    pass


class LLMSignalFilter:
    """LLM 信号过滤器

    收到策略信号后，获取最近 K 线数据，让 LLM 分析当前市场状况，
    只有 LLM 确认方向与策略信号一致时才放行。无行情、调用异常、
    失败结果或无效结果一律拒绝（fail-closed）。
    """

    # LiveOrderPipeline uses this marker to fetch fresh market data only when
    # a filter actually needs it.  This avoids adding a second exchange call
    # to every signal when no market-data-aware filter is attached.
    requires_market_data = True
    market_data_limit = 80

    def __init__(
        self,
        analyzer,  # LLMAnalyzer — annotation deferred to avoid circular import
        default_order_amount_usdt: float = 50.0,
        min_confidence: float = 0.5,
    ):
        self.analyzer = analyzer
        self.default_order_amount_usdt = default_order_amount_usdt
        self.min_confidence = min_confidence
        # 缓存最近的 ticker/klines，由外部通过 feed_market_data 更新
        self._latest_ticker: dict[str, dict[str, Any] | None] = {}
        self._latest_klines: dict[str, list] = {}

    def feed_market_data(self, symbol: str, ticker: dict[str, Any], klines: list) -> None:
        """注入市场数据供过滤器使用。"""
        self._latest_ticker[symbol] = ticker
        self._latest_klines[symbol] = klines[-80:] if klines else []

    async def check(
        self,
        exchange_or_signal: str | Signal,
        strategy_or_context: str | Mapping[str, Any] | None = None,
        signal: Signal | None = None,
    ) -> bool:
        """检查信号，兼容历史三参数回调和流水线上下文协议。

        历史调用方式为 ``check(exchange, strategy, signal)``；新的流水线
        调用方式为 ``check(signal, context)``，其中 context 会携带最新
        ticker/K 线，避免在过滤器外部维护一份可能过期的行情缓存。
        """

        if isinstance(exchange_or_signal, Signal):
            signal = exchange_or_signal
            context = (
                strategy_or_context
                if isinstance(strategy_or_context, Mapping)
                else {}
            )
        else:
            context = {}

        if signal is None:
            logger.warning("LLM 过滤器收到不完整信号，拒绝信号")
            return False

        symbol = signal.symbol
        interval = str(context.get("interval") or "")
        klines = list(
            context.get("klines") or self._latest_klines.get(symbol, [])
        )
        ticker = context.get("ticker")
        if not klines:
            # 没有缓存数据，用 ticker 凑合
            ticker = ticker or self._latest_ticker.get(symbol, {}) or {
                "symbol": symbol,
                "last_price": signal.price or 0,
            }
        else:
            last = klines[-1]
            ticker = ticker or self._latest_ticker.get(symbol, {}) or {
                "symbol": symbol,
                "last_price": float(last.get("close", last.get("last_price", 0))),
            }

        if not ticker.get("last_price"):
            logger.warning(f"LLM 过滤器 [{symbol}]: 无价格数据，拒绝信号")
            return False

        try:
            result = await self.analyzer.analyze_raw(
                ticker=ticker,
                klines=klines,
                symbol=symbol,
                interval=interval,
                position_context=None,
            )
            decision = result.decision
            confidence = float(result.confidence)
            error_kind = getattr(result, "error_kind", None)
        except Exception as exc:
            logger.warning(f"LLM 过滤器 [{symbol}] 调用异常: {exc}，拒绝信号")
            return False

        if error_kind:
            logger.warning(
                f"LLM 过滤器 [{symbol}] 返回失败结果 ({error_kind})，拒绝信号"
            )
            return False

        if decision not in {"buy", "sell", "hold"} or not 0 <= confidence <= 1:
            logger.warning(f"LLM 过滤器 [{symbol}] 返回无效结果，拒绝信号")
            return False

        if decision == "hold":
            logger.info(f"LLM 过滤器 [{symbol}]: LLM hold，拒绝信号 {signal.action.value}")
            return False

        if confidence < self.min_confidence:
            logger.info(
                f"LLM 过滤器 [{symbol}]: 置信度 {confidence:.2f} < {self.min_confidence}，拒绝"
            )
            return False

        # 检查方向一致性
        llm_action = decision  # "buy" / "sell"
        signal_action = signal.action.value  # "buy" / "sell"
        if llm_action != signal_action:
            logger.info(
                f"LLM 过滤器 [{symbol}]: LLM 建议 {llm_action}，策略信号 {signal_action}，拒绝"
            )
            return False

        logger.info(
            f"LLM 过滤器 [{symbol}]: LLM 确认 {llm_action}，置信度 {confidence:.2f}，放行"
        )
        return True
