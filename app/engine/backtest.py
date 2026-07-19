"""SMA crossover backtest with conservative execution assumptions.

The engine is deliberately deterministic and side-effect free.  Signals are
computed after a candle closes, then filled at the *next* candle's open.  This
avoids using a price that was not available when the decision was made.  Entry
and exit prices also include configurable taker fees and adverse slippage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from app.engine.simulation import (
    AccountSnapshot,
    EventDrivenSimulationEngine,
    ExecutionModelConfig,
    MarketEvent,
    RiskModelConfig,
    SignalEvent,
    SimulationConfig,
)


@dataclass(frozen=True)
class BacktestTrade:
    """One completed long trade produced by the backtest."""

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


@dataclass(frozen=True)
class BacktestFill:
    """One simulated order fill, including partial-fill information."""

    order_id: str
    index: int
    time: Any | None
    side: str
    requested_quantity: float
    filled_quantity: float
    price: float
    fee: float
    remaining_quantity: float
    status: str
    reason: str


@dataclass
class BacktestResult:
    initial_capital: float
    final_equity: float
    total_pnl: float
    trades: int
    win_rate: float  # 0.0 - 1.0
    max_drawdown: float  # 0.0 - 1.0
    equity_curve: list[float] = field(default_factory=list)
    total_fees: float = 0.0
    gross_pnl: float = 0.0
    total_return_pct: float = 0.0
    profit_factor: float | None = None
    trade_history: list[BacktestTrade] = field(default_factory=list)
    fill_history: list[BacktestFill] = field(default_factory=list)


@dataclass(frozen=True)
class PortfolioStrategyConfig:
    """One independently funded SMA strategy in a portfolio experiment."""

    name: str
    short_window: int
    long_window: int
    weight: float


@dataclass(frozen=True)
class PortfolioStrategyResult:
    """The capital allocation and result for one portfolio strategy."""

    name: str
    weight: float
    allocated_capital: float
    result: BacktestResult


@dataclass
class PortfolioBacktestResult:
    """Aggregate of independent strategy backtests on the same candle timeline."""

    initial_capital: float
    final_equity: float
    total_pnl: float
    trades: int
    win_rate: float
    max_drawdown: float
    equity_curve: list[float] = field(default_factory=list)
    total_fees: float = 0.0
    gross_pnl: float = 0.0
    total_return_pct: float = 0.0
    profit_factor: float | None = None
    strategies: list[PortfolioStrategyResult] = field(default_factory=list)


def _sma(values: list[float], window: int) -> list[float]:
    """Simple moving average; first ``window - 1`` values are zero."""
    out: list[float] = []
    total = 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        out.append(total / window if i + 1 >= window else 0.0)
    return out


def _price(candle: dict[str, Any], key: str, index: int) -> float:
    """Return a finite, positive OHLC value with a useful validation error."""
    try:
        value = float(candle[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"candle {index} has invalid {key!r} price") from exc
    if not isfinite(value) or value <= 0:
        raise ValueError(f"candle {index} has invalid {key!r} price")
    return value


def _validate_inputs(
    candles: list[dict[str, Any]],
    short_window: int,
    long_window: int,
    initial_capital: float,
    position_size_pct: float,
    fee_rate: float,
    slippage_rate: float,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
) -> None:
    if short_window <= 0 or long_window <= 0 or short_window >= long_window:
        raise ValueError("short_window must be positive and smaller than long_window")
    if not isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    if not 0 < position_size_pct <= 1:
        raise ValueError("position_size_pct must be between 0 (exclusive) and 1")
    for name, value in (("fee_rate", fee_rate), ("slippage_rate", slippage_rate)):
        if not isfinite(value) or not 0 <= value < 1:
            raise ValueError(f"{name} must be between 0 and 1")
    for risk_name, risk_value in (
        ("stop_loss_pct", stop_loss_pct),
        ("take_profit_pct", take_profit_pct),
    ):
        if risk_value is not None and (not isfinite(risk_value) or not 0 < risk_value < 1):
            raise ValueError(f"{risk_name} must be between 0 (exclusive) and 1")
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict):
            raise ValueError(f"candle {index} must be an object")
        low = _price(candle, "low", index)
        high = _price(candle, "high", index)
        open_price = _price(candle, "open", index)
        close = _price(candle, "close", index)
        if low > high or not low <= open_price <= high or not low <= close <= high:
            raise ValueError(f"candle {index} has inconsistent OHLC prices")


def run_sma_backtest(
    candles: list[dict[str, Any]],
    short_window: int = 5,
    long_window: int = 20,
    initial_capital: float = 10_000.0,
    position_size_pct: float = 1.0,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    max_volume_participation: float | None = None,
) -> BacktestResult:
    """Run a long-only SMA crossover through the shared simulation engine.

    A cross detected on candle ``i`` creates an order for candle ``i + 1``'s
    open. Optional stop loss and take profit triggers inspect each candle's
    high/low after entry. When both triggers are reachable in the same candle,
    the stop loss wins as the conservative assumption.

    ``max_volume_participation`` can cap fills to a fraction of candle volume.
    It is disabled by default so existing callers retain their historical
    behavior while the shared engine can model partial fills when requested.
    """
    _validate_inputs(
        candles,
        short_window,
        long_window,
        initial_capital,
        position_size_pct,
        fee_rate,
        slippage_rate,
        stop_loss_pct,
        take_profit_pct,
    )

    execution = ExecutionModelConfig(
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        max_volume_participation=max_volume_participation,
    )
    config = SimulationConfig(
        initial_capital=initial_capital,
        position_size_pct=position_size_pct,
        execution=execution,
        risk=RiskModelConfig(
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        ),
    )

    closes = [_price(candle, "close", index) for index, candle in enumerate(candles)]
    candle_count = len(closes)
    if candle_count < long_window + 1:
        return BacktestResult(
            initial_capital=initial_capital,
            final_equity=initial_capital,
            total_pnl=0.0,
            trades=0,
            win_rate=0.0,
            max_drawdown=0.0,
            equity_curve=[initial_capital] * candle_count,
        )

    markets = [
        MarketEvent(
            index=index,
            time=candle.get("open_time"),
            open=_price(candle, "open", index),
            high=_price(candle, "high", index),
            low=_price(candle, "low", index),
            close=closes[index],
            volume=_volume(candle),
        )
        for index, candle in enumerate(candles)
    ]
    short_sma = _sma(closes, short_window)
    long_sma = _sma(closes, long_window)

    def sma_signal_model(
        market_events: Sequence[MarketEvent],
        index: int,
        account: AccountSnapshot,
    ) -> SignalEvent | None:
        if index < long_window:
            return None
        in_long = short_sma[index] > long_sma[index]
        was_in_long = short_sma[index - 1] > long_sma[index - 1]
        if in_long and not was_in_long and account.position_quantity <= 1e-12:
            return SignalEvent(
                index=index,
                time=market_events[index].time,
                action="enter",
                reason="signal",
            )
        if not in_long and account.position_quantity > 1e-12:
            return SignalEvent(
                index=index,
                time=market_events[index].time,
                action="exit",
                reason="signal",
            )
        return None

    simulation = EventDrivenSimulationEngine(config).run(markets, sma_signal_model)
    gross_pnl = sum(trade.gross_pnl for trade in simulation.trades)
    total_fees = sum(trade.fees for trade in simulation.trades)
    net_pnls = [trade.net_pnl for trade in simulation.trades]
    wins = sum(1 for pnl in net_pnls if pnl > 0)
    losses = -sum(pnl for pnl in net_pnls if pnl < 0)
    gains = sum(pnl for pnl in net_pnls if pnl > 0)
    profit_factor = round(gains / losses, 4) if losses > 0 else None
    final_equity = simulation.final_equity

    return BacktestResult(
        initial_capital=round(initial_capital, 4),
        final_equity=round(final_equity, 4),
        total_pnl=round(final_equity - initial_capital, 4),
        trades=len(simulation.trades),
        win_rate=round(wins / len(simulation.trades), 4) if simulation.trades else 0.0,
        max_drawdown=round(simulation.max_drawdown, 4),
        equity_curve=[round(value, 4) for value in simulation.equity_curve],
        total_fees=round(total_fees, 4),
        gross_pnl=round(gross_pnl, 4),
        total_return_pct=round((final_equity / initial_capital - 1) * 100, 4),
        profit_factor=profit_factor,
        trade_history=[
            BacktestTrade(
                entry_index=trade.entry_index,
                exit_index=trade.exit_index,
                entry_time=trade.entry_time,
                exit_time=trade.exit_time,
                quantity=round(trade.quantity, 8),
                entry_price=round(trade.entry_price, 8),
                exit_price=round(trade.exit_price, 8),
                gross_pnl=round(trade.gross_pnl, 4),
                fees=round(trade.fees, 4),
                net_pnl=round(trade.net_pnl, 4),
                exit_reason=trade.exit_reason,
            )
            for trade in simulation.trades
        ],
        fill_history=[
            BacktestFill(
                order_id=fill.order_id,
                index=fill.index,
                time=fill.time,
                side=fill.side.value,
                requested_quantity=round(fill.requested_quantity, 8),
                filled_quantity=round(fill.filled_quantity, 8),
                price=round(fill.price, 8),
                fee=round(fill.fee, 4),
                remaining_quantity=round(fill.remaining_quantity, 8),
                status=fill.status.value,
                reason=fill.reason,
            )
            for fill in simulation.fills
        ],
    )


def run_multi_sma_backtest(
    candles: list[dict[str, Any]],
    strategies: Sequence[PortfolioStrategyConfig],
    initial_capital: float = 10_000.0,
    position_size_pct: float = 1.0,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0,
    max_volume_participation: float | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> PortfolioBacktestResult:
    """Backtest explicitly weighted SMA strategies and aggregate their equity.

    Each strategy receives only ``initial_capital * weight`` and is simulated
    independently.  The combined curve is the point-in-time sum of those
    independently funded curves; it does not share cash or rebalance between
    strategies.  This makes allocation and attribution deterministic.
    """

    if not strategies:
        raise ValueError("at least one portfolio strategy is required")
    if not isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial_capital must be positive")

    names: set[str] = set()
    total_weight = 0.0
    for strategy in strategies:
        name = strategy.name.strip()
        if not name:
            raise ValueError("portfolio strategy name must not be empty")
        normalized_name = name.casefold()
        if normalized_name in names:
            raise ValueError(f"duplicate portfolio strategy name: {name}")
        names.add(normalized_name)
        if not isfinite(strategy.weight) or strategy.weight <= 0:
            raise ValueError("portfolio strategy weights must be positive")
        total_weight += strategy.weight

    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError("portfolio strategy weights must sum to 1.0")

    strategy_results: list[PortfolioStrategyResult] = []
    for strategy in strategies:
        allocated_capital = initial_capital * strategy.weight
        result = run_sma_backtest(
            candles=candles,
            short_window=strategy.short_window,
            long_window=strategy.long_window,
            initial_capital=allocated_capital,
            position_size_pct=position_size_pct,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
            max_volume_participation=max_volume_participation,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )
        strategy_results.append(
            PortfolioStrategyResult(
                name=strategy.name.strip(),
                weight=strategy.weight,
                allocated_capital=round(allocated_capital, 4),
                result=result,
            )
        )

    curve_lengths = {len(item.result.equity_curve) for item in strategy_results}
    if len(curve_lengths) > 1:
        raise ValueError("portfolio strategy equity curves must share a timeline")
    curve_length = curve_lengths.pop() if curve_lengths else 0
    equity_curve = [
        round(sum(item.result.equity_curve[index] for item in strategy_results), 4)
        for index in range(curve_length)
    ]
    final_equity = sum(item.result.final_equity for item in strategy_results)
    total_fees = sum(item.result.total_fees for item in strategy_results)
    gross_pnl = sum(item.result.gross_pnl for item in strategy_results)
    all_trades = [trade for item in strategy_results for trade in item.result.trade_history]
    gains = sum(trade.net_pnl for trade in all_trades if trade.net_pnl > 0)
    losses = -sum(trade.net_pnl for trade in all_trades if trade.net_pnl < 0)
    wins = sum(1 for trade in all_trades if trade.net_pnl > 0)
    peak = initial_capital
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    return PortfolioBacktestResult(
        initial_capital=round(initial_capital, 4),
        final_equity=round(final_equity, 4),
        total_pnl=round(final_equity - initial_capital, 4),
        trades=len(all_trades),
        win_rate=round(wins / len(all_trades), 4) if all_trades else 0.0,
        max_drawdown=round(max_drawdown, 4),
        equity_curve=equity_curve,
        total_fees=round(total_fees, 4),
        gross_pnl=round(gross_pnl, 4),
        total_return_pct=round((final_equity / initial_capital - 1) * 100, 4),
        profit_factor=round(gains / losses, 4) if losses > 0 else None,
        strategies=strategy_results,
    )


def _volume(candle: dict[str, Any]) -> float | None:
    raw_volume = candle.get("volume")
    if raw_volume is None:
        return None
    try:
        volume = float(raw_volume)
    except (TypeError, ValueError):
        return None
    return volume if isfinite(volume) and volume >= 0 else None


__all__ = [
    "BacktestFill",
    "BacktestResult",
    "BacktestTrade",
    "PortfolioBacktestResult",
    "PortfolioStrategyConfig",
    "PortfolioStrategyResult",
    "run_multi_sma_backtest",
    "run_sma_backtest",
]
