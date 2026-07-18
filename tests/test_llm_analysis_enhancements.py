from __future__ import annotations

from app.engine.llm_cache import LLMFingerprintCache
from app.engine.llm_decision_parser import parse_llm_decision
from app.engine.llm_types import LLMDecided, LLMResponse
from app.strategies.llm_analyzer import LLMAnalyzer


def _trend_klines(count: int = 30) -> list[dict[str, float | str]]:
    return [
        {
            "open_time": f"2026-07-{index + 1:02d} 00:00",
            "open": 100 + index,
            "high": 102 + index,
            "low": 99 + index,
            "close": 101 + index,
            "volume": 100 + index * 5,
        }
        for index in range(count)
    ]


def test_structured_parser_preserves_full_analysis() -> None:
    decision = parse_llm_decision(
        '''{
          "trend": "bullish",
          "volatility": "high",
          "summary": "趋势与量能共振",
          "key_support": 98,
          "key_resistance": 135,
          "decision": "buy",
          "confidence": 0.82,
          "entry_zone": "128-130",
          "stop_loss": 124,
          "take_profit": 140,
          "position_pct": 0.25,
          "bullish_factors": ["SMA5 高于 SMA20", "量比放大"],
          "bearish_factors": ["RSI 偏高"],
          "invalidation_condition": "跌破 124",
          "reason": "多项证据同向",
          "risk_level": "medium",
          "risk_note": "防范冲高回落"
        }''',
        "test-model",
    )

    assert decision.trend == "bullish"
    assert decision.volatility == "high"
    assert decision.summary == "趋势与量能共振"
    assert decision.key_support == 98
    assert decision.key_resistance == 135
    assert decision.entry_zone == "128-130"
    assert decision.position_pct == 0.25
    assert decision.bullish_factors == ("SMA5 高于 SMA20", "量比放大")
    assert decision.bearish_factors == ("RSI 偏高",)
    assert decision.invalidation_condition == "跌破 124"


def test_technical_snapshot_cross_checks_trend_momentum_and_volume() -> None:
    snapshot = LLMAnalyzer._technical_snapshot(_trend_klines())

    assert snapshot["data_quality"] == "sufficient"
    assert snapshot["trend_bias"] == "bullish"
    assert snapshot["sma_5"] > snapshot["sma_20"]
    assert snapshot["momentum_20_pct"] > 0
    assert snapshot["volume_ratio"] > 1
    assert 0 <= snapshot["rsi_14"] <= 100
    assert snapshot["support_20"] < snapshot["resistance_20"]


def test_prompt_contains_deterministic_technical_snapshot() -> None:
    analyzer = LLMAnalyzer()
    prompt = analyzer._build_prompt(
        symbol="BTCUSDT",
        interval="1h",
        ticker={
            "last_price": 130,
            "price_change_pct_24h": 2.0,
            "volume_24h": 5000,
            "quote_volume_24h": 650000,
        },
        klines=_trend_klines(),
    )

    assert "引擎计算的技术指标" in prompt
    assert "SMA5 / SMA20" in prompt
    assert "RSI14" in prompt
    assert "20周期支撑 / 阻力" in prompt
    assert "bullish_factors" in prompt
    assert "invalidation_condition" in prompt


def test_cache_fingerprint_changes_when_risk_context_changes() -> None:
    common = dict(
        symbol="BTCUSDT",
        interval="1h",
        last_candle={"close": 130},
        position_signature="none",
        prompt_version="v3",
    )
    safe = LLMFingerprintCache.fingerprint(
        **common, context_signature={"risk": {"kill_switch_enabled": False}}
    )
    blocked = LLMFingerprintCache.fingerprint(
        **common, context_signature={"risk": {"kill_switch_enabled": True}}
    )

    assert safe != blocked


def test_translate_exposes_analysis_and_risk_reward_ratio() -> None:
    response = LLMResponse(
        decided=LLMDecided(
            decision="buy",
            confidence=0.8,
            reason="趋势确认",
            stop_loss=95,
            take_profit=115,
            trend="bullish",
            volatility="medium",
            summary="价格保持上行结构",
            key_support=96,
            key_resistance=114,
            entry_zone="99-101",
            position_pct=0.2,
            bullish_factors=("均线多头", "动量为正"),
            bearish_factors=("临近阻力",),
            invalidation_condition="跌破 95",
        )
    )

    result = LLMAnalyzer._translate(
        response,
        "BTCUSDT",
        "1h",
        30,
        False,
        current_price=100,
        technical_indicators={"rsi_14": 62.0},
    )

    assert result.summary == "价格保持上行结构"
    assert result.key_support == 96
    assert result.position_pct == 0.2
    assert result.risk_reward_ratio == 3.0
    assert result.technical_indicators == {"rsi_14": 62.0}


def test_translate_ignores_invalid_current_price() -> None:
    response = LLMResponse(
        decided=LLMDecided(decision="hold", confidence=0.4, reason="等待确认")
    )

    result = LLMAnalyzer._translate(
        response, "BTCUSDT", "1h", 30, False, current_price="not-a-price"
    )

    assert result.suggested_price is None
    assert result.risk_reward_ratio is None


def test_invalid_klines_are_excluded_from_snapshot_and_prompt_rows() -> None:
    analyzer = LLMAnalyzer()
    invalid = [
        {
            "open_time": "2026-07-18 00:00",
            "open": "nan",
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 10,
        }
    ]

    assert analyzer._technical_snapshot(invalid)["data_quality"] == "unavailable"
    assert analyzer._render_klines_compact(invalid) == ""


def test_parser_bounds_untrusted_text_fields() -> None:
    decision = parse_llm_decision(
        '{"decision":"hold","reason":"' + ("x" * 3000) + '","summary":"' + ("y" * 800) + '"}',
        "test-model",
    )

    assert len(decision.reason) == 2000
    assert len(decision.summary) == 500
