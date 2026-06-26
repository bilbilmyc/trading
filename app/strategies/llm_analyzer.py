"""LLMAnalyzer v2 — uses OpenAIProvider + three-state result.

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
    prompt_version: str = "v1"


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


PROMPT_TEMPLATE = """你是一位专业的加密货币永续合约交易分析师。请根据以下市场数据给出交易建议。

## 交易规则
- 只交易 USDT 本位永续合约
- 严格风控：单笔最大亏损不超过账户权益的 2%
- 优先考虑趋势跟随，逆势开仓必须给出充分理由

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

### 最近 K 线数据（倒序，最新在前）
```
{candle_data}
```

## 输出要求

请严格按以下 JSON 格式输出，不要包含其他文字：

```json
{{
  "decision": "buy|sell|hold",
  "confidence": 0.0-1.0,
  "reason": "中文分析推理，200 字以内",
  "suggested_action": "open_long|close_long|open_short|close_short|null",
  "suggested_quantity": null 或数字,
  "suggested_price": null 或数字,
  "stop_loss": null 或数字,
  "take_profit": null 或数字,
  "risk_level": "low|medium|high",
  "risk_note": "风险提示，50 字以内"
}}
```
"""


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
        self._provider = provider or OpenAIProvider(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
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
        candle_lines = [
            "open_time    open      high      low       close     volume"
        ]
        for k in sorted(klines, key=lambda x: x.get("open_time", ""), reverse=True)[: self.config.max_candles]:
            ot = k.get("open_time", "")
            if isinstance(ot, datetime):
                ot = ot.strftime("%m-%d %H:%M")
            else:
                ot = str(ot)[-16:]
            candle_lines.append(
                f"{ot}  {float(k.get('open', 0)):>8.2f} {float(k.get('high', 0)):>8.2f} "
                f"{float(k.get('low', 0)):>8.2f} {float(k.get('close', 0)):>8.2f} "
                f"{float(k.get('volume', 0)):>10.4f}"
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
            candle_data="\n".join(candle_lines),
        )

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