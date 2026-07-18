"""LLMAnalyzer v2 - uses OpenAIProvider + three-state result.

External API preserved: `analyze_raw()` returns `LLMAnalysisResult` for
backward compatibility with `LLMStrategy` and `LLMSignalFilter`.

Internally uses `OpenAIProvider` (retry policy, three-state errors) and
`LLMFingerprintCache` (TTL 30s) to cut token cost on repeat queries.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.engine.llm_cache import LLMFingerprintCache
from app.engine.llm_decision_protocol import (
    downgrade_duplicate_decision,
    validate_decision_protocol,
)
from app.engine.llm_governor import LLMCallGovernor
from app.engine.llm_guardrails import validate_trade_decision
from app.engine.llm_technical_analysis import (
    format_technical_section,
    kline_summary,
    technical_snapshot,
    true_ranges,
    valid_klines,
)
from app.engine.llm_types import (
    LLMError,
    LLMErrorKind,
    LLMMessage,
    LLMRequest,
    LLMResponse,
)
from app.engine.metrics import LLM_CALL_DURATION, LLM_TOKENS_TOTAL, safe_add, safe_observe
from app.engine.openai_provider import OpenAIProvider, RetryPolicy
from app.exchanges.base import ExchangeBase

# ── Backward-compatible config ──────────────────────────────────────


@dataclass
class LLMAnalyzerConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 2048
    request_timeout: float = 30.0
    min_request_interval_seconds: float = 0.0
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 60.0
    min_candles: int = 20
    max_candles: int = 100
    default_interval: str = "1h"
    default_limit: int = 30
    cache_ttl_seconds: float = 30.0
    cache_max_entries: int = 1024
    prompt_version: str = "v4"  # versioned structured-decision protocol
    max_compact_rows: int = 30  # rows shipped in prompt body
    min_actionable_confidence: float = 0.55
    max_position_pct: float = 0.50


# ── Backward-compatible result ──────────────────────────────────────


@dataclass
class LLMAnalysisResult:
    decision: str  # "buy" | "sell" | "hold"
    confidence: float
    reason: str
    suggested_action: str | None = None
    suggested_quantity: float | None = None
    suggested_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_level: str = "medium"
    risk_note: str = ""
    trend: str = "neutral"
    volatility: str = "medium"
    summary: str = ""
    key_support: float | None = None
    key_resistance: float | None = None
    entry_zone: str = ""
    position_pct: float = 0.0
    bullish_factors: tuple[str, ...] = ()
    bearish_factors: tuple[str, ...] = ()
    invalidation_condition: str = ""
    risk_reward_ratio: float | None = None
    technical_indicators: dict[str, Any] | None = None
    analyzed_symbol: str = ""
    analyzed_interval: str = ""
    candle_count: int = 0
    model: str = ""
    analysis_time: str = ""
    raw_response: str | None = None
    regime: str = "unknown"
    reasons: tuple[str, ...] = ()
    risk_factors: tuple[str, ...] = ()
    position_size: float = 0.0
    invalidation_conditions: tuple[str, ...] = ()
    data_timestamp: str = ""
    model_version: str = ""
    prompt_version: str = ""
    interception_reasons: tuple[str, ...] = ()

    # v2 additions
    error_kind: str | None = None
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        out = {}
        for k, v in self.__dict__.items():
            if isinstance(v, Decimal):
                v = float(v)
            out[k] = v
        return out


# ── Prompt: deterministic indicators + structured model judgment ───


class _PromptTemplate(str):
    """Keep direct ``PROMPT_TEMPLATE.format(...)`` calls backward compatible."""

    def format(self, *args: Any, **kwargs: Any) -> str:
        kwargs.setdefault("technical_section", "- (未提供技术指标快照)")
        kwargs.setdefault("analysis_input_section", "- (未提供统一分析输入)")
        return super().format(*args, **kwargs)


PROMPT_TEMPLATE = _PromptTemplate("""你是一位专业的加密货币永续合约交易分析师。请根据以下市场数据给出**结构化的中文交易建议**。

## 交易规则
- 只交易 USDT 本位永续合约
- 严格风控：单笔最大亏损不超过账户权益的 2%
- 优先考虑趋势跟随，逆势开仓必须给出充分理由
- 关键价位（止损/止盈）须基于近期 K 线高低点
- 当 Kill Switch 已启用、当日亏损已超阈值、当前回撤超过 15% 时，**必须降级为 hold**，并在 reason 中说明
- 当近 N 笔交易胜率持续低于 40% 时，应降低仓位（position_pct < 0.3）并提高 confidence 要求

## 当前市场数据

### 基本信息
- 交易对：{symbol}
- 分析周期：{interval}
- 当前价格：{current_price}
- 24h 涨跌幅：{price_change_24h}%
- 24h 成交量：{volume_24h}
- 24h 成交额：{quote_volume_24h}

### 持仓状态
{position_info}

### 风险状态（来自风控引擎）
{risk_section}

### 近期交易表现
{trade_history_section}

### 引擎计算的技术指标（确定性数据，必须作为证据使用）
{technical_section}

### 统一 AI 分析输入（审计摘要，必须逐项考虑）
{analysis_input_section}

### 最近 K 线数据（紧凑编码：t=时间, o=开, h=高, l=低, c=收, v=量）
```
{candle_data}
```

## 输出要求

**只输出一个 JSON 对象**，不要任何其他文字、解释或 Markdown 标记。字段：

```json
{{
  "trend": "bullish" | "bearish" | "neutral",
  "volatility": "high" | "medium" | "low",
  "summary": "1-2 句核心观察（中文）",
  "key_support": 数字,
  "key_resistance": 数字,
  "decision": "buy" | "sell" | "hold" | "observe",
  "confidence": 0.0-1.0,
  "entry_zone": "价格区间，例如 95000-96000",
  "stop_loss": 数字,
  "take_profit": 数字,
  "position_pct": 0.0-1.0,
  "position_size": 0.0-0.5,
  "regime": "trending" | "ranging" | "volatile" | "breakout" | "unknown",
  "reasons": ["最多 6 条核心依据"],
  "risk_factors": ["最多 6 条风险因素"],
  "bullish_factors": ["最多 3 条看多证据"],
  "bearish_factors": ["最多 3 条看空证据"],
  "invalidation_condition": "使当前判断失效的具体价格或条件",
  "invalidation_conditions": ["最多 6 条失效条件"],
  "data_timestamp": "必须原样使用统一输入中的 data_timestamp",
  "model_version": "模型版本标识",
  "prompt_version": "v4",
  "reason": "综合趋势、动量、量能、波动率和风控后的操作理由（中文）",
  "risk_level": "low" | "medium" | "high",
  "risk_note": "主要风险点（中文，1-2 句）"
}}
```

**重要**:
- 先区分“市场观察”和“交易决策”，不能只凭单一指标下结论。
- `confidence >= 0.7` 必须至少有趋势、动量、量能三类证据中的两类同向。
- buy/sell 必须给出具体止损、止盈、失效条件，并确保风险收益比合理；证据冲突时返回 hold。
- `stop_loss` / `take_profit` / `key_support` / `key_resistance` 必须是 JSON number（不是字符串）。""")


def _system_message() -> str:
    """Return the system prompt with risk constraints and a few-shot example.

    The system message is the durable place for safety guidance — it survives
    edits to the user-facing prompt template and stays in front of the model
    on every request. A single worked example teaches the LLM the expected
    JSON shape and reasoning style without bloating the per-request prompt.
    """

    return (
        "你是一位专业的加密货币永续合约交易分析师。请根据市场数据给出交易建议。"
        "只输出 JSON，不要包含其他文字。\n"
        "\n"
        "## 硬性风险约束（必须遵守，违反会被引擎拒绝）\n"
        "1. 单笔最大亏损 ≤ 账户权益的 2%\n"
        "2. 当 Kill Switch 启用时，所有 decision 必须为 hold\n"
        "3. 当日已实现亏损 ≥ max_daily_loss 时，所有 decision 必须为 hold\n"
        "4. 当前回撤 ≥ max_drawdown_pct 时，建议降级为 hold 或大幅降低 position_pct\n"
        "5. 关键价位（止损/止盈）必须基于近期 K 线高低点，不能凭空给数字\n"
        "6. 必须交叉验证趋势、动量、成交量和波动率；证据冲突时 decision=hold\n"
        "7. confidence >= 0.7 时，bullish_factors / bearish_factors 中必须给出至少两条同向证据\n"
        "8. buy/sell 必须给出明确 invalidation_condition，且不得把预测描述成确定事实\n"
        "\n"
        "## 示例\n"
        "输入摘要：BTCUSDT 1h，价格 50000 附近，连续 3 根 K 线收阴，成交量下降，"
        "无持仓，账户权益 10000 USDT，胜率 60%。\n"
        "正确输出：\n"
        '{"trend":"bearish","volatility":"medium","summary":"短期趋势转弱，量能不足",'
        '"key_support":49500,"key_resistance":50500,"decision":"hold",'
        '"confidence":0.4,"entry_zone":"--","stop_loss":null,"take_profit":null,'
        '"position_pct":0.0,"bullish_factors":[],"bearish_factors":["短期均线向下",'
        '"连续收阴"],"invalidation_condition":"重新站稳 50500 后弱势判断失效",'
        '"reason":"趋势与价格行为偏弱，但量能不足以确认突破，等待关键位",'
        '"risk_level":"medium","risk_note":"如跌破 49500 支撑需警惕进一步下行"}\n'
        "\n"
        "请严格按上述 JSON 结构输出，并完整返回 decision、confidence、regime、reasons、risk_factors、"
        "stop_loss、take_profit、position_size、invalidation_conditions、data_timestamp、model_version、prompt_version。"
    )


def _format_risk_section(risk: dict[str, Any] | None) -> str:
    """Render the risk-context block for the user prompt.

    When the engine doesn't pass risk data, the section still appears
    (with a "no data" marker) so the LLM doesn't see a missing section
    and infer the engine forgot to feed it.
    """
    if not risk:
        return "- (无风控数据，默认按中性处理)"

    kill = risk.get("kill_switch_enabled", False)
    daily = risk.get("daily_pnl", 0.0)
    drawdown = risk.get("current_drawdown_pct", 0.0)
    orders = risk.get("orders_last_minute", 0)
    max_orders = risk.get("max_orders_per_minute", 0)
    return (
        f"- Kill Switch: {'已启用（必须 hold）' if kill else '未启用'}\n"
        f"- 当日已实现盈亏: {daily:+.2f} USDT\n"
        f"- 当前回撤: {drawdown * 100:.2f}%\n"
        f"- 限速: {orders}/{max_orders} 单/分钟"
    )


def _format_trade_history_section(history: dict[str, Any] | None) -> str:
    """Render the trade-history block for the user prompt.

    When no history is available, the section shows a "no history" marker.
    """
    if not history:
        return "- (无历史交易记录，按首次交易谨慎处理)"

    total = history.get("total_trades", 0)
    wins = history.get("winning_trades", 0)
    losses = history.get("losing_trades", 0)
    win_rate = history.get("win_rate", 0.0)
    avg_win = history.get("avg_win", 0.0)
    avg_loss = history.get("avg_loss", 0.0)
    streak_w = history.get("max_consecutive_wins", 0)
    streak_l = history.get("max_consecutive_losses", 0)
    return (
        f"- 总交易数: {total}（{wins} 胜 / {losses} 负）\n"
        f"- 胜率: {win_rate * 100:.1f}%\n"
        f"- 平均盈: {avg_win:+.2f} USDT / 平均亏: {avg_loss:+.2f} USDT\n"
        f"- 最长连盈: {streak_w} 笔 / 最长连亏: {streak_l} 笔"
    )


# ── LLMAnalyzer v2 ──────────────────────────────────────────────────


class LLMAnalyzer:
    def __init__(
        self,
        config: LLMAnalyzerConfig | None = None,
        provider: OpenAIProvider | None = None,
        cache: LLMFingerprintCache | None = None,
        on_decision: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config or LLMAnalyzerConfig()
        if not self.config.api_key:
            self.config.api_key = os.environ.get("LLM_API_KEY", "")
        # Provider selection by base_url when not explicitly given.
        # DeepSeek / MiniMax are OpenAI-compatible, so the same class
        # works for all of them. We pick the subclass by URL prefix.
        if provider is None:
            provider = self._select_provider()
        self._provider = provider
        self._cache = cache or LLMFingerprintCache(
            ttl_seconds=self.config.cache_ttl_seconds,
            max_entries=self.config.cache_max_entries,
        )
        # The governor is analyzer-instance scoped: long-running strategies
        # retain its state, while one-shot API analyses remain independent.
        self._governor = LLMCallGovernor(
            min_request_interval_seconds=self.config.min_request_interval_seconds,
            circuit_failure_threshold=self.config.circuit_failure_threshold,
            circuit_cooldown_seconds=self.config.circuit_cooldown_seconds,
        )
        # Optional observer — fired once per LLM decision (after the
        # response comes back, before the result is returned to the
        # caller). Used by traders / API endpoints to persist the
        # decision as an audit event. Errors here are swallowed.
        self._on_decision = on_decision
        # Bounded in-memory duplicate barrier. The execution engine still owns
        # durable idempotency; this prevents the same AI conclusion from
        # becoming two strategy signals before it reaches that layer.
        self._recent_action_fingerprints: dict[str, None] = {}

    def _select_provider(self) -> OpenAIProvider:
        """Pick provider class by config.base_url prefix."""
        url = (self.config.base_url or "").lower()
        key = self.config.api_key
        if "deepseek" in url:
            from app.engine.deepseek_provider import DeepSeekProvider

            return DeepSeekProvider(
                api_key=key,
                base_url=self.config.base_url,
                timeout_seconds=self.config.request_timeout,
            )
        if "minimax" in url or "minimax" in url:
            from app.engine.minimax_provider import MiniMaxProvider

            return MiniMaxProvider(
                api_key=key,
                base_url=self.config.base_url,
                timeout_seconds=self.config.request_timeout,
            )
        if "anthropic" in url or "claude" in url:
            from app.engine.anthropic_provider import AnthropicProvider

            return AnthropicProvider(
                api_key=key,
                base_url=self.config.base_url,
                timeout_seconds=self.config.request_timeout,
            )
        if "ollama" in url or url.endswith(":11434") or "localhost" in url:
            from app.engine.ollama_provider import OllamaProvider

            return OllamaProvider(
                api_key=key,
                base_url=self.config.base_url,
                timeout_seconds=self.config.request_timeout,
            )
        return OpenAIProvider(
            api_key=key,
            base_url=self.config.base_url,
            timeout_seconds=self.config.request_timeout,
            retry_policy=RetryPolicy(),
        )

    # ── Public API ──────────────────────────────────────────────

    async def analyze(
        self,
        exchange: ExchangeBase,
        symbol: str,
        interval: str | None = None,
        limit: int | None = None,
        position_context: dict[str, Any] | None = None,
        risk_context: dict[str, Any] | None = None,
        trade_history: dict[str, Any] | None = None,
        backtest_performance: dict[str, Any] | None = None,
        recent_ai_decisions: list[dict[str, Any]] | None = None,
    ) -> LLMAnalysisResult:
        interval = interval or self.config.default_interval
        limit = min(
            max(limit or self.config.default_limit, self.config.min_candles),
            self.config.max_candles,
        )
        preflight = self._preflight_failure()
        if preflight is not None:
            return await self._finalize_fresh_response(
                preflight, symbol, interval, candle_count=0, exchange=exchange
            )

        try:
            ticker, klines = await self._fetch_market_data(exchange, symbol, interval, limit)
        except Exception as exc:
            return await self._finalize_fresh_response(
                LLMResponse(
                    failed=LLMError(
                        kind=LLMErrorKind.NETWORK,
                        message=f"获取市场数据失败: {exc}",
                        retryable=True,
                    )
                ),
                symbol,
                interval,
                candle_count=0,
                exchange=exchange,
            )
        return await self.analyze_raw(
            ticker=ticker,
            klines=klines,
            symbol=symbol,
            interval=interval,
            position_context=position_context,
            risk_context=risk_context,
            trade_history=trade_history,
            backtest_performance=backtest_performance,
            recent_ai_decisions=recent_ai_decisions,
            exchange=exchange,
        )

    async def analyze_raw(
        self,
        ticker: dict[str, Any],
        klines: list[dict[str, Any]],
        symbol: str,
        interval: str,
        position_context: dict[str, Any] | None = None,
        risk_context: dict[str, Any] | None = None,
        trade_history: dict[str, Any] | None = None,
        backtest_performance: dict[str, Any] | None = None,
        recent_ai_decisions: list[dict[str, Any]] | None = None,
        exchange: ExchangeBase | None = None,
    ) -> LLMAnalysisResult:
        preflight = self._preflight_failure()
        if preflight is not None:
            return await self._finalize_fresh_response(
                preflight, symbol, interval, candle_count=len(klines), exchange=exchange
            )

        position_signature = self._position_signature(position_context)
        technical_snapshot = self._technical_snapshot(klines)
        analysis_input = self._build_analysis_input(
            ticker=ticker,
            klines=klines,
            position_context=position_context,
            risk_context=risk_context,
            trade_history=trade_history,
            backtest_performance=backtest_performance,
            recent_ai_decisions=recent_ai_decisions,
            technical_snapshot=technical_snapshot,
        )
        last_candle = klines[-1] if klines else {}
        cache_key = LLMFingerprintCache.fingerprint(
            symbol=symbol,
            interval=interval,
            last_candle=last_candle,
            position_signature=position_signature,
            prompt_version=self.config.prompt_version,
            context_signature=self._analysis_context_signature(
                ticker,
                risk_context,
                trade_history,
                technical_snapshot,
                backtest_performance=backtest_performance,
                recent_ai_decisions=recent_ai_decisions,
            ),
        )
        cached = self._cache.get(cache_key)
        if cached is not None and cached.is_ok:
            return self._translate(
                cached,
                symbol,
                interval,
                len(klines),
                cache_hit=True,
                current_price=ticker.get("last_price"),
                technical_indicators=technical_snapshot,
            )

        governor_failure = self._governor.before_provider_call()
        if governor_failure is not None:
            return await self._finalize_fresh_response(
                LLMResponse(failed=governor_failure),
                symbol,
                interval,
                candle_count=len(klines),
                exchange=exchange,
            )

        prompt = self._build_prompt(
            symbol,
            interval,
            ticker,
            klines,
            position_context=position_context,
            risk_context=risk_context,
            trade_history=trade_history,
            backtest_performance=backtest_performance,
            recent_ai_decisions=recent_ai_decisions,
            technical_snapshot=technical_snapshot,
            analysis_input=analysis_input,
        )
        request = LLMRequest(
            model=self.config.model,
            messages=[
                LLMMessage(role="system", content=_system_message()),
                LLMMessage(role="user", content=prompt),
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            response_format_json=True,
        )
        response = await self._provider.complete(request)
        response = validate_decision_protocol(
            response,
            min_confidence=self.config.min_actionable_confidence,
            max_position_pct=self.config.max_position_pct,
        )
        response = validate_trade_decision(response, current_price=ticker.get("last_price"))
        response = self._intercept_duplicate(
            response, symbol=symbol, interval=interval, data_timestamp=analysis_input["data_timestamp"]
        )
        self._governor.record_provider_response(response)
        self._record_provider_metrics(response)
        if response.is_ok:
            self._cache.put(cache_key, response)
        return await self._finalize_fresh_response(
            response,
            symbol,
            interval,
            candle_count=len(klines),
            exchange=exchange,
            current_price=ticker.get("last_price"),
            technical_indicators=technical_snapshot,
            analysis_input=analysis_input,
        )

    def _preflight_failure(self) -> LLMResponse | None:
        """Fail fast before market I/O when the configured provider has no key."""
        if str(self.config.api_key or "").strip():
            return None
        return LLMResponse(
            failed=LLMError(
                kind=LLMErrorKind.API_KEY_MISSING,
                message="未配置 LLM API Key，请设置 LLM_API_KEY 后重试。",
                retryable=False,
            )
        )

    def _record_provider_metrics(self, response: LLMResponse) -> None:
        """Emit best-effort metrics for one real provider request.

        Preflight and market-data failures never reach this method: they do
        not spend provider time or tokens. Safety rejections do reach it, so
        the response was produced by a model but rejected before it could
        enter a trading path.
        """
        provider = str(getattr(self._provider, "name", "unknown") or "unknown")
        model = (
            response.decided.model
            if response.decided and response.decided.model
            else (self.config.model or "unknown")
        )
        status = response.failed.kind.value if response.failed else "success"
        latency_ms = max(0, int(response.latency_ms or 0))

        safe_observe(
            LLM_CALL_DURATION,
            latency_ms / 1000.0,
            provider=provider,
            model=model,
            status=status,
        )
        if response.prompt_tokens > 0:
            safe_add(
                LLM_TOKENS_TOTAL,
                response.prompt_tokens,
                provider=provider,
                model=model,
                type="prompt",
            )
        if response.completion_tokens > 0:
            safe_add(
                LLM_TOKENS_TOTAL,
                response.completion_tokens,
                provider=provider,
                model=model,
                type="completion",
            )

    async def _finalize_fresh_response(
        self,
        response: LLMResponse,
        symbol: str,
        interval: str,
        *,
        candle_count: int,
        exchange: ExchangeBase | None,
        current_price: Any = None,
        technical_indicators: dict[str, Any] | None = None,
        analysis_input: dict[str, Any] | None = None,
    ) -> LLMAnalysisResult:
        """Audit and translate a non-cached provider/preflight response."""
        if self._on_decision is not None:
            try:
                await self._on_decision(
                    {
                        "symbol": symbol,
                        "interval": interval,
                        "exchange": str(getattr(exchange, "name", "") or ""),
                        "decision": response.decided.decision if response.decided else None,
                        "confidence": response.decided.confidence if response.decided else None,
                        "reason": (
                            response.decided.reason
                            if response.decided
                            else (response.failed.message if response.failed else None)
                        ),
                        "provider": str(getattr(self._provider, "name", "unknown") or "unknown"),
                        "model": (
                            response.decided.model
                            if response.decided and response.decided.model
                            else self.config.model
                        ),
                        "risk_level": response.decided.risk_level if response.decided else "",
                        "prompt_tokens": response.prompt_tokens,
                        "completion_tokens": response.completion_tokens,
                        "latency_ms": response.latency_ms,
                        "failed": response.failed.kind.value if response.failed else None,
                        "cache_hit": False,
                        "data_timestamp": response.decided.data_timestamp if response.decided else None,
                        "model_version": (
                            response.decided.model_version if response.decided else self.config.model
                        ),
                        "prompt_version": (
                            response.decided.prompt_version if response.decided else self.config.prompt_version
                        ),
                        "interception_reasons": (
                            response.decided.interception_reasons if response.decided else ()
                        ),
                        "input_summary": analysis_input or {},
                        "output_summary": self._output_summary(response),
                    }
                )
            except Exception:
                # Audit failures must never break the trading path.
                pass
        return self._translate(
            response,
            symbol,
            interval,
            candle_count,
            cache_hit=False,
            current_price=current_price,
            technical_indicators=technical_indicators,
        )

    # ── Internals ──────────────────────────────────────────────

    async def _fetch_market_data(
        self,
        exchange: ExchangeBase,
        symbol: str,
        interval: str,
        limit: int,
    ) -> tuple:
        import asyncio

        ticker, klines = await asyncio.gather(
            exchange.get_ticker(symbol),
            exchange.get_klines(symbol, interval=interval, limit=limit),
        )
        return ticker, klines

    def _build_prompt(
        self,
        symbol: str,
        interval: str,
        ticker: dict[str, Any],
        klines: list[dict[str, Any]],
        position_context: dict[str, Any] | None = None,
        risk_context: dict[str, Any] | None = None,
        trade_history: dict[str, Any] | None = None,
        backtest_performance: dict[str, Any] | None = None,
        recent_ai_decisions: list[dict[str, Any]] | None = None,
        technical_snapshot: dict[str, Any] | None = None,
        analysis_input: dict[str, Any] | None = None,
    ) -> str:
        candle_data = self._render_klines_compact(klines)
        technical_snapshot = technical_snapshot or self._technical_snapshot(klines)
        analysis_input = analysis_input or self._build_analysis_input(
            ticker=ticker,
            klines=klines,
            position_context=position_context,
            risk_context=risk_context,
            trade_history=trade_history,
            backtest_performance=backtest_performance,
            recent_ai_decisions=recent_ai_decisions,
            technical_snapshot=technical_snapshot,
        )
        if position_context:
            pos_lines = [
                f"- 持仓方向: {position_context.get('side', '无')}",
                f"- 持仓量: {position_context.get('quantity', 0)}",
                f"- 入场均价: {position_context.get('avg_entry_price', '--')}",
                f"- 未实现盈亏: {position_context.get('unrealized_pnl', 0):.2f} USDT",
                f"- 当前权益: {position_context.get('equity', '--')} USDT",
            ]
            pos_info = "\n".join(pos_lines)
        else:
            pos_info = "- 当前无持仓"

        risk_section = _format_risk_section(risk_context)
        trade_history_section = _format_trade_history_section(trade_history)

        current_price = float(ticker.get("last_price", 0))
        price_change_24h = float(ticker.get("price_change_pct_24h", 0))
        volume_24h = float(ticker.get("volume_24h", 0))
        quote_volume_24h = float(ticker.get("quote_volume_24h", 0))
        return PROMPT_TEMPLATE.format(
            symbol=symbol,
            interval=interval,
            current_price=current_price,
            price_change_24h=price_change_24h,
            volume_24h=volume_24h,
            quote_volume_24h=quote_volume_24h,
            position_info=pos_info,
            risk_section=risk_section,
            trade_history_section=trade_history_section,
            technical_section=format_technical_section(technical_snapshot),
            analysis_input_section=json.dumps(analysis_input, ensure_ascii=False, default=str),
            candle_data=candle_data,
        )

    # ── Compact K-line encoding ──────────────────────────────────

    @staticmethod
    def _valid_klines(klines: list[dict[str, Any]]) -> list[dict[str, float | Any]]:
        return valid_klines(klines)

    @staticmethod
    def _true_ranges(ordered: list[dict[str, float | Any]]) -> list[float]:
        return true_ranges(ordered)

    @staticmethod
    def _technical_snapshot(klines: list[dict[str, Any]]) -> dict[str, Any]:
        return technical_snapshot(klines)

    @staticmethod
    def _kline_summary(klines: list[dict[str, Any]]) -> dict[str, float]:
        return kline_summary(klines)

    @staticmethod
    def _analysis_context_signature(
        ticker: dict[str, Any],
        risk_context: dict[str, Any] | None,
        trade_history: dict[str, Any] | None,
        technical_snapshot: dict[str, Any],
        *,
        backtest_performance: dict[str, Any] | None = None,
        recent_ai_decisions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "ticker": {
                key: ticker.get(key)
                for key in (
                    "last_price",
                    "price_change_pct_24h",
                    "volume_24h",
                    "quote_volume_24h",
                )
            },
            "risk": risk_context or {},
            "history": trade_history or {},
            "backtest": backtest_performance or {},
            "recent_ai_decisions": recent_ai_decisions or [],
            "technical": technical_snapshot,
        }

    @staticmethod
    def _build_analysis_input(
        *,
        ticker: dict[str, Any],
        klines: list[dict[str, Any]],
        position_context: dict[str, Any] | None,
        risk_context: dict[str, Any] | None,
        trade_history: dict[str, Any] | None,
        backtest_performance: dict[str, Any] | None,
        recent_ai_decisions: list[dict[str, Any]] | None,
        technical_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Create one serializable, auditable analysis-input envelope."""
        last_candle = klines[-1] if klines else {}
        timestamp = last_candle.get("open_time") or ticker.get("timestamp") or datetime.now(UTC).isoformat()
        atr_pct = technical_snapshot.get("atr_pct")
        volatility_state = "unknown"
        try:
            volatility_state = "high" if float(atr_pct) >= 3 else "low" if float(atr_pct) < 1 else "medium"
        except (TypeError, ValueError):
            pass
        volume_ratio = technical_snapshot.get("volume_ratio")
        volume_state = "unknown"
        try:
            volume_state = "high" if float(volume_ratio) >= 1.2 else "low" if float(volume_ratio) < 0.8 else "normal"
        except (TypeError, ValueError):
            pass
        trend_state = str(technical_snapshot.get("trend_bias") or "neutral")
        regime = "volatile" if volatility_state == "high" else "trending" if trend_state != "neutral" else "ranging"
        return {
            "data_timestamp": str(timestamp),
            "market_data": {
                key: ticker.get(key)
                for key in ("last_price", "price_change_pct_24h", "volume_24h", "quote_volume_24h")
            },
            "technical_indicators": technical_snapshot,
            "trend_state": trend_state,
            "volatility_state": volatility_state,
            "volume_state": volume_state,
            "position": position_context or {"side": "flat", "quantity": 0},
            "account_risk": risk_context or {},
            "historical_trade_performance": trade_history or {},
            "historical_backtest_performance": backtest_performance or {},
            "market_regime": regime,
            "recent_ai_decisions": list(recent_ai_decisions or [])[:10],
        }

    def _intercept_duplicate(
        self,
        response: LLMResponse,
        *,
        symbol: str,
        interval: str,
        data_timestamp: str,
    ) -> LLMResponse:
        if response.is_failed or response.decided is None or response.decided.decision not in {"buy", "sell"}:
            return response
        decision = response.decided
        fingerprint = "|".join(
            (symbol, interval, data_timestamp, decision.decision, str(decision.stop_loss), str(decision.take_profit))
        )
        if fingerprint in self._recent_action_fingerprints:
            return downgrade_duplicate_decision(response)
        self._recent_action_fingerprints[fingerprint] = None
        if len(self._recent_action_fingerprints) > 1024:
            self._recent_action_fingerprints.pop(next(iter(self._recent_action_fingerprints)))
        return response

    @staticmethod
    def _output_summary(response: LLMResponse) -> dict[str, Any]:
        if response.failed:
            return {"failed": response.failed.kind.value, "reason": response.failed.message}
        if response.decided is None:
            return {}
        decision = response.decided
        return {
            "decision": decision.decision,
            "confidence": decision.confidence,
            "regime": decision.regime,
            "reasons": decision.reasons,
            "risk_factors": decision.risk_factors,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "position_size": decision.position_size,
            "invalidation_conditions": decision.invalidation_conditions,
        }

    def _render_klines_compact(self, klines: list[dict[str, Any]]) -> str:
        """Render K-lines as compact text.

        Output format (newest first):
          #K n=30 first=100.5 last=129.5 hi=130.0 lo=99.0 atr=2.0
          06-26-14:00 o:129 h:130 l:128 c:129.5 v:39.0
          ...

        Summary header + up to max_compact_rows body lines. Roughly half the
        size of the old aligned-table format.
        """
        valid = self._valid_klines(klines)
        if not valid:
            return ""
        ordered = sorted(valid, key=lambda k: str(k.get("open_time", "")), reverse=True)
        rows = ordered[: self.config.max_compact_rows]
        summary = self._kline_summary(valid)
        header = (
            f"#K n={summary['count']} "
            f"first={summary['first_close']:.2f} "
            f"last={summary['last_close']:.2f} "
            f"hi={summary['max_high']:.2f} "
            f"lo={summary['min_low']:.2f} "
            f"atr={summary['atr']:.2f}"
        )
        body = []
        for k in rows:
            ot = k.get("open_time", "")
            if isinstance(ot, datetime):
                ot = ot.strftime("%m-%d %H:%M")
            else:
                ot = str(ot)[-11:]
            body.append(
                f"{ot} o:{float(k.get('open', 0)):.2f} "
                f"h:{float(k.get('high', 0)):.2f} "
                f"l:{float(k.get('low', 0)):.2f} "
                f"c:{float(k.get('close', 0)):.2f} "
                f"v:{float(k.get('volume', 0)):.2f}"
            )
        return "\n".join([header, *body])

    @staticmethod
    def _position_signature(position_context: dict[str, Any] | None) -> str:
        if not position_context:
            return "none"
        side = position_context.get("side", "")
        qty = position_context.get("quantity", 0)
        avg = position_context.get("avg_entry_price", 0)
        return f"{side}:{qty}:{avg}"

    @staticmethod
    def _risk_reward_ratio(
        decision: str, current_price: Any, stop_loss: Any, take_profit: Any
    ) -> float | None:
        try:
            price = float(current_price)
            stop = float(stop_loss)
            target = float(take_profit)
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in (price, stop, target)):
            return None
        if min(price, stop, target) <= 0:
            return None
        if decision == "buy" and stop < price < target:
            risk = price - stop
            reward = target - price
        elif decision == "sell" and target < price < stop:
            risk = stop - price
            reward = price - target
        else:
            return None
        return round(reward / risk, 2) if risk > 0 else None

    @staticmethod
    def _translate(
        response: LLMResponse,
        symbol: str,
        interval: str,
        candle_count: int,
        cache_hit: bool,
        *,
        current_price: Any = None,
        technical_indicators: dict[str, Any] | None = None,
    ) -> LLMAnalysisResult:
        now = datetime.now(UTC).isoformat()
        if response.is_failed:
            err = response.failed
            return LLMAnalysisResult(
                decision="hold",
                confidence=0.0,
                reason=f"[{err.kind.value}] {err.message}",
                risk_level="high",
                risk_note="API 异常" if err.kind != LLMErrorKind.API_KEY_MISSING else "未配置",
                technical_indicators=technical_indicators,
                analyzed_symbol=symbol,
                analyzed_interval=interval,
                candle_count=candle_count,
                analysis_time=now,
                error_kind=err.kind.value,
            )
        d = response.decided
        try:
            suggested_price = float(current_price)
        except (TypeError, ValueError):
            suggested_price = None
        if suggested_price is not None and (
            not math.isfinite(suggested_price) or suggested_price <= 0
        ):
            suggested_price = None
        return LLMAnalysisResult(
            decision=d.decision,
            confidence=d.confidence,
            reason=d.reason,
            suggested_action=d.decision,
            suggested_price=suggested_price,
            stop_loss=d.stop_loss,
            take_profit=d.take_profit,
            risk_level=d.risk_level,
            risk_note=d.risk_note,
            trend=d.trend,
            volatility=d.volatility,
            summary=d.summary,
            key_support=d.key_support,
            key_resistance=d.key_resistance,
            entry_zone=d.entry_zone,
            position_pct=d.position_pct,
            bullish_factors=d.bullish_factors,
            bearish_factors=d.bearish_factors,
            invalidation_condition=d.invalidation_condition,
            risk_reward_ratio=LLMAnalyzer._risk_reward_ratio(
                d.decision, current_price, d.stop_loss, d.take_profit
            ),
            technical_indicators=technical_indicators,
            analyzed_symbol=symbol,
            analyzed_interval=interval,
            candle_count=candle_count,
            model=d.model,
            analysis_time=now,
            raw_response=d.raw_response,
            regime=d.regime,
            reasons=d.reasons,
            risk_factors=d.risk_factors,
            position_size=d.position_size,
            invalidation_conditions=d.invalidation_conditions,
            data_timestamp=d.data_timestamp,
            model_version=d.model_version,
            prompt_version=d.prompt_version,
            interception_reasons=d.interception_reasons,
            cache_hit=cache_hit,
        )

    async def close(self) -> None:
        await self._provider._client_aclose() if hasattr(self._provider, "_client_aclose") else None


# Re-export for backward compatibility with `from app.strategies.llm_analyzer import LLMAnalyzer`
__all__ = ["LLMAnalyzer", "LLMAnalyzerConfig", "LLMAnalysisResult", "PROMPT_TEMPLATE"]
