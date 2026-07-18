"""Versioned historical market-data catalog backed by DuckDB and Parquet."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from threading import RLock
from typing import Any

import duckdb

from app.market_data.quality import assess_candles, timeframe_delta


class MarketDataError(ValueError):
    """Base error raised for catalog input and lookup failures."""


class DatasetNotFoundError(MarketDataError):
    """Raised when a dataset version does not exist."""


class DatasetQualityError(MarketDataError):
    """Raised when a failed dataset is requested for backtesting."""


@dataclass(frozen=True)
class MarketCandle:
    """Canonical, UTC-normalized OHLCV candle persisted in every dataset."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    timeframe: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": _iso_utc(self.timestamp),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "source": self.source,
            "timeframe": self.timeframe,
        }


def _iso_utc(value: datetime) -> str:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, index: int) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MarketDataError(f"candle {index} has an invalid timestamp") from exc
    else:
        raise MarketDataError(f"candle {index} has an invalid timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketDataError(f"candle {index} timestamp must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def _read_text(value: object, *, field_name: str, index: int) -> str:
    result = str(value or "").strip()
    if not result:
        raise MarketDataError(f"candle {index} has an empty {field_name}")
    return result


def _read_number(value: object, *, field_name: str, index: int) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"candle {index} has an invalid {field_name}") from exc
    if not isfinite(result):
        raise MarketDataError(f"candle {index} has an invalid {field_name}")
    return result


def _normalize_candles(
    rows: Iterable[dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
    source: str,
) -> list[MarketCandle]:
    timeframe_delta(timeframe)
    normalized_symbol = _read_text(symbol, field_name="symbol", index=0).upper()
    normalized_timeframe = _read_text(timeframe, field_name="timeframe", index=0).lower()
    normalized_source = _read_text(source, field_name="source", index=0)
    normalized: list[MarketCandle] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MarketDataError(f"candle {index} must be an object")
        row_symbol = _read_text(row.get("symbol", normalized_symbol), field_name="symbol", index=index).upper()
        row_timeframe = _read_text(row.get("timeframe", normalized_timeframe), field_name="timeframe", index=index).lower()
        row_source = _read_text(row.get("source", normalized_source), field_name="source", index=index)
        if row_symbol != normalized_symbol or row_timeframe != normalized_timeframe or row_source != normalized_source:
            raise MarketDataError("one dataset import must contain exactly one symbol, timeframe, and source")
        normalized.append(
            MarketCandle(
                symbol=normalized_symbol,
                timestamp=_parse_timestamp(row.get("timestamp"), index),
                open=_read_number(row.get("open"), field_name="open", index=index),
                high=_read_number(row.get("high"), field_name="high", index=index),
                low=_read_number(row.get("low"), field_name="low", index=index),
                close=_read_number(row.get("close"), field_name="close", index=index),
                volume=_read_number(row.get("volume"), field_name="volume", index=index),
                source=normalized_source,
                timeframe=normalized_timeframe,
            )
        )
    if not normalized:
        raise MarketDataError("at least one candle is required")
    return normalized


def _content_hash(candles: Iterable[MarketCandle]) -> str:
    canonical = [candle.as_dict() for candle in candles]
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


class MarketDataCatalog:
    """Immutable market-data datasets plus their quality and provenance metadata."""

    def __init__(self, catalog_path: str, parquet_dir: str):
        self.catalog_path = Path(catalog_path)
        self.parquet_dir = Path(parquet_dir)
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = duckdb.connect(str(self.catalog_path))
        self._conn.execute("SET TimeZone='UTC'")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_datasets (
                    version VARCHAR PRIMARY KEY,
                    content_hash VARCHAR NOT NULL UNIQUE,
                    symbol VARCHAR NOT NULL,
                    timeframe VARCHAR NOT NULL,
                    source VARCHAR NOT NULL,
                    imported_at TIMESTAMP NOT NULL,
                    row_count BIGINT NOT NULL,
                    start_at TIMESTAMP NOT NULL,
                    end_at TIMESTAMP NOT NULL,
                    parquet_path VARCHAR NOT NULL,
                    quality_json VARCHAR NOT NULL
                )
                """
            )

    def import_candles(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        symbol: str,
        timeframe: str,
        source: str,
    ) -> dict[str, Any]:
        """Validate and persist a canonical Parquet dataset, idempotently by hash."""

        candles = _normalize_candles(rows, symbol=symbol, timeframe=timeframe, source=source)
        report = assess_candles(candles, candles[0].timeframe)
        content_hash = _content_hash(candles)
        version = f"md-{content_hash}"
        with self._lock:
            existing = self._dataset_row(version)
            if existing is not None:
                return existing

            parquet_path = self.parquet_dir / f"{version}.parquet"
            self._conn.execute(
                """
                CREATE OR REPLACE TEMP TABLE staged_candles (
                    symbol VARCHAR,
                    timestamp TIMESTAMP,
                    open DOUBLE,
                    high DOUBLE,
                    low DOUBLE,
                    close DOUBLE,
                    volume DOUBLE,
                    source VARCHAR,
                    timeframe VARCHAR
                )
                """
            )
            self._conn.executemany(
                "INSERT INTO staged_candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        candle.symbol,
                        candle.timestamp.replace(tzinfo=None),
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        candle.volume,
                        candle.source,
                        candle.timeframe,
                    )
                    for candle in candles
                ],
            )
            self._conn.execute(
                "COPY (SELECT * FROM staged_candles ORDER BY timestamp) TO "
                f"'{_sql_path(parquet_path)}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            imported_at = datetime.now(UTC).replace(tzinfo=None)
            self._conn.execute(
                """
                INSERT INTO market_datasets (
                    version, content_hash, symbol, timeframe, source, imported_at,
                    row_count, start_at, end_at, parquet_path, quality_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    version,
                    content_hash,
                    candles[0].symbol,
                    candles[0].timeframe,
                    candles[0].source,
                    imported_at,
                    len(candles),
                    min(candle.timestamp for candle in candles).replace(tzinfo=None),
                    max(candle.timestamp for candle in candles).replace(tzinfo=None),
                    str(parquet_path),
                    json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True),
                ],
            )
            result = self._dataset_row(version)
        assert result is not None
        return result

    def import_parquet(
        self,
        parquet_path: str | Path,
        *,
        symbol: str,
        timeframe: str,
        source: str,
    ) -> dict[str, Any]:
        """Import an external Parquet file after canonicalizing its candle columns."""

        source_path = Path(parquet_path)
        if not source_path.is_file():
            raise MarketDataError("Parquet file does not exist")
        with self._lock:
            cursor = self._conn.execute(
                f"SELECT * FROM read_parquet('{_sql_path(source_path)}')"
            )
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return self.import_candles(rows, symbol=symbol, timeframe=timeframe, source=source)

    def import_parquet_bytes(
        self,
        payload: bytes,
        *,
        symbol: str,
        timeframe: str,
        source: str,
    ) -> dict[str, Any]:
        """Import a Parquet upload without retaining the caller-owned raw file."""

        if not payload:
            raise MarketDataError("Parquet upload is empty")
        upload_dir = self.parquet_dir / ".uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        upload_path = upload_dir / f"{hashlib.sha256(payload).hexdigest()}.parquet"
        with self._lock:
            upload_path.write_bytes(payload)
            try:
                return self.import_parquet(
                    upload_path,
                    symbol=symbol,
                    timeframe=timeframe,
                    source=source,
                )
            finally:
                upload_path.unlink(missing_ok=True)

    def datasets(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM market_datasets ORDER BY imported_at DESC LIMIT ?", [limit]
            ).fetchall()
            columns = [column[0] for column in self._conn.description]
        return [self._serialize_dataset(dict(zip(columns, row, strict=True))) for row in rows]

    def dataset(self, version: str) -> dict[str, Any]:
        with self._lock:
            result = self._dataset_row(version)
        if result is None:
            raise DatasetNotFoundError(f"dataset version {version!r} was not found")
        return result

    def query_candles(
        self,
        version: str,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        require_quality: bool = False,
    ) -> list[dict[str, Any]]:
        """Query a versioned Parquet dataset using UTC-inclusive time bounds."""

        metadata = self.dataset(version)
        if require_quality and not metadata["quality_report"]["valid"]:
            raise DatasetQualityError(
                f"dataset {version} failed data-quality checks and cannot be used for backtesting"
            )
        if symbol is not None and symbol.upper() != metadata["symbol"]:
            return []
        if timeframe is not None and timeframe.lower() != metadata["timeframe"]:
            return []
        start = _normalize_query_time(start, "start")
        end = _normalize_query_time(end, "end")
        if start is not None and end is not None and start > end:
            raise MarketDataError("start must be earlier than or equal to end")

        where: list[str] = []
        params: list[object] = []
        if start is not None:
            where.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            where.append("timestamp <= ?")
            params.append(end)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        parquet_path = Path(metadata["parquet_path"])
        query = (
            "SELECT symbol, timestamp, open, high, low, close, volume, source, timeframe "
            f"FROM read_parquet('{_sql_path(parquet_path)}'){clause} ORDER BY timestamp"
        )
        with self._lock:
            cursor = self._conn.execute(query, params)
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return [
            {
                **row,
                "timestamp": _iso_utc(row["timestamp"]),
            }
            for row in rows
        ]

    def _dataset_row(self, version: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM market_datasets WHERE version = ?", [version]
        ).fetchone()
        if row is None:
            return None
        columns = [column[0] for column in self._conn.description]
        return self._serialize_dataset(dict(zip(columns, row, strict=True)))

    @staticmethod
    def _serialize_dataset(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": row["version"],
            "content_hash": row["content_hash"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "source": row["source"],
            "imported_at": _iso_utc(row["imported_at"]),
            "row_count": int(row["row_count"]),
            "start_at": _iso_utc(row["start_at"]),
            "end_at": _iso_utc(row["end_at"]),
            "parquet_path": row["parquet_path"],
            "quality_report": json.loads(row["quality_json"]),
        }


def _normalize_query_time(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataError(f"{field_name} must include an explicit UTC offset")
    return value.astimezone(UTC).replace(tzinfo=None)


__all__ = [
    "DatasetNotFoundError",
    "DatasetQualityError",
    "MarketCandle",
    "MarketDataCatalog",
    "MarketDataError",
]
