"""
大模型分析模块

人工辅助模式 — 不自动交易。
调用 OpenAI 兼容 API 进行市场分析，返回结构化开单建议。
支持任意兼容 OpenAI Chat Completions 的 API（OpenAI / Claude / DeepSeek / Ollama / vLLM）。
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx

from app.exchanges.base import ExchangeBase


# ── 配置 ────────────────────────────────────────────────────


@dataclass
class LLMAnalyzerConfig:
    """大模型分析器配置

    所有字段均有默认值，可从 env / settings 覆盖。
    """

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 2048
    request_timeout: float = 30.0

    # 分析参数
    min_candles: int = 20
    max_candles: int = 100
    default_interval: str = "1h"
    default_limit: int = 30


# ── 分析结果模型 ────────────────────────────────────────────


@dataclass
class LLMAnalysisResult:
    """大模型分析返回的结构化结果。"""

    # 核心决策
    decision: str  # "buy" | "sell" | "hold"
    confidence: float  # 0.0 ~ 1.0
    reason: str  # 分析推理摘要

    # 建议参数（decision=hold 时可为 None）
    suggested_action: Optional[str] = None  # "open_long" | "close_long" | "open_short" | "close_short"
    suggested_quantity: Optional[float] = None
    suggested_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    # 风险评估
    risk_level: str = "medium"  # "low" | "medium" | "high"
    risk_note: str = ""

    # 元信息
    analyzed_symbol: str = ""
    analyzed_interval: str = ""
    candle_count: int = 0
    model: str = ""
    analysis_time: str = ""
    raw_response: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {}
        for k, v in asdict(self).items():
            if isinstance(v, Decimal):
                v = float(v)
            result[k] = v
        return result


# ── Prompt 模板 ─────────────────────────────────────────────


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


# ── LLM 分析器 ──────────────────────────────────────────────


class LLMAnalyzer:
    """大模型分析器

    用法::

        analyzer = LLMAnalyzer(config)
        result = await analyzer.analyze(exchange, "BTCUSDT", interval="1h", limit=30)
        print(result.decision, result.reason)
    """

    def __init__(self, config: Optional[LLMAnalyzerConfig] = None):
        self.config = config or LLMAnalyzerConfig()
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.config.request_timeout)
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── 公共方法 ──────────────────────────────────────────────

    async def analyze(
        self,
        exchange: ExchangeBase,
        symbol: str,
        interval: Optional[str] = None,
        limit: Optional[int] = None,
        position_context: Optional[Dict[str, Any]] = None,
    ) -> LLMAnalysisResult:
        """执行一次大模型分析。

        Args:
            exchange: 交易所实例
            symbol: 交易对
            interval: K 线周期，默认 config.default_interval
            limit: K 线数量，默认 config.default_limit
            position_context: 可选持仓上下文

        Returns:
            LLMAnalysisResult
        """

        interval = interval or self.config.default_interval
        limit = min(
            max(limit or self.config.default_limit, self.config.min_candles),
            self.config.max_candles,
        )

        # 1) 获取市场数据
        ticker, klines = await self._fetch_market_data(exchange, symbol, interval, limit)

        # 2) 构建 Prompt
        prompt = self._build_prompt(symbol, interval, ticker, klines, position_context)

        # 3) 调用 LLM
        raw = await self._call_llm(prompt)

        # 4) 解析结果
        result = self._parse_response(raw, symbol, interval, limit)
        return result

    async def analyze_raw(
        self,
        ticker: Dict[str, Any],
        klines: List[Dict[str, Any]],
        symbol: str,
        interval: str,
        position_context: Optional[Dict[str, Any]] = None,
    ) -> LLMAnalysisResult:
        """使用已经获取的市场数据进行分析（避免重复请求交易所）。"""

        prompt = self._build_prompt(symbol, interval, ticker, klines, position_context)
        raw = await self._call_llm(prompt)
        return self._parse_response(raw, symbol, interval, len(klines))

    # ── 数据获取 ──────────────────────────────────────────────

    async def _fetch_market_data(
        self,
        exchange: ExchangeBase,
        symbol: str,
        interval: str,
        limit: int,
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """同时获取 ticker + klines。"""

        import asyncio

        ticker_task = exchange.get_ticker(symbol)
        klines_task = exchange.get_klines(symbol, interval=interval, limit=limit)

        ticker, klines = await asyncio.gather(ticker_task, klines_task)
        return ticker, klines

    # ── Prompt 构建 ────────────────────────────────────────────

    def _build_prompt(
        self,
        symbol: str,
        interval: str,
        ticker: Dict[str, Any],
        klines: List[Dict[str, Any]],
        position_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """组装发送给 LLM 的 Prompt。"""

        # 格式化 K 线数据
        candle_lines = ["open_time    open      high      low       close     volume"]
        for k in sorted(klines, key=lambda x: x.get("open_time", ""), reverse=True)[:self.config.max_candles]:
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

        # 持仓上下文
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

        # 当前价格
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

    # ── LLM 调用 ──────────────────────────────────────────────

    async def _call_llm(self, prompt: str) -> str:
        """调用 OpenAI 兼容 API 并返回原始响应文本。"""

        if not self.config.api_key:
            return json.dumps({
                "decision": "hold",
                "confidence": 0.0,
                "reason": "未配置 API Key。请设置 LLM_API_KEY 环境变量。",
                "risk_level": "medium",
                "risk_note": "分析不可用",
            })

        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一位专业的加密货币永续合约交易分析师。请根据市场数据给出交易建议。"
                    "只输出 JSON，不要包含其他文字。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
        }

        try:
            response = await client.post(
                f"{self.config.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()
        except httpx.HTTPStatusError as exc:
            error_body = ""
            try:
                error_body = exc.response.text
            except Exception:
                pass
            return json.dumps({
                "decision": "hold",
                "confidence": 0.0,
                "reason": f"LLM API 调用失败: {exc.response.status_code} {error_body[:200]}",
                "risk_level": "high",
                "risk_note": "API 不可用",
            })
        except Exception as exc:
            return json.dumps({
                "decision": "hold",
                "confidence": 0.0,
                "reason": f"LLM API 调用异常: {exc}",
                "risk_level": "high",
                "risk_note": "API 不可用",
            })

    # ── 响应解析 ──────────────────────────────────────────────

    def _parse_response(
        self,
        raw: str,
        symbol: str,
        interval: str,
        candle_count: int,
    ) -> LLMAnalysisResult:
        """解析 LLM 返回的 JSON 字符串为结构化结果。"""

        now = datetime.utcnow().isoformat()

        # 尝试解析 JSON
        data: Dict[str, Any] = {}
        try:
            # 处理可能被 Markdown 代码块包裹的情况
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                # 移除 ```json ... ``` 包裹
                cleaned = cleaned.split("\n", 1)[-1]
                cleaned = cleaned.rsplit("\n```", 1)[0]
                cleaned = cleaned.strip()
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return LLMAnalysisResult(
                decision="hold",
                confidence=0.0,
                reason=f"LLM 返回格式异常，无法解析: {raw[:300]}",
                risk_level="high",
                risk_note="解析失败",
                analyzed_symbol=symbol,
                analyzed_interval=interval,
                candle_count=candle_count,
                model=self.config.model,
                analysis_time=now,
                raw_response=raw,
            )

        decision = str(data.get("decision", "hold")).lower()
        if decision not in ("buy", "sell", "hold"):
            decision = "hold"

        action = data.get("suggested_action")
        if action and str(action).lower() == "null":
            action = None

        quantity = self._safe_float(data.get("suggested_quantity"))
        price = self._safe_float(data.get("suggested_price"))
        sl = self._safe_float(data.get("stop_loss"))
        tp = self._safe_float(data.get("take_profit"))

        return LLMAnalysisResult(
            decision=decision,
            confidence=min(max(float(data.get("confidence", 0.5)), 0.0), 1.0),
            reason=str(data.get("reason", "")),
            suggested_action=action,
            suggested_quantity=quantity,
            suggested_price=price,
            stop_loss=sl,
            take_profit=tp,
            risk_level=str(data.get("risk_level", "medium")).lower(),
            risk_note=str(data.get("risk_note", "")),
            analyzed_symbol=symbol,
            analyzed_interval=interval,
            candle_count=candle_count,
            model=self.config.model,
            analysis_time=now,
            raw_response=raw,
        )

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            v = float(value)
            if v <= 0 or v != v:  # NaN or non-positive
                return None
            return v
        except (ValueError, TypeError):
            return None
