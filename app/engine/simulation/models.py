"""Configuration and result models for the deterministic simulation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from app.engine.simulation.events import FillEvent, SimulationEvent


@dataclass(frozen=True)
class ExecutionModelConfig:
    """Deterministic bar execution assumptions.

    ``max_volume_participation`` is disabled by default to preserve the legacy
    candle backtest behavior. Set it to a value in ``(0, 1]`` to cap each fill
    to that fraction of a candle's reported volume.
    """

    fee_rate: float = 0.001
    slippage_rate: float = 0.0
    max_volume_participation: float | None = None

    def __post_init__(self) -> None:
        for name, value in (("fee_rate", self.fee_rate), ("slippage_rate", self.slippage_rate)):
            if not isfinite(value) or not 0 <= value < 1:
                raise ValueError(f"{name} must be between 0 and 1")
        participation = self.max_volume_participation
        if participation is not None and (
            not isfinite(participation) or not 0 < participation <= 1
        ):
            raise ValueError("max_volume_participation must be between 0 (exclusive) and 1")


@dataclass(frozen=True)
class RiskModelConfig:
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("stop_loss_pct", self.stop_loss_pct),
            ("take_profit_pct", self.take_profit_pct),
        ):
            if value is not None and (not isfinite(value) or not 0 < value < 1):
                raise ValueError(f"{name} must be between 0 (exclusive) and 1")


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
