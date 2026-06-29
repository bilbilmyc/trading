"""
SQLite 持久化层。

当前系统先按“本地单节点量化工作台”设计，所以这里没有引入 ORM 和迁移框架。
存储接口尽量保持 dict 形状，方便 TradingEngine、API 和前端审计面板直接复用。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Optional[str]) -> Dict[str, Any]:
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
                """
            )
            self._conn.commit()

    def upsert_strategy(self, strategy: Dict[str, Any]) -> None:
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

    def list_strategies(self) -> List[Dict[str, Any]]:
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

    def append_signal(self, signal: Dict[str, Any]) -> None:
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

    def recent_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
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

    def append_event(self, event: Dict[str, Any]) -> None:
        """追加一条可审计事件，比如下单、撤单、风控拒单。"""

        self.append_events([event])

    def append_events(self, events: List[Dict[str, Any]]) -> None:
        """Batched event writes — N rows in one transaction.

        Use this when emitting multiple audit events from a single logical
        operation (e.g. signal veto + risk reject + observer push). One
        commit replaces N commits, cutting SQLite fsync overhead.
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

    def recent_events(
        self,
        category: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """按时间顺序返回最近事件，供 API 和前端审计时间线使用。"""

        filters = []
        params: List[Any] = []
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

    def save_paper_state(self, summary: Dict[str, Any]) -> None:
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
            active_keys = {f"{item['exchange']}:{item['symbol']}" for item in summary.get("positions", [])}
            if active_keys:
                placeholders = ",".join("?" for _ in active_keys)
                self._conn.execute(
                    f"DELETE FROM paper_positions WHERE position_key NOT IN ({placeholders})",
                    tuple(active_keys),
                )
            else:
                self._conn.execute("DELETE FROM paper_positions")
            self._conn.commit()

    def save_paper_order(self, order: Dict[str, Any]) -> None:
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
        strategy: Optional[str] = None,
        exchange: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List recent paper orders, newest first."""
        clauses: List[str] = []
        params: List[Any] = []
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
                f"SELECT * FROM paper_orders {where} "
                f"ORDER BY timestamp DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [dict(r) for r in rows]

    def load_paper_state(self) -> Dict[str, Any]:
        with self._lock:
            account = self._conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
            positions = self._conn.execute("SELECT * FROM paper_positions ORDER BY position_key").fetchall()
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
