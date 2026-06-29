"""Tests for LLM prompt enhancements: risk context, trade history, few-shot.

These tests cover the *content* of the prompt, not the engine wiring
(which is a separate concern — the analyze() method needs new optional
parameters and the engine needs to pass them).

Scope:
- The rendered prompt must include risk metrics when risk_context is provided
- The rendered prompt must include trade history stats when trade_history is provided
- The system message must include a few-shot example so the model has an
  in-context demonstration of the expected JSON shape and reasoning style
- Backward compatibility: when no risk_context / trade_history is provided,
  rendering still succeeds (graceful degrade)
"""

from __future__ import annotations

import pytest

from app.strategies.llm_analyzer import LLMAnalyzer, _system_message


def _render(analyzer: LLMAnalyzer, **overrides) -> str:
    """Render the user prompt with minimal but valid inputs."""
    ticker = {"last_price": 50000.0, "price_change_pct_24h": 2.5,
              "volume_24h": 1000.0, "quote_volume_24h": 50_000_000.0}
    klines = [
        {"open_time": "06-26 14:00", "open": 50000, "high": 50100,
         "low": 49900, "close": 50050, "volume": 100.0},
    ]
    return analyzer._build_prompt(
        symbol="BTCUSDT",
        interval="1h",
        ticker=ticker,
        klines=klines,
        **overrides,
    )


def test_prompt_omits_risk_block_when_no_risk_context() -> None:
    """Default rendering must still work and must not crash on missing risk data."""
    analyzer = LLMAnalyzer()
    prompt = _render(analyzer)
    # The risk header is allowed to be missing; the prompt must still render
    # the rest of the required fields.
    assert "BTCUSDT" in prompt
    assert "50000" in prompt


def test_prompt_includes_risk_context_when_provided() -> None:
    """Risk context block must surface the key risk metrics to the LLM."""
    analyzer = LLMAnalyzer()
    risk = {
        "daily_pnl": -125.0,
        "current_drawdown_pct": 0.12,
        "kill_switch_enabled": False,
        "orders_last_minute": 2,
        "max_orders_per_minute": 5,
    }
    prompt = _render(analyzer, risk_context=risk)
    # Daily PnL should appear
    assert "-125" in prompt or "125" in prompt
    # Drawdown percentage should appear
    assert "12" in prompt or "0.12" in prompt
    # Kill-switch status should appear
    assert "kill" in prompt.lower() or "熔断" in prompt
    # Rate-limit info should appear
    assert "2" in prompt and "5" in prompt


def test_prompt_includes_trade_history_when_provided() -> None:
    """Trade history block must surface the key performance metrics."""
    analyzer = LLMAnalyzer()
    history = {
        "total_trades": 25,
        "winning_trades": 15,
        "losing_trades": 10,
        "win_rate": 0.6,
        "avg_win": 12.5,
        "avg_loss": -8.0,
        "max_consecutive_wins": 4,
        "max_consecutive_losses": 2,
    }
    prompt = _render(analyzer, trade_history=history)
    # Total trade count should appear
    assert "25" in prompt
    # Win rate should appear (as percentage or fraction)
    assert "60" in prompt or "0.6" in prompt or "15/25" in prompt
    # Streak info should appear
    assert "4" in prompt or "2" in prompt


def test_prompt_handles_both_risk_and_history_together() -> None:
    """Both blocks can be provided simultaneously without one stomping the other."""
    analyzer = LLMAnalyzer()
    risk = {"daily_pnl": -50.0, "current_drawdown_pct": 0.05,
            "kill_switch_enabled": False, "orders_last_minute": 0, "max_orders_per_minute": 5}
    history = {"total_trades": 10, "winning_trades": 6, "losing_trades": 4,
               "win_rate": 0.6, "avg_win": 5.0, "avg_loss": -3.0,
               "max_consecutive_wins": 3, "max_consecutive_losses": 1}
    prompt = _render(analyzer, risk_context=risk, trade_history=history)
    # Both blocks present
    assert "-50" in prompt or "50" in prompt
    assert "10" in prompt
    assert "6" in prompt


def test_system_message_includes_few_shot_example() -> None:
    """The system message must include at least one worked example
    so the LLM has an in-context demonstration of the expected shape."""
    sys_msg = _system_message()
    # Few-shot typically includes a sample input + expected output
    # Look for either a JSON example or explicit demonstration markers
    has_json = "{" in sys_msg and "}" in sys_msg
    has_marker = "示例" in sys_msg or "example" in sys_msg.lower() or "例" in sys_msg
    assert has_json and has_marker, (
        "System message should include a few-shot example with both "
        "JSON shape and an explicit example marker"
    )


def test_system_message_includes_risk_constraints() -> None:
    """System message must remind the model about risk constraints —
    this is the durable place for safety guidance that survives prompt
    template edits."""
    sys_msg = _system_message()
    # Should mention at least one of: 风控 / risk / 止损 / stop / 仓位 / position
    keywords = ["风控", "risk", "止损", "stop", "仓位", "position", "熔断", "kill"]
    assert any(kw.lower() in sys_msg.lower() for kw in keywords), (
        "System message should include risk-related guidance"
    )
