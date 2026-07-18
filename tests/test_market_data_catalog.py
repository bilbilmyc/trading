from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from app.market_data import MarketDataCatalog


def _candles(count: int = 6) -> list[dict[str, object]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {
            "timestamp": (start + timedelta(minutes=index)).isoformat().replace("+00:00", "Z"),
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.5 + index,
            "volume": 10.0 + index,
        }
        for index in range(count)
    ]


def _catalog(tmp_path: Path) -> MarketDataCatalog:
    return MarketDataCatalog(
        str(tmp_path / "market_data.duckdb"),
        str(tmp_path / "market_data"),
    )


def test_catalog_imports_utc_parquet_and_queries_time_range(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    dataset = catalog.import_candles(
        _candles(), symbol="btcusdt", timeframe="1m", source="fixture"
    )

    assert dataset["symbol"] == "BTCUSDT"
    assert dataset["quality_report"]["valid"] is True
    assert len(dataset["content_hash"]) == 64
    assert Path(dataset["parquet_path"]).is_file()

    rows = catalog.query_candles(
        dataset["version"],
        symbol="BTCUSDT",
        timeframe="1m",
        start=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 4, tzinfo=UTC),
        require_quality=True,
    )
    assert [row["timestamp"] for row in rows] == [
        "2026-01-01T00:02:00Z",
        "2026-01-01T00:03:00Z",
        "2026-01-01T00:04:00Z",
    ]
    assert catalog.import_candles(
        _candles(), symbol="BTCUSDT", timeframe="1m", source="fixture"
    )["version"] == dataset["version"]
    catalog.close()


def test_catalog_imports_external_parquet_file(tmp_path: Path) -> None:
    source_path = tmp_path / "source.parquet"
    connection = duckdb.connect()
    connection.execute(
        """
        CREATE TABLE source_candles AS
        SELECT * FROM (VALUES
            ('2026-01-01T00:00:00Z', 100.0, 101.0, 99.0, 100.5, 10.0),
            ('2026-01-01T00:01:00Z', 101.0, 102.0, 100.0, 101.5, 11.0)
        ) AS rows(timestamp, open, high, low, close, volume)
        """
    )
    connection.execute(f"COPY source_candles TO '{source_path.as_posix()}' (FORMAT PARQUET)")
    connection.close()

    catalog = _catalog(tmp_path)
    dataset = catalog.import_parquet(
        source_path, symbol="ETHUSDT", timeframe="1m", source="external"
    )
    assert dataset["quality_report"]["valid"] is True
    assert catalog.query_candles(dataset["version"])[0]["symbol"] == "ETHUSDT"
    catalog.close()


def test_catalog_reports_every_required_quality_failure(tmp_path: Path) -> None:
    rows = _candles(1) + [
        {
            "timestamp": "2026-01-01T00:02:00Z",
            "open": 100.0,
            "high": 90.0,
            "low": 95.0,
            "close": 0.0,
            "volume": -1.0,
        },
        {
            "timestamp": "2026-01-01T00:01:30Z",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "timestamp": "2026-01-01T00:01:30Z",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "timestamp": "2026-01-01T00:05:00Z",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        },
    ]
    catalog = _catalog(tmp_path)
    dataset = catalog.import_candles(rows, symbol="BTCUSDT", timeframe="1m", source="fixture")
    codes = {issue["code"] for issue in dataset["quality_report"]["issues"]}

    assert dataset["quality_report"]["valid"] is False
    assert {
        "invalid_price",
        "invalid_volume",
        "invalid_ohlc_relationship",
        "timestamp_descending",
        "duplicate_timestamp",
        "trading_calendar_misalignment",
        "missing_candles",
        "interval_anomaly",
    } <= codes
    catalog.close()
