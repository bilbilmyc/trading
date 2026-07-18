"""
SQLite 持久化层。

当前系统先按“本地单节点量化工作台”设计，所以这里没有引入 ORM 和迁移框架。
存储接口尽量保持 dict 形状，方便 TradingEngine、API 和前端审计面板直接复用。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any


def _json_dumps(value: Any) -> str:
    return json.dumps({} if value is None else value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


class SQLiteStore:
    """API worker 使用的 SQLite 仓库。"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategies (
                    name TEXT PRIMARY KEY,
                    class_name TEXT NOT NULL,
                    exchange TEXT,
                    symbol TEXT,
                    interval TEXT NOT NULL DEFAULT '1m',
                    enabled INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL DEFAULT 'signal',
                    initialized_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    parameters_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS strategy_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    exchange TEXT,
                    symbol TEXT,
                    interval TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT 'configuration_change',
                    UNIQUE(strategy_name, version),
                    UNIQUE(strategy_name, fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_versions_name_version
                    ON strategy_versions(strategy_name, version DESC);

                CREATE TABLE IF NOT EXISTS strategy_backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    strategy_version INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    request_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_backtest_runs_name_time
                    ON strategy_backtest_runs(strategy_name, created_at DESC);

                CREATE TABLE IF NOT EXISTS backtest_experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    data_version TEXT,
                    data_start TEXT,
                    data_end TEXT,
                    strategy_parameters_json TEXT NOT NULL DEFAULT '{}',
                    execution_model_json TEXT NOT NULL DEFAULT '{}',
                    risk_model_json TEXT NOT NULL DEFAULT '{}',
                    environment_json TEXT NOT NULL DEFAULT '{}',
                    request_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    result_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_backtest_experiments_created
                    ON backtest_experiments(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_backtest_experiments_data_version
                    ON backtest_experiments(data_version, created_at DESC);

                CREATE TABLE IF NOT EXISTS strategy_promotion_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    strategy_version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    thresholds_json TEXT NOT NULL DEFAULT '{}',
                    requested_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    decision_note TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_promotion_reviews_name_time
                    ON strategy_promotion_reviews(strategy_name, requested_at DESC);

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    strength REAL NOT NULL,
                    quantity REAL,
                    price REAL,
                    order_type TEXT NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    actionable INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
                CREATE INDEX IF NOT EXISTS idx_signals_strategy_symbol ON signals(strategy, symbol);

                CREATE TABLE IF NOT EXISTS account_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    balances_json TEXT NOT NULL DEFAULT '[]',
                    positions_json TEXT NOT NULL DEFAULT '[]',
                    balance_sync_ok INTEGER NOT NULL DEFAULT 0,
                    position_sync_ok INTEGER,
                    errors_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_account_snapshots_exchange_time
                    ON account_snapshots(exchange, created_at DESC);

                CREATE TABLE IF NOT EXISTS reconciliation_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    issue_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    local_json TEXT,
                    exchange_json TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'open',
                    detected_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution_note TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_reconciliation_issues_open
                    ON reconciliation_issues(exchange, issue_key, status);
                CREATE INDEX IF NOT EXISTS idx_reconciliation_issues_status
                    ON reconciliation_issues(exchange, status, severity);

                CREATE TABLE IF NOT EXISTS paper_account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_cash REAL NOT NULL,
                    cash REAL NOT NULL,
                    fee_rate REAL NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_positions (
                    position_key TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    avg_entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_orders (
                    order_id TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    fee REAL NOT NULL,
                    realized_pnl REAL NOT NULL,
                    status TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    signal_metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_paper_orders_timestamp ON paper_orders(timestamp);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    level TEXT NOT NULL,
                    exchange TEXT,
                    symbol TEXT,
                    strategy TEXT,
                    order_id TEXT,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
                CREATE INDEX IF NOT EXISTS idx_events_order_id ON events(order_id);

                CREATE TABLE IF NOT EXISTS bot_autopilot_budget_reservations (
                    decision_id TEXT PRIMARY KEY,
                    budget_date TEXT NOT NULL,
                    notional REAL NOT NULL CHECK (notional > 0),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_bot_autopilot_budget_date
                    ON bot_autopilot_budget_reservations(budget_date);

                CREATE TABLE IF NOT EXISTS risk_daily_notional_reservations (
                    client_order_id TEXT PRIMARY KEY,
                    budget_date TEXT NOT NULL,
                    notional REAL NOT NULL CHECK (notional > 0),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_risk_daily_notional_date
                    ON risk_daily_notional_reservations(budget_date);

                CREATE TABLE IF NOT EXISTS execution_intents (
                    client_order_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL,
                    status TEXT NOT NULL,
                    exchange_order_id TEXT,
                    request_json TEXT NOT NULL DEFAULT '{}',
                    response_json TEXT NOT NULL DEFAULT '{}',
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_execution_intents_status
                    ON execution_intents(status, exchange, updated_at);
                """
            )
            self._conn.commit()

    def record_strategy_version(
        self,
        strategy: dict[str, Any],
        *,
        fingerprint: str,
        reason: str = "configuration_change",
    ) -> dict[str, Any]:
        """Append an immutable version only when its configuration changed."""

        name = str(strategy["name"])
        created_at = str(strategy.get("updated_at") or strategy["initialized_at"])
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM strategy_versions WHERE strategy_name = ? AND fingerprint = ?",
                (name, fingerprint),
            ).fetchone()
            if existing is None:
                row = self._conn.execute(
                    "SELECT COALESCE(MAX(version), 0) AS latest FROM strategy_versions "
                    "WHERE strategy_name = ?",
                    (name,),
                ).fetchone()
                version = int(row["latest"]) + 1
                self._conn.execute(
                    """
                    INSERT INTO strategy_versions (
                        strategy_name, version, fingerprint, class_name, exchange, symbol,
                        interval, mode, enabled, parameters_json, created_at, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        version,
                        fingerprint,
                        strategy["class_name"],
                        strategy.get("exchange"),
                        strategy.get("symbol"),
                        strategy.get("interval", "1m"),
                        strategy.get("mode", "signal"),
                        1 if strategy.get("running") else 0,
                        _json_dumps(strategy.get("parameters")),
                        created_at,
                        reason,
                    ),
                )
                self._conn.commit()
                existing = self._conn.execute(
                    "SELECT * FROM strategy_versions WHERE strategy_name = ? AND version = ?",
                    (name, version),
                ).fetchone()
        return self._strategy_version_row(existing)

    @staticmethod
    def _strategy_version_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "strategy_name": row["strategy_name"],
            "version": row["version"],
            "fingerprint": row["fingerprint"],
            "class_name": row["class_name"],
            "exchange": row["exchange"],
            "symbol": row["symbol"],
            "interval": row["interval"],
            "mode": row["mode"],
            "enabled": bool(row["enabled"]),
            "parameters": _json_loads(row["parameters_json"]),
            "created_at": row["created_at"],
            "reason": row["reason"],
        }

    def strategy_versions(self, strategy_name: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM strategy_versions WHERE strategy_name = ? "
                "ORDER BY version DESC LIMIT ?",
                (strategy_name, limit),
            ).fetchall()
        return [self._strategy_version_row(row) for row in rows]

    def latest_strategy_version(self, strategy_name: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM strategy_versions WHERE strategy_name = ? "
                "ORDER BY version DESC LIMIT 1",
                (strategy_name,),
            ).fetchone()
        return self._strategy_version_row(row) if row else None

    def save_strategy_backtest_run(
        self,
        *,
        strategy_name: str,
        strategy_version: int,
        kind: str,
        request: dict[str, Any],
        result: dict[str, Any],
        created_at: str,
    ) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO strategy_backtest_runs (
                    strategy_name, strategy_version, kind, request_json, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_name,
                    strategy_version,
                    kind,
                    _json_dumps(request),
                    _json_dumps(result),
                    created_at,
                ),
            )
            self._conn.commit()
        return int(cursor.lastrowid)

    def recent_strategy_backtest_runs(self, strategy_name: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM strategy_backtest_runs WHERE strategy_name = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (strategy_name, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "strategy_name": row["strategy_name"],
                "strategy_version": row["strategy_version"],
                "kind": row["kind"],
                "request": _json_loads(row["request_json"]),
                "result": _json_loads(row["result_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def paper_strategy_performance(self, strategy_name: str) -> dict[str, Any]:
        """Summarise closed long paper trades for a promotion review."""

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT realized_pnl, fee, timestamp FROM paper_orders
                WHERE strategy = ? AND lower(side) = 'sell' AND status = 'filled'
                ORDER BY timestamp ASC
                """,
                (strategy_name,),
            ).fetchall()
        net_pnls = [float(row["realized_pnl"]) - float(row["fee"]) for row in rows]
        wins = sum(value > 0 for value in net_pnls)
        gains = sum(value for value in net_pnls if value > 0)
        losses = -sum(value for value in net_pnls if value < 0)
        return {
            "strategy_name": strategy_name,
            "closed_trades": len(net_pnls),
            "wins": wins,
            "win_rate": round(wins / len(net_pnls), 4) if net_pnls else 0.0,
            "total_pnl": round(sum(net_pnls), 4),
            "profit_factor": round(gains / losses, 4) if losses > 0 else None,
            "first_closed_at": rows[0]["timestamp"] if rows else None,
            "last_closed_at": rows[-1]["timestamp"] if rows else None,
        }

    def create_strategy_promotion_review(
        self,
        *,
        strategy_name: str,
        strategy_version: int,
        status: str,
        evidence: dict[str, Any],
        thresholds: dict[str, Any],
        requested_at: str,
    ) -> dict[str, Any]:
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO strategy_promotion_reviews (
                    strategy_name, strategy_version, status, evidence_json, thresholds_json, requested_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_name,
                    strategy_version,
                    status,
                    _json_dumps(evidence),
                    _json_dumps(thresholds),
                    requested_at,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM strategy_promotion_reviews WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._promotion_review_row(row)

    @staticmethod
    def _promotion_review_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "strategy_name": row["strategy_name"],
            "strategy_version": row["strategy_version"],
            "status": row["status"],
            "evidence": _json_loads(row["evidence_json"]),
            "thresholds": _json_loads(row["thresholds_json"]),
            "requested_at": row["requested_at"],
            "decided_at": row["decided_at"],
            "decided_by": row["decided_by"],
            "decision_note": row["decision_note"],
        }

    def decide_strategy_promotion_review(
        self,
        review_id: int,
        *,
        strategy_name: str,
        approved: bool,
        decided_by: str,
        note: str,
        decided_at: str,
    ) -> dict[str, Any] | None:
        status = "approved" if approved else "rejected"
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE strategy_promotion_reviews
                SET status = ?, decided_at = ?, decided_by = ?, decision_note = ?
                WHERE id = ? AND strategy_name = ? AND status = 'eligible'
                """,
                (status, decided_at, decided_by, note, review_id, strategy_name),
            )
            self._conn.commit()
            if cursor.rowcount != 1:
                return None
            row = self._conn.execute(
                "SELECT * FROM strategy_promotion_reviews WHERE id = ?", (review_id,)
            ).fetchone()
        return self._promotion_review_row(row)

    def save_backtest_experiment(
        self,
        *,
        strategy_name: str,
        strategy_version: str,
        data_version: str | None,
        data_start: str | None,
        data_end: str | None,
        strategy_parameters: dict[str, Any],
        execution_model: dict[str, Any],
        risk_model: dict[str, Any],
        environment: dict[str, Any],
        request: dict[str, Any],
        result: dict[str, Any],
        result_hash: str,
        created_at: str,
    ) -> int:
        """Persist an immutable, reproducible backtest experiment record."""

        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO backtest_experiments (
                    strategy_name, strategy_version, data_version, data_start, data_end,
                    strategy_parameters_json, execution_model_json, risk_model_json,
                    environment_json, request_json, result_json, result_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_name,
                    strategy_version,
                    data_version,
                    data_start,
                    data_end,
                    _json_dumps(strategy_parameters),
                    _json_dumps(execution_model),
                    _json_dumps(risk_model),
                    _json_dumps(environment),
                    _json_dumps(request),
                    _json_dumps(result),
                    result_hash,
                    created_at,
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    @staticmethod
    def _backtest_experiment_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "strategy_name": row["strategy_name"],
            "strategy_version": row["strategy_version"],
            "data_version": row["data_version"],
            "data_start": row["data_start"],
            "data_end": row["data_end"],
            "strategy_parameters": _json_loads(row["strategy_parameters_json"]),
            "execution_model": _json_loads(row["execution_model_json"]),
            "risk_model": _json_loads(row["risk_model_json"]),
            "environment": _json_loads(row["environment_json"]),
            "request": _json_loads(row["request_json"]),
            "result": _json_loads(row["result_json"]),
            "result_hash": row["result_hash"],
            "created_at": row["created_at"],
        }

    def recent_backtest_experiments(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return bounded experiment history for read-only analysis context."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM backtest_experiments ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._backtest_experiment_row(row) for row in rows]

    def backtest_experiment(self, experiment_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM backtest_experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
        return self._backtest_experiment_row(row) if row else None

    def upsert_strategy(self, strategy: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO strategies (
                    name, class_name, exchange, symbol, interval, enabled, mode,
                    initialized_at, updated_at, parameters_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    class_name=excluded.class_name,
                    exchange=excluded.exchange,
                    symbol=excluded.symbol,
                    interval=excluded.interval,
                    enabled=excluded.enabled,
                    mode=excluded.mode,
                    initialized_at=excluded.initialized_at,
                    updated_at=excluded.updated_at,
                    parameters_json=excluded.parameters_json
                """,
                (
                    strategy["name"],
                    strategy["class_name"],
                    strategy.get("exchange"),
                    strategy.get("symbol"),
                    strategy.get("interval", "1m"),
                    1 if strategy.get("running") else 0,
                    strategy.get("mode", "signal"),
                    strategy["initialized_at"],
                    strategy.get("updated_at") or strategy["initialized_at"],
                    _json_dumps(strategy.get("parameters")),
                ),
            )
            self._conn.commit()

    def delete_strategy(self, name: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM strategies WHERE name = ?", (name,))
            self._conn.commit()

    def list_strategies(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM strategies ORDER BY name").fetchall()
        return [
            {
                "name": row["name"],
                "class_name": row["class_name"],
                "exchange": row["exchange"],
                "symbol": row["symbol"],
                "interval": row["interval"],
                "enabled": bool(row["enabled"]),
                "mode": row["mode"],
                "initialized_at": row["initialized_at"],
                "updated_at": row["updated_at"],
                "parameters": _json_loads(row["parameters_json"]),
            }
            for row in rows
        ]

    def append_signal(self, signal: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO signals (
                    exchange, strategy, symbol, action, strength, quantity, price,
                    order_type, stop_loss, take_profit, metadata_json, actionable, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal["exchange"],
                    signal["strategy"],
                    signal["symbol"],
                    signal["action"],
                    signal["strength"],
                    signal.get("quantity"),
                    signal.get("price"),
                    signal["order_type"],
                    signal.get("stop_loss"),
                    signal.get("take_profit"),
                    _json_dumps(signal.get("metadata")),
                    1 if signal.get("actionable") else 0,
                    signal["timestamp"],
                ),
            )
            self._conn.commit()

    def recent_signals(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        rows = list(reversed(rows))
        return [
            {
                "exchange": row["exchange"],
                "strategy": row["strategy"],
                "symbol": row["symbol"],
                "action": row["action"],
                "strength": row["strength"],
                "quantity": row["quantity"],
                "price": row["price"],
                "order_type": row["order_type"],
                "stop_loss": row["stop_loss"],
                "take_profit": row["take_profit"],
                "metadata": _json_loads(row["metadata_json"]),
                "actionable": bool(row["actionable"]),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def append_event(self, event: dict[str, Any]) -> None:
        """追加一条可审计事件，比如下单、撤单、风控拒单。"""

        self.append_events([event])

    def append_events(self, events: list[dict[str, Any]]) -> None:
        """Batched event writes — N rows in one transaction.

        Use this when emitting multiple audit events from a single logical
        operation (e.g. signal veto + risk reject + observer push). One
        commit replaces N commits, cutting SQLite fsync overhead.

        The transaction is committed before this method returns, so a
        second connection (e.g. the SSE generator's polling loop) sees
        the new rows on its next read.
        """
        if not events:
            return
        rows = [
            (
                e["category"],
                e["event_type"],
                e.get("level", "info"),
                e.get("exchange"),
                e.get("symbol"),
                e.get("strategy"),
                e.get("order_id"),
                e["message"],
                _json_dumps(e.get("details")),
                e["timestamp"],
            )
            for e in events
        ]
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO events (
                    category, event_type, level, exchange, symbol, strategy,
                    order_id, message, details_json, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.commit()

    def _reserve_daily_notional(
        self,
        *,
        table_name: str,
        key_column: str,
        reservation_key: str,
        budget_date: str,
        notional: float,
        maximum_notional: float,
        created_at: str,
    ) -> tuple[bool, float, bool]:
        """Atomically reserve a daily notional budget using a fixed internal table.

        The table and key-column arguments are only supplied by the two wrappers
        below, never from an API request. A durable reservation is intentionally
        retained when exchange submission is uncertain: freeing it could allow a
        duplicate live order to exceed the daily cap.
        """
        if notional <= 0 or maximum_notional <= 0:
            raise ValueError("notional and maximum_notional must be positive")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._conn.execute(
                    f"SELECT notional FROM {table_name} WHERE {key_column} = ?",
                    (reservation_key,),
                ).fetchone()
                if existing is not None:
                    used = float(
                        self._conn.execute(
                            f"SELECT COALESCE(SUM(notional), 0) FROM {table_name} "
                            "WHERE budget_date = ?",
                            (budget_date,),
                        ).fetchone()[0]
                    )
                    self._conn.commit()
                    return True, used - float(existing["notional"]), True

                used = float(
                    self._conn.execute(
                        f"SELECT COALESCE(SUM(notional), 0) FROM {table_name} "
                        "WHERE budget_date = ?",
                        (budget_date,),
                    ).fetchone()[0]
                )
                if used + notional > maximum_notional:
                    self._conn.rollback()
                    return False, used, False
                self._conn.execute(
                    f"INSERT INTO {table_name} "
                    f"({key_column}, budget_date, notional, created_at) VALUES (?, ?, ?, ?)",
                    (reservation_key, budget_date, notional, created_at),
                )
                self._conn.commit()
                return True, used, False
            except Exception:
                self._conn.rollback()
                raise

    def reserve_bot_autopilot_notional(
        self,
        *,
        decision_id: str,
        budget_date: str,
        notional: float,
        maximum_notional: float,
        created_at: str,
    ) -> tuple[bool, float, bool]:
        """Atomically reserve an unattended-Bot daily notional budget."""
        return self._reserve_daily_notional(
            table_name="bot_autopilot_budget_reservations",
            key_column="decision_id",
            reservation_key=decision_id,
            budget_date=budget_date,
            notional=notional,
            maximum_notional=maximum_notional,
            created_at=created_at,
        )

    def reserve_risk_daily_notional(
        self,
        *,
        client_order_id: str,
        budget_date: str,
        notional: float,
        maximum_notional: float,
        created_at: str,
    ) -> tuple[bool, float, bool]:
        """Atomically reserve the shared live-trading daily notional budget."""
        return self._reserve_daily_notional(
            table_name="risk_daily_notional_reservations",
            key_column="client_order_id",
            reservation_key=client_order_id,
            budget_date=budget_date,
            notional=notional,
            maximum_notional=maximum_notional,
            created_at=created_at,
        )

    def recent_events(
        self,
        category: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """按时间顺序返回最近事件，供 API 和前端审计时间线使用。"""

        filters = []
        params: list[Any] = []
        if category:
            filters.append("category = ?")
            params.append(category)
        if event_type:
            filters.append("event_type = ?")
            params.append(event_type)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM events {where} ORDER BY id DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        rows = list(reversed(rows))
        return [
            {
                "id": row["id"],
                "category": row["category"],
                "event_type": row["event_type"],
                "level": row["level"],
                "exchange": row["exchange"],
                "symbol": row["symbol"],
                "strategy": row["strategy"],
                "order_id": row["order_id"],
                "message": row["message"],
                "details": _json_loads(row["details_json"]),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def create_execution_intent(self, intent: dict[str, Any]) -> bool:
        """Persist a new external order intent exactly once.

        Returns ``True`` only for the caller that won the client-order-id
        claim. Callers that lose the race must read and replay the stored
        result instead of submitting another order to the exchange.
        """

        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO execution_intents (
                    client_order_id, fingerprint, exchange, symbol, side,
                    order_type, quantity, price, status, exchange_order_id,
                    request_json, response_json, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent["client_order_id"],
                    intent["fingerprint"],
                    intent["exchange"],
                    intent["symbol"],
                    intent["side"],
                    intent["order_type"],
                    intent["quantity"],
                    intent.get("price"),
                    intent.get("status", "submitting"),
                    intent.get("exchange_order_id"),
                    _json_dumps(intent.get("request")),
                    _json_dumps(intent.get("response")),
                    intent.get("last_error"),
                    intent["created_at"],
                    intent.get("updated_at") or intent["created_at"],
                ),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    def get_execution_intent(self, client_order_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM execution_intents WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        return self._execution_intent_row(row) if row is not None else None

    def update_execution_intent(
        self,
        client_order_id: str,
        *,
        status: str | None = None,
        exchange_order_id: str | None = None,
        response: dict[str, Any] | None = None,
        last_error: str | None = None,
        clear_error: bool = False,
    ) -> None:
        """Update the durable execution state without overwriting request intent."""

        assignments: list[str] = ["updated_at = datetime('now')"]
        params: list[Any] = []
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
        if exchange_order_id is not None:
            assignments.append("exchange_order_id = ?")
            params.append(exchange_order_id)
        if response is not None:
            assignments.append("response_json = ?")
            params.append(_json_dumps(response))
        if last_error is not None:
            assignments.append("last_error = ?")
            params.append(last_error)
        elif clear_error:
            assignments.append("last_error = NULL")
        params.append(client_order_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE execution_intents SET {', '.join(assignments)} WHERE client_order_id = ?",
                tuple(params),
            )
            self._conn.commit()

    def pending_execution_intents(self, exchange: str | None = None) -> list[dict[str, Any]]:
        """Return intents which may still need exchange reconciliation."""

        params: list[Any] = ["submitting", "submitted", "unknown", "pending", "partially_filled"]
        where = "status IN (?, ?, ?, ?, ?)"
        if exchange:
            where += " AND exchange = ?"
            params.append(exchange)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM execution_intents WHERE {where} ORDER BY created_at ASC",
                tuple(params),
            ).fetchall()
        return [self._execution_intent_row(row) for row in rows]

    @staticmethod
    def _execution_intent_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "client_order_id": row["client_order_id"],
            "fingerprint": row["fingerprint"],
            "exchange": row["exchange"],
            "symbol": row["symbol"],
            "side": row["side"],
            "order_type": row["order_type"],
            "quantity": row["quantity"],
            "price": row["price"],
            "status": row["status"],
            "exchange_order_id": row["exchange_order_id"],
            "request": _json_loads(row["request_json"]),
            "response": _json_loads(row["response_json"]),
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def append_account_snapshot(self, outcome: dict[str, Any]) -> None:
        """Persist the exchange-authoritative view from one reconciliation pass."""

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO account_snapshots (
                    exchange, balances_json, positions_json, balance_sync_ok,
                    position_sync_ok, errors_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome["exchange"],
                    _json_dumps(outcome.get("balances", [])),
                    _json_dumps(outcome.get("positions", [])),
                    int(bool(outcome.get("balance_sync_ok"))),
                    (
                        None
                        if outcome.get("position_sync_ok") is None
                        else int(bool(outcome.get("position_sync_ok")))
                    ),
                    _json_dumps(outcome.get("errors", [])),
                    outcome.get("completed_at") or datetime.utcnow().isoformat(),
                ),
            )
            self._conn.commit()

    def upsert_reconciliation_issues(self, exchange: str, issues: list[dict[str, Any]]) -> None:
        """Keep one open record per active discrepancy while retaining history."""

        if not issues:
            return
        now = datetime.utcnow().isoformat()
        with self._lock:
            for issue in issues:
                self._conn.execute(
                    """
                    INSERT INTO reconciliation_issues (
                        exchange, issue_key, kind, severity, local_json,
                        exchange_json, details_json, status, detected_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                    ON CONFLICT(exchange, issue_key, status) DO UPDATE SET
                        kind = excluded.kind,
                        severity = excluded.severity,
                        local_json = excluded.local_json,
                        exchange_json = excluded.exchange_json,
                        details_json = excluded.details_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        exchange.lower(),
                        issue["issue_key"],
                        issue["kind"],
                        issue["severity"],
                        _json_dumps(issue.get("local")) if issue.get("local") is not None else None,
                        _json_dumps(issue.get("exchange"))
                        if issue.get("exchange") is not None
                        else None,
                        _json_dumps({"resource": issue.get("resource")}),
                        now,
                        now,
                    ),
                )
            self._conn.commit()

    @staticmethod
    def _reconciliation_issue_row(row: sqlite3.Row) -> dict[str, Any]:
        details = _json_loads(row["details_json"])
        return {
            "id": row["id"],
            "exchange": row["exchange"],
            "issue_key": row["issue_key"],
            "kind": row["kind"],
            "severity": row["severity"],
            "resource": details.get("resource"),
            "local": _json_loads(row["local_json"]) if row["local_json"] else None,
            "exchange_state": _json_loads(row["exchange_json"]) if row["exchange_json"] else None,
            "status": row["status"],
            "detected_at": row["detected_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
            "resolution_note": row["resolution_note"],
        }

    def reconciliation_issues(
        self, exchange: str | None = None, status: str = "open"
    ) -> list[dict[str, Any]]:
        where = "status = ?"
        params: list[Any] = [status]
        if exchange:
            where += " AND exchange = ?"
            params.append(exchange.lower())
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM reconciliation_issues WHERE {where} "
                "ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END, detected_at DESC",
                tuple(params),
            ).fetchall()
        return [self._reconciliation_issue_row(row) for row in rows]

    def resolve_reconciliation_issues(self, exchange: str, note: str) -> int:
        """Resolve all currently open issues after an explicit operator action."""

        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE reconciliation_issues
                SET status = 'resolved', resolved_at = datetime('now'),
                    updated_at = datetime('now'), resolution_note = ?
                WHERE exchange = ? AND status = 'open'
                """,
                (note, exchange.lower()),
            )
            self._conn.commit()
        return cursor.rowcount

    def reconciliation_summary(self, exchange: str | None = None) -> dict[str, Any]:
        issues = self.reconciliation_issues(exchange)
        return {
            "open_count": len(issues),
            "critical_count": sum(issue["severity"] == "critical" for issue in issues),
            "warning_count": sum(issue["severity"] == "warning" for issue in issues),
        }

    def save_paper_state(self, summary: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO paper_account (id, initial_cash, cash, fee_rate, enabled, updated_at)
                VALUES (1, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    initial_cash=excluded.initial_cash,
                    cash=excluded.cash,
                    fee_rate=excluded.fee_rate,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    summary["initial_cash"],
                    summary["cash"],
                    summary["fee_rate"],
                    1 if summary["enabled"] else 0,
                ),
            )
            for position in summary.get("positions", []):
                key = f"{position['exchange']}:{position['symbol']}"
                self._conn.execute(
                    """
                    INSERT INTO paper_positions (
                        position_key, exchange, symbol, quantity, avg_entry_price,
                        current_price, realized_pnl, unrealized_pnl, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(position_key) DO UPDATE SET
                        quantity=excluded.quantity,
                        avg_entry_price=excluded.avg_entry_price,
                        current_price=excluded.current_price,
                        realized_pnl=excluded.realized_pnl,
                        unrealized_pnl=excluded.unrealized_pnl,
                        updated_at=excluded.updated_at
                    """,
                    (
                        key,
                        position["exchange"],
                        position["symbol"],
                        position["quantity"],
                        position["avg_entry_price"],
                        position["current_price"],
                        position["realized_pnl"],
                        position["unrealized_pnl"],
                        position["updated_at"],
                    ),
                )
            active_keys = {
                f"{item['exchange']}:{item['symbol']}" for item in summary.get("positions", [])
            }
            if active_keys:
                placeholders = ",".join("?" for _ in active_keys)
                self._conn.execute(
                    f"DELETE FROM paper_positions WHERE position_key NOT IN ({placeholders})",
                    tuple(active_keys),
                )
            else:
                self._conn.execute("DELETE FROM paper_positions")
            self._conn.commit()

    def save_paper_order(self, order: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO paper_orders (
                    order_id, exchange, strategy, symbol, side, quantity, price, fee,
                    realized_pnl, status, timestamp, signal_metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order["order_id"],
                    order["exchange"],
                    order["strategy"],
                    order["symbol"],
                    order["side"],
                    order["quantity"],
                    order["price"],
                    order["fee"],
                    order["realized_pnl"],
                    order["status"],
                    order["timestamp"],
                    _json_dumps(order.get("signal_metadata")),
                ),
            )
            self._conn.commit()

    def clear_paper_orders(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM paper_orders")
            self._conn.commit()

    def recent_paper_orders(
        self,
        *,
        limit: int = 100,
        strategy: str | None = None,
        exchange: str | None = None,
    ) -> list[dict[str, Any]]:
        """List recent paper orders, newest first."""
        clauses: list[str] = []
        params: list[Any] = []
        if strategy:
            clauses.append("strategy = ?")
            params.append(strategy)
        if exchange:
            clauses.append("exchange = ?")
            params.append(exchange)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM paper_orders {where} ORDER BY timestamp DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [dict(r) for r in rows]

    def load_paper_state(self) -> dict[str, Any]:
        with self._lock:
            account = self._conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
            positions = self._conn.execute(
                "SELECT * FROM paper_positions ORDER BY position_key"
            ).fetchall()
            order_rows = self._conn.execute(
                "SELECT * FROM paper_orders ORDER BY timestamp DESC LIMIT 200"
            ).fetchall()
            orders = []
            for row in reversed(order_rows):
                order = dict(row)
                order["signal_metadata"] = _json_loads(order.pop("signal_metadata_json", "{}"))
                orders.append(order)
        return {
            "account": dict(account) if account else None,
            "positions": [dict(row) for row in positions],
            "orders": orders,
        }
