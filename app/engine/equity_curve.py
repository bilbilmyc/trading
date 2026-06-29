"""Per-strategy equity curve storage and aggregation.

Snapshots are taken at trade close, recorded into SQLite, and
retrievable as a time series for the portfolio chart. Pure functions
for aggregation (Sharpe, max DD, etc.) live in portfolio_metrics.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class EquitySnapshot:
    strategy: str
    equity: float
    timestamp: str
    trade_id: Optional[str] = None


class EquityCurveStore:
    """Append-only log of per-strategy equity snapshots."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS equity_curve (
                    strategy TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    equity REAL NOT NULL,
                    trade_id TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_equity_strategy_ts "
                "ON equity_curve(strategy, timestamp DESC)"
            )
            self._conn.commit()

    def record(self, snapshot: EquitySnapshot) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO equity_curve (strategy, timestamp, equity, trade_id) "
                "VALUES (?, ?, ?, ?)",
                (snapshot.strategy, snapshot.timestamp, snapshot.equity, snapshot.trade_id),
            )
            self._conn.commit()

    def history(
        self,
        strategy: str,
        *,
        since: Optional[str] = None,
        limit: int = 500,
    ) -> List[EquitySnapshot]:
        with self._lock:
            if since:
                rows = self._conn.execute(
                    "SELECT * FROM equity_curve WHERE strategy = ? AND timestamp >= ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (strategy, since, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM equity_curve WHERE strategy = ? "
                    "ORDER BY timestamp DESC LIMIT ?",
                    (strategy, limit),
                ).fetchall()
        return [
            EquitySnapshot(
                strategy=r["strategy"],
                timestamp=r["timestamp"],
                equity=r["equity"],
                trade_id=r["trade_id"],
            )
            for r in rows
        ]

    def latest(self, strategy: str) -> Optional[EquitySnapshot]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM equity_curve WHERE strategy = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (strategy,),
            ).fetchone()
        if not row:
            return None
        return EquitySnapshot(
            strategy=row["strategy"],
            timestamp=row["timestamp"],
            equity=row["equity"],
            trade_id=row["trade_id"],
        )

    def all_strategies_equity_curves(
        self, since: Optional[str] = None
    ) -> Dict[str, List[EquitySnapshot]]:
        """Return a dict strategy -> sorted equity curve (oldest first)."""
        with self._lock:
            if since:
                rows = self._conn.execute(
                    "SELECT * FROM equity_curve WHERE timestamp >= ? "
                    "ORDER BY strategy, timestamp ASC",
                    (since,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM equity_curve ORDER BY strategy, timestamp ASC"
                ).fetchall()
        out: Dict[str, List[EquitySnapshot]] = {}
        for r in rows:
            out.setdefault(r["strategy"], []).append(
                EquitySnapshot(
                    strategy=r["strategy"],
                    timestamp=r["timestamp"],
                    equity=r["equity"],
                    trade_id=r["trade_id"],
                )
            )
        return out


__all__ = ["EquitySnapshot", "EquityCurveStore"]