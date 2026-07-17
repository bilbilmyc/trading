"""SMA crossover backtest with conservative execution assumptions.

The engine is deliberately deterministic and side-effect free.  Signals are
computed after a candle closes, then filled at the *next* candle's open.  This
avoids using a price that was not available when the decision was made.  Entry
and exit prices also include configurable taker fees and adverse slippage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any


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
    for name, value in (("stop_loss_pct", stop_loss_pct), ("take_profit_pct", take_profit_pct)):
        if value is not None and (not isfinite(value) or not 0 < value < 1):
            raise ValueError(f"{name} must be between 0 (exclusive) and 1")
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict):
            raise ValueError(f"candle {index} must be an object")
        low = _price(candle, "low", index)
        high = _price(candle, "high", index)
        open_price = _price(candle, "open", index)
        close = _price(candle, "close", index)
        if low > high or not low <= open_price <= high or not low <= close <= high:
            raise ValueError(f"candle {index} has inconsistent OHLC prices")


def _apply_slippage(price: float, side: str, slippage_rate: float) -> float:
    """Apply adverse slippage: buys cost more and sells receive less."""
    return price * (1 + slippage_rate) if side == "buy" else price * (1 - slippage_rate)


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
) -> BacktestResult:
    """Run a long-only SMA crossover backtest with realistic execution costs.

    A cross detected on candle ``i`` creates an order for candle ``i + 1``'s
    open.  Optional stop loss and take profit triggers inspect each candle's
    high/low after entry.  When both triggers are reachable in the same candle,
    the stop loss wins as the conservative assumption.
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

    short_sma = _sma(closes, short_window)
    long_sma = _sma(closes, long_window)
    cash = initial_capital
    quantity = 0.0
    entry_price = 0.0
    entry_index = -1
    entry_time: Any | None = None
    entry_fee = 0.0
    pending_action: str | None = None
    equity_curve: list[float] = []
    trade_history: list[BacktestTrade] = []
    peak = initial_capital
    max_drawdown = 0.0

    def close_position(index: int, raw_price: float, reason: str) -> None:
        nonlocal cash, quantity, entry_price, entry_index, entry_time, entry_fee
        exit_price = _apply_slippage(raw_price, "sell", slippage_rate)
        exit_notional = quantity * exit_price
        exit_fee = exit_notional * fee_rate
        cash += exit_notional - exit_fee
        gross_pnl = (exit_price - entry_price) * quantity
        fees = entry_fee + exit_fee
        trade_history.append(
            BacktestTrade(
                entry_index=entry_index,
                exit_index=index,
                entry_time=entry_time,
                exit_time=candles[index].get("open_time"),
                quantity=quantity,
                entry_price=entry_price,
                exit_price=exit_price,
                gross_pnl=gross_pnl,
                fees=fees,
                net_pnl=gross_pnl - fees,
                exit_reason=reason,
            )
        )
        quantity = 0.0
        entry_price = 0.0
        entry_index = -1
        entry_time = None
        entry_fee = 0.0

    for index, candle in enumerate(candles):
        open_price = _price(candle, "open", index)

        # A signal based on the prior close can only be filled at this open.
        if pending_action == "enter" and quantity == 0:
            execution_price = _apply_slippage(open_price, "buy", slippage_rate)
            allocation = cash * position_size_pct
            quantity = allocation / (execution_price * (1 + fee_rate))
            entry_price = execution_price
            entry_index = index
            entry_time = candle.get("open_time")
            entry_fee = quantity * entry_price * fee_rate
            cash -= quantity * entry_price + entry_fee
        elif pending_action == "exit" and quantity > 0:
            close_position(index, open_price, "signal")
        pending_action = None

        if quantity > 0:
            low = _price(candle, "low", index)
            high = _price(candle, "high", index)
            stop_price = entry_price * (1 - stop_loss_pct) if stop_loss_pct is not None else None
            take_price = (
                entry_price * (1 + take_profit_pct) if take_profit_pct is not None else None
            )
            # OHLC cannot reveal the intrabar path. Choose the protective stop
            # whenever both levels were touched to avoid optimistic results.
            if stop_price is not None and low <= stop_price:
                # A gap below the stop cannot be filled at the more favorable
                # trigger price; use the opening price in that case.
                close_position(index, min(open_price, stop_price), "stop_loss")
            elif take_price is not None and high >= take_price:
                close_position(index, take_price, "take_profit")

        close = closes[index]
        equity = cash + quantity * close
        equity_curve.append(equity)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0.0)

        # Signals use data known at this close, and are executed at next open.
        if index < long_window or index == candle_count - 1:
            continue
        in_long = short_sma[index] > long_sma[index]
        was_in_long = short_sma[index - 1] > long_sma[index - 1]
        if in_long and not was_in_long and quantity == 0:
            pending_action = "enter"
        elif not in_long and quantity > 0:
            pending_action = "exit"

    # There is no next open after the final candle; close the remaining position
    # at its known close rather than silently dropping its P&L from the result.
    if quantity > 0:
        close_position(candle_count - 1, closes[-1], "end_of_data")
        equity_curve[-1] = cash

    gross_pnl = sum(trade.gross_pnl for trade in trade_history)
    total_fees = sum(trade.fees for trade in trade_history)
    net_pnls = [trade.net_pnl for trade in trade_history]
    wins = sum(1 for pnl in net_pnls if pnl > 0)
    losses = -sum(pnl for pnl in net_pnls if pnl < 0)
    gains = sum(pnl for pnl in net_pnls if pnl > 0)
    profit_factor = round(gains / losses, 4) if losses > 0 else None
    final_equity = cash

    return BacktestResult(
        initial_capital=round(initial_capital, 4),
        final_equity=round(final_equity, 4),
        total_pnl=round(final_equity - initial_capital, 4),
        trades=len(trade_history),
        win_rate=round(wins / len(trade_history), 4) if trade_history else 0.0,
        max_drawdown=round(max_drawdown, 4),
        equity_curve=[round(value, 4) for value in equity_curve],
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
            for trade in trade_history
        ],
    )


__all__ = ["BacktestResult", "BacktestTrade", "run_sma_backtest"]
