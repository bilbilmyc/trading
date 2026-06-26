"""Backtest engine — run SMA crossover on historical klines.

Pure-function design: takes a list of OHLCV dicts (any source — exchange,
CSV, custom data source) and returns a BacktestResult. No exchange calls,
no async — purely synchronous for ease of testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class BacktestResult:
    initial_capital: float
    final_equity: float
    total_pnl: float
    trades: int
    win_rate: float            # 0.0 - 1.0
    max_drawdown: float        # 0.0 - 1.0
    equity_curve: List[float] = field(default_factory=list)


def _sma(values: List[float], window: int) -> List[float]:
    """Simple moving average; first window-1 entries are None."""
    out: List[float] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window:
            s -= values[i - window]
        if i + 1 >= window:
            out.append(s / window)
        else:
            out.append(0.0)
    return out


def run_sma_backtest(
    candles: List[Dict[str, Any]],
    short_window: int = 5,
    long_window: int = 20,
    initial_capital: float = 10_000.0,
    position_size_pct: float = 1.0,  # 0..1 of capital per trade
) -> BacktestResult:
    """Run a simple SMA crossover backtest.

    Strategy: long when short_sma > long_sma; flat otherwise. Each entry
    uses `position_size_pct` of available capital; exits at next bar.
    """
    closes = [float(c.get("close", 0)) for c in candles]
    n = len(closes)
    if n < long_window + 1:
        return BacktestResult(
            initial_capital=initial_capital,
            final_equity=initial_capital,
            total_pnl=0.0,
            trades=0,
            win_rate=0.0,
            max_drawdown=0.0,
            equity_curve=[initial_capital] * n if n else [],
        )

    short_sma = _sma(closes, short_window)
    long_sma = _sma(closes, long_window)

    cash = initial_capital
    position_qty = 0.0
    position_entry = 0.0
    equity = initial_capital
    equity_curve: List[float] = []
    trades: List[float] = []  # realized PnL per closed trade
    peak = initial_capital
    max_dd = 0.0

    for i in range(n):
        price = closes[i]
        # Compute mark-to-market equity.
        mtm_equity = cash + position_qty * price
        equity_curve.append(mtm_equity)
        peak = max(peak, mtm_equity)
        if peak > 0:
            dd = (peak - mtm_equity) / peak
            if dd > max_dd:
                max_dd = dd

        if i < long_window:
            continue  # not enough history

        in_long = short_sma[i] > long_sma[i]
        prev_in_long = short_sma[i - 1] > long_sma[i - 1] if i > 0 else False

        # Entry: cross up.
        if in_long and not prev_in_long and position_qty == 0 and price > 0:
            position_qty = (cash * position_size_pct) / price
            position_entry = price
            cash -= position_qty * price

        # Exit: cross down OR we were already long and crossed up no longer holds.
        elif not in_long and position_qty > 0:
            cash += position_qty * price
            pnl = (price - position_entry) * position_qty
            trades.append(pnl)
            position_qty = 0.0
            position_entry = 0.0

    # Close any open position at last price.
    if position_qty > 0 and closes:
        cash += position_qty * closes[-1]
        pnl = (closes[-1] - position_entry) * position_qty
        trades.append(pnl)

    final_equity = cash
    total_pnl = final_equity - initial_capital
    wins = sum(1 for t in trades if t > 0)
    win_rate = (wins / len(trades)) if trades else 0.0

    return BacktestResult(
        initial_capital=initial_capital,
        final_equity=round(final_equity, 4),
        total_pnl=round(total_pnl, 4),
        trades=len(trades),
        win_rate=round(win_rate, 4),
        max_drawdown=round(max_dd, 4),
        equity_curve=[round(e, 4) for e in equity_curve],
    )


__all__ = ["BacktestResult", "run_sma_backtest"]