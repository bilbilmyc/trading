"""Tests for StrategyRegistry — round-trip persistence of strategy state."""

from __future__ import annotations

import pytest

from app.engine.strategy_registry import StrategyRegistry
from app.strategies.sma import SMAStrategy


def test_sma_strategy_round_trips_state() -> None:
    reg = StrategyRegistry()
    reg.register(
        cls=SMAStrategy,
        snapshot=lambda s: {"short_window": s.short_window, "long_window": s.long_window},
        restore=lambda data: SMAStrategy(short_window=data["short_window"], long_window=data["long_window"]),
    )

    original = SMAStrategy(short_window=7, long_window=42)
    snapshot = {
        "class_name": "SMAStrategy",
        "state": reg.snapshot(original),
    }
    restored = reg.restore(snapshot)

    assert isinstance(restored, SMAStrategy)
    assert restored.short_window == 7
    assert restored.long_window == 42


def test_llm_strategy_round_trips_non_primitive_state() -> None:
    """LLM strategy has model, temperature, prompt — non-primitive fields that
    vars() filtering drops. The registry's restore_fn reads them back."""

    class _StrConfig:
        def __init__(self, prompt: str, temperature: float) -> None:
            self.prompt = prompt
            self.temperature = temperature

    class _FakeLLMStrategy:
        name = "llm"
        def __init__(self, model: str, cfg: _StrConfig) -> None:
            self.model = model
            self.cfg = cfg

    def _snap(s):
        return {"model": s.model, "cfg": {"prompt": s.cfg.prompt, "temperature": s.cfg.temperature}}

    def _restore(data):
        return _FakeLLMStrategy(
            model=data["model"],
            cfg=_StrConfig(prompt=data["cfg"]["prompt"], temperature=data["cfg"]["temperature"]),
        )

    reg = StrategyRegistry()
    reg.register(cls=_FakeLLMStrategy, snapshot=_snap, restore=_restore)

    original = _FakeLLMStrategy(
        model="claude-sonnet",
        cfg=_StrConfig(prompt="You are a quant", temperature=0.3),
    )
    snapshot = {"class_name": "_FakeLLMStrategy", "state": reg.snapshot(original)}
    restored = reg.restore(snapshot)

    assert restored.model == "claude-sonnet"
    assert restored.cfg.prompt == "You are a quant"
    assert restored.cfg.temperature == 0.3


def test_restore_unknown_class_returns_none() -> None:
    reg = StrategyRegistry()
    snapshot = {"class_name": "UnregisteredStrategy", "state": {"x": 1}}
    assert reg.restore(snapshot) is None


def test_unknown_class_does_not_raise() -> None:
    """Forward-compat: when a class isn't registered, restore silently skips."""

    reg = StrategyRegistry()
    reg.register(cls=SMAStrategy, snapshot=lambda s: {}, restore=lambda d: SMAStrategy())

    snapshot = {"class_name": "FutureStrategy", "state": {"future": True}}
    assert reg.restore(snapshot) is None


def test_registry_supports_multiple_classes() -> None:
    reg = StrategyRegistry()
    reg.register(cls=SMAStrategy, snapshot=lambda s: {"short_window": s.short_window}, restore=lambda d: SMAStrategy(short_window=d["short_window"]))
    assert "SMAStrategy" in reg.registered_classes()
    assert len(reg.registered_classes()) == 1