"""无人值守 Bot 的多周期趋势分析。

该模块只负责从已闭合的 1 小时 K 线得出可审计的候选动作；它不访问
交易所，也不提交订单。执行层必须额外通过 Bot 预算、统一风控、
Kill Switch、账户对账和实盘开关。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

TIMEFRAME_HOURS: dict[str, int] = {"1h": 1, "5h": 5, "24h": 24}
_VALID_ACTIONS = {"buy", "sell", "observe"}


@dataclass(frozen=True)
class TimeframeSignal:
    """一个观察窗口的趋势结果。"""

    timeframe: str
    return_pct: float | None
    action: str
    reason: str


@dataclass(frozen=True)
class AutopilotDecision:
    """多周期共识结果，可直接序列化到 API 或审计事件。"""

    decision_id: str
    action: str
    confidence: float
    price: float | None
    signals: tuple[TimeframeSignal, ...]
    reason: str
    signal_key: str
    analyzed_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signals"] = [asdict(signal) for signal in self.signals]
        return payload


def extract_closes(candles: Iterable[Mapping[str, Any]]) -> list[float]:
    """从统一行情适配器返回的 K 线中提取有效收盘价。"""

    closes: list[float] = []
    for candle in candles:
        try:
            close = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(close) and close > 0:
            closes.append(close)
    return closes


def analyze_multi_timeframe(
    candles: Iterable[Mapping[str, Any]],
    *,
    min_return_pct: float = 0.002,
    now: datetime | None = None,
) -> AutopilotDecision:
    """基于 1h / 5h / 24h 已闭合 K 线生成保守的趋势候选。

    ``min_return_pct`` 是每个窗口独立需要满足的最小绝对涨跌幅，例如
    ``0.002`` 表示 0.2%。任何窗口无足够数据、方向不同或波动不足都会
    返回 ``observe``；因此缺数据与异常路径不会产生自动订单。
    """

    if not math.isfinite(min_return_pct) or min_return_pct <= 0:
        raise ValueError("min_return_pct must be a positive finite number")

    closes = extract_closes(candles)
    signals: list[TimeframeSignal] = []
    for timeframe, hours in TIMEFRAME_HOURS.items():
        # 当前收盘价与 N 小时前收盘价比较，所以需要 N + 1 根 K 线。
        if len(closes) < hours + 1:
            signals.append(
                TimeframeSignal(
                    timeframe=timeframe,
                    return_pct=None,
                    action="observe",
                    reason=f"insufficient_closed_candles: need {hours + 1}, got {len(closes)}",
                )
            )
            continue

        base = closes[-(hours + 1)]
        current = closes[-1]
        change = (current / base) - 1
        if change >= min_return_pct:
            action = "buy"
            reason = "uptrend_above_threshold"
        elif change <= -min_return_pct:
            action = "sell"
            reason = "downtrend_below_threshold"
        else:
            action = "observe"
            reason = "movement_below_threshold"
        signals.append(
            TimeframeSignal(
                timeframe=timeframe,
                return_pct=round(change, 8),
                action=action,
                reason=reason,
            )
        )

    actionable = [signal.action for signal in signals]
    if len(closes) >= 25 and len(set(actionable)) == 1 and actionable[0] in _VALID_ACTIONS - {"observe"}:
        action = actionable[0]
        returns = [abs(signal.return_pct or 0.0) for signal in signals]
        # 共识已经是硬门槛；置信度仅用于通知与审计，不用于扩大下单金额。
        confidence = round(min(0.99, 0.5 + min(returns) / (min_return_pct * 4)), 4)
        reason = "all_timeframes_aligned"
    else:
        action = "observe"
        confidence = 0.0
        if len(closes) < 25:
            reason = "insufficient_closed_candles_for_24h"
        elif any(signal.action == "observe" for signal in signals):
            reason = "at_least_one_timeframe_not_actionable"
        else:
            reason = "timeframes_disagree"

    price = closes[-1] if closes else None
    # This excludes the random decision ID and timestamp on purpose. It is the
    # stable identity of this exact closed-candle consensus, allowing the order
    # path to remain idempotent across scheduler retries and Bot restarts.
    signal_material = "|".join(
        [action, reason, f"{price:.12g}" if price is not None else "none"]
        + [
            f"{signal.timeframe}:{signal.action}:{signal.return_pct!r}"
            for signal in signals
        ]
    )
    signal_key = hashlib.sha256(signal_material.encode("utf-8")).hexdigest()[:32]
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    return AutopilotDecision(
        decision_id=f"bot-{uuid4().hex}",
        action=action,
        confidence=confidence,
        price=price,
        signals=tuple(signals),
        reason=reason,
        signal_key=signal_key,
        analyzed_at=timestamp,
    )


__all__ = [
    "AutopilotDecision",
    "TIMEFRAME_HOURS",
    "TimeframeSignal",
    "analyze_multi_timeframe",
    "extract_closes",
]
