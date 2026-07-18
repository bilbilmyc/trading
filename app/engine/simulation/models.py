"""Configuration and result models for the deterministic simulation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from app.engine.simulation.events import FillEvent, SimulationEvent


@dataclass(frozen=True)
class ExecutionModelConfig:
    """Deterministic bar execution assumptions.

    Depth and queue inputs are intentionally conservative synthetic-book
    controls. They make OHLCV backtests reproducible; they are not a claim to
    reconstruct a historical exchange order book without L2 data.
    """

    fee_rate: float = 0.001
    slippage_rate: float = 0.0
    max_volume_participation: float | None = None
    additional_latency_bars: int = 0
    volatile_slippage_multiplier: float = 1.5
    stressed_slippage_multiplier: float = 2.5
    queue_position_fraction: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (("fee_rate", self.fee_rate), ("slippage_rate", self.slippage_rate)):
            if not isfinite(value) or not 0 <= value < 1:
                raise ValueError(f"{name} must be between 0 and 1")
        participation = self.max_volume_participation
        if participation is not None and (
            not isfinite(participation) or not 0 < participation <= 1
        ):
            raise ValueError("max_volume_participation must be between 0 (exclusive) and 1")
        if not isinstance(self.additional_latency_bars, int) or self.additional_latency_bars < 0:
            raise ValueError("additional_latency_bars must be a non-negative integer")
        for name, value in (
            ("volatile_slippage_multiplier", self.volatile_slippage_multiplier),
            ("stressed_slippage_multiplier", self.stressed_slippage_multiplier),
        ):
            if not isfinite(value) or value < 1:
                raise ValueError(f"{name} must be at least 1")
        if not isfinite(self.queue_position_fraction) or not 0 <= self.queue_position_fraction < 1:
            raise ValueError("queue_position_fraction must be between 0 and 1")


@dataclass(frozen=True)
class RiskModelConfig:
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None
    trailing_activation_pct: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (
            ("stop_loss_pct", self.stop_loss_pct),
            ("take_profit_pct", self.take_profit_pct),
            ("trailing_stop_pct", self.trailing_stop_pct),
        ):
            if value is not None and (not isfinite(value) or not 0 < value < 1):
                raise ValueError(f"{name} must be between 0 (exclusive) and 1")
        if not isfinite(self.trailing_activation_pct) or not 0 <= self.trailing_activation_pct < 1:
            raise ValueError("trailing_activation_pct must be between 0 and 1")
        if self.trailing_stop_pct is None and self.trailing_activation_pct != 0:
            raise ValueError("trailing_activation_pct requires trailing_stop_pct")


@dataclass(frozen=True)
class SimulationConfig:
    initial_capital: float = 10_000.0
    position_size_pct: float = 1.0
    execution: ExecutionModelConfig = field(default_factory=ExecutionModelConfig)
    risk: RiskModelConfig = field(default_factory=RiskModelConfig)

    def __post_init__(self) -> None:
        if not isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if not isfinite(self.position_size_pct) or not 0 < self.position_size_pct <= 1:
            raise ValueError("position_size_pct must be between 0 (exclusive) and 1")


@dataclass
class SimulationPosition:
    quantity: float = 0.0
    entry_quantity: float = 0.0
    entry_price: float = 0.0
    entry_index: int = -1
    entry_time: Any | None = None
    entry_fee: float = 0.0
    exit_quantity: float = 0.0
    exit_notional: float = 0.0
    exit_fee: float = 0.0
    exit_reason: str | None = None

    @property
    def is_open(self) -> bool:
        return self.quantity > 1e-12


@dataclass(frozen=True)
class SimulationTrade:
    entry_index: int
    exit_index: int
    entry_time: Any | None
    exit_time: Any | None
    quantity: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    fees: float
    net_pnl: float
    exit_reason: str


@dataclass
class SimulationResult:
    initial_capital: float
    final_equity: float
    equity_curve: list[float]
    trades: list[SimulationTrade] = field(default_factory=list)
    fills: list[FillEvent] = field(default_factory=list)
    events: list[SimulationEvent] = field(default_factory=list)
    max_drawdown: float = 0.0


__all__ = [
    "ExecutionModelConfig",
    "RiskModelConfig",
    "SimulationConfig",
    "SimulationPosition",
    "SimulationResult",
    "SimulationTrade",
]
