"""LLMAnalyzer v2 - uses OpenAIProvider + three-state result.

External API preserved: `analyze_raw()` returns `LLMAnalysisResult` for
backward compatibility with `LLMStrategy` and `LLMSignalFilter`.

Internally uses `OpenAIProvider` (retry policy, three-state errors) and
`LLMFingerprintCache` (TTL 30s) to cut token cost on repeat queries.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx

from app.engine.llm_cache import LLMFingerprintCache
from app.engine.llm_types import (
    LLMDecided,
    LLMError,
    LLMErrorKind,
    LLMMessage,
    LLMRequest,
    LLMResponse,
)
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
    min_candles: int = 20
    max_candles: int = 100
    default_interval: str = "1h"
    default_limit: int = 30
    cache_ttl_seconds: float = 30.0
    cache_max_entries: int = 1024
    prompt_version: str = "v2"  # bumped: compact k-line + system/user split
    max_compact_rows: int = 30  # rows shipped in prompt body


# ── Backward-compatible result ──────────────────────────────────────


@dataclass
class LLMAnalysisResult:
    decision: str  # "buy" | "sell" | "hold"
    confidence: float
    reason: str
    suggested_action: Optional[str] = None
    suggested_quantity: Optional[float] = None
    suggested_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_level: str = "medium"
    risk_note: str = ""
    analyzed_symbol: str = ""
    analyzed_interval: str = ""
    candle_count: int = 0
    model: str = ""
    analysis_time: str = ""
    raw_response: Optional[str] = None

    # v2 additions
    error_kind: Optional[str] = None
    cache_hit: bool = False

    def to_dict(self) -> Dict[str, Any]:
        out = {}
        for k, v in self.__dict__.items():
            if isinstance(v, Decimal):
                v = float(v)
            out[k] = v
        return out


# ── Prompt (unchanged from v1 for now; future: compact + split) ────


PROMPT_TEMPLATE = """你是一位专业的加密货币永续合约交易分析师。请根据以下市场数据给出**结构化的中文交易建议**。

## 交易规则
- 只交易 USDT 本位永续合约
- 严格风控：单笔最大亏损不超过账户权益的 2%
- 优先考虑趋势跟随，逆势开仓必须给出充分理由
- 关键价位（止损/止盈）须基于近期 K 线高低点

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
  "decision": "buy" | "sell" | "hold",
  "confidence": 0.0-1.0,
  "entry_zone": "价格区间，例如 95000-96000",
  "stop_loss": 数字,
  "take_profit": 数字,
  "position_pct": 0.0-1.0,
  "reason": "1-2 句操作理由（中文）",
  "risk_level": "low" | "medium" | "high",
  "risk_note": "主要风险点（中文，1-2 句）"
}}
```

**重要**: 每条建议必须有具体数字。`stop_loss` / `take_profit` / `key_support` / `key_resistance` 必须是 JSON number（不是字符串）。"""


def _system_message() -> str:
    return (
        "你是一位专业的加密货币永续合约交易分析师。请根据市场数据给出交易建议。"
        "只输出 JSON，不要包含其他文字。"
    )


# ── LLMAnalyzer v2 ──────────────────────────────────────────────────


class LLMAnalyzer:
    def __init__(
        self,
        config: Optional[LLMAnalyzerConfig] = None,
        provider: Optional[OpenAIProvider] = None,
        cache: Optional[LLMFingerprintCache] = None,
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

    def _select_provider(self) -> OpenAIProvider:
        """Pick provider class by config.base_url prefix."""
        url = (self.config.base_url or "").lower()
        key = self.config.api_key
        if "deepseek" in url:
            from app.engine.deepseek_provider import DeepSeekProvider
            return DeepSeekProvider(
                api_key=key, base_url=self.config.base_url,
                timeout_seconds=self.config.request_timeout,
            )
        if "minimax" in url or "minimax" in url:
            from app.engine.minimax_provider import MiniMaxProvider
            return MiniMaxProvider(
                api_key=key, base_url=self.config.base_url,
                timeout_seconds=self.config.request_timeout,
            )
        if "anthropic" in url or "claude" in url:
            from app.engine.anthropic_provider import AnthropicProvider
            return AnthropicProvider(
                api_key=key, base_url=self.config.base_url,
                timeout_seconds=self.config.request_timeout,
            )
        if "ollama" in url or url.endswith(":11434") or "localhost" in url:
            from app.engine.ollama_provider import OllamaProvider
            return OllamaProvider(
                api_key=key, base_url=self.config.base_url,
                timeout_seconds=self.config.request_timeout,
            )
        return OpenAIProvider(
            api_key=key, base_url=self.config.base_url,
            timeout_seconds=self.config.request_timeout,
            retry_policy=RetryPolicy(),
        )
        self._cache = cache or LLMFingerprintCache(
            ttl_seconds=self.config.cache_ttl_seconds,
            max_entries=self.config.cache_max_entries,
        )

    # ── Public API ──────────────────────────────────────────────

    async def analyze(
        self,
        exchange: ExchangeBase,
        symbol: str,
        interval: Optional[str] = None,
        limit: Optional[int] = None,
        position_context: Optional[Dict[str, Any]] = None,
    ) -> LLMAnalysisResult:
        interval = interval or self.config.default_interval
        limit = min(
            max(limit or self.config.default_limit, self.config.min_candles),
            self.config.max_candles,
        )
        ticker, klines = await self._fetch_market_data(exchange, symbol, interval, limit)
        return await self.analyze_raw(
            ticker=ticker,
            klines=klines,
            symbol=symbol,
            interval=interval,
            position_context=position_context,
        )

    async def analyze_raw(
        self,
        ticker: Dict[str, Any],
        klines: List[Dict[str, Any]],
        symbol: str,
        interval: str,
        position_context: Optional[Dict[str, Any]] = None,
    ) -> LLMAnalysisResult:
        position_signature = self._position_signature(position_context)
        last_candle = klines[-1] if klines else {}
        cache_key = LLMFingerprintCache.fingerprint(
            symbol=symbol,
            interval=interval,
            last_candle=last_candle,
            position_signature=position_signature,
            prompt_version=self.config.prompt_version,
        )
        cached = self._cache.get(cache_key)
        if cached is not None and cached.is_ok:
            return self._translate(cached, symbol, interval, len(klines), cache_hit=True)

        prompt = self._build_prompt(symbol, interval, ticker, klines, position_context)
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
        if response.is_ok:
            self._cache.put(cache_key, response)
        return self._translate(response, symbol, interval, len(klines), cache_hit=False)

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
        ticker: Dict[str, Any],
        klines: List[Dict[str, Any]],
        position_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        candle_data = self._render_klines_compact(klines)
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
            candle_data=candle_data,
        )

    # ── Compact K-line encoding ──────────────────────────────────

    @staticmethod
    def _kline_summary(klines: List[Dict[str, Any]]) -> Dict[str, float]:
        """Aggregate stats - gives the LLM orientation in 1 line."""
        if not klines:
            return {"count": 0}
        ordered = sorted(klines, key=lambda k: k.get("open_time", ""))
        closes = [float(k.get("close", 0)) for k in ordered]
        highs = [float(k.get("high", 0)) for k in ordered]
        lows = [float(k.get("low", 0)) for k in ordered]
        n = len(ordered)
        # Average True Range (rough)
        trs = []
        for k in ordered:
            tr = max(
                float(k.get("high", 0)) - float(k.get("low", 0)),
                abs(float(k.get("high", 0)) - float(k.get("close", 0))),
                abs(float(k.get("low", 0)) - float(k.get("close", 0))),
            )
            trs.append(tr)
        return {
            "count": n,
            "first_close": closes[0],
            "last_close": closes[-1],
            "max_high": max(highs),
            "min_low": min(lows),
            "atr": sum(trs) / n if n else 0.0,
        }

    def _render_klines_compact(self, klines: List[Dict[str, Any]]) -> str:
        """Render K-lines as compact text.

        Output format (newest first):
          #K n=30 first=100.5 last=129.5 hi=130.0 lo=99.0 atr=2.0
          06-26-14:00 o:129 h:130 l:128 c:129.5 v:39.0
          ...

        Summary header + up to max_compact_rows body lines. Roughly half the
        size of the old aligned-table format.
        """
        if not klines:
            return ""
        ordered = sorted(klines, key=lambda k: k.get("open_time", ""), reverse=True)
        rows = ordered[: self.config.max_compact_rows]
        summary = self._kline_summary(klines)
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
    def _position_signature(position_context: Optional[Dict[str, Any]]) -> str:
        if not position_context:
            return "none"
        side = position_context.get("side", "")
        qty = position_context.get("quantity", 0)
        avg = position_context.get("avg_entry_price", 0)
        return f"{side}:{qty}:{avg}"

    @staticmethod
    def _translate(
        response: LLMResponse,
        symbol: str,
        interval: str,
        candle_count: int,
        cache_hit: bool,
    ) -> LLMAnalysisResult:
        now = datetime.utcnow().isoformat()
        if response.is_failed:
            err = response.failed
            return LLMAnalysisResult(
                decision="hold",
                confidence=0.0,
                reason=f"[{err.kind.value}] {err.message}",
                risk_level="high",
                risk_note="API 异常" if err.kind != LLMErrorKind.API_KEY_MISSING else "未配置",
                analyzed_symbol=symbol,
                analyzed_interval=interval,
                candle_count=candle_count,
                analysis_time=now,
                error_kind=err.kind.value,
            )
        d = response.decided
        return LLMAnalysisResult(
            decision=d.decision,
            confidence=d.confidence,
            reason=d.reason,
            stop_loss=d.stop_loss,
            take_profit=d.take_profit,
            risk_level=d.risk_level,
            risk_note=d.risk_note,
            analyzed_symbol=symbol,
            analyzed_interval=interval,
            candle_count=candle_count,
            model=d.model,
            analysis_time=now,
            raw_response=d.raw_response,
            cache_hit=cache_hit,
        )

    async def close(self) -> None:
        await self._provider._client_aclose() if hasattr(self._provider, "_client_aclose") else None


# Re-export for backward compatibility with `from app.strategies.llm_analyzer import LLMAnalyzer`
__all__ = ["LLMAnalyzer", "LLMAnalyzerConfig", "LLMAnalysisResult", "PROMPT_TEMPLATE"]