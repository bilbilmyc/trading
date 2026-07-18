"""Data-quality checks for versioned historical OHLCV datasets."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from math import isfinite


@dataclass(frozen=True)
class QualityIssue:
    """One aggregated data-quality finding."""

    code: str
    severity: str
    message: str
    count: int = 1
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DataQualityReport:
    """Deterministic report emitted whenever a dataset is imported."""

    row_count: int
    valid: bool
    issues: tuple[QualityIssue, ...]
    checks: dict[str, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "row_count": self.row_count,
            "valid": self.valid,
            "status": "passed" if self.valid else "failed",
            "issues": [issue.as_dict() for issue in self.issues],
            "checks": self.checks,
        }


def timeframe_delta(timeframe: str) -> timedelta:
    """Translate a supported candle timeframe to its UTC interval."""

    unit = timeframe[-1:]
    try:
        amount = int(timeframe[:-1])
    except ValueError as exc:
        raise ValueError("timeframe must use the form <positive integer><m|h|d|w>") from exc
    if amount <= 0 or unit not in {"m", "h", "d", "w"}:
        raise ValueError("timeframe must use the form <positive integer><m|h|d|w>")
    return {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }[unit]


def _is_calendar_aligned(timestamp: datetime, timeframe: str) -> bool:
    """Apply the built-in 24x7 UTC market calendar to a candle timestamp."""

    if timestamp.second or timestamp.microsecond:
        return False
    amount = int(timeframe[:-1])
    unit = timeframe[-1]
    if unit == "m":
        return timestamp.minute % amount == 0
    if unit == "h":
        return timestamp.minute == 0 and timestamp.hour % amount == 0
    if unit == "d":
        return timestamp.hour == 0 and timestamp.minute == 0
    return timestamp.weekday() == 0 and timestamp.hour == 0 and timestamp.minute == 0


def _append_issue(
    issues: list[QualityIssue],
    *,
    code: str,
    message: str,
    count: int = 1,
    details: dict[str, object] | None = None,
) -> None:
    issues.append(
        QualityIssue(
            code=code,
            severity="error",
            message=message,
            count=count,
            details=details or {},
        )
    )


def assess_candles(candles: Iterable[object], timeframe: str) -> DataQualityReport:
    """Validate canonical candle objects without mutating their source order.

    The catalog currently targets continuously traded instruments.  Its calendar
    policy is therefore a 24x7 UTC calendar; session-based markets should be
    imported into a future calendar-aware adapter rather than silently skipping
    gaps.
    """

    rows = list(candles)
    interval = timeframe_delta(timeframe)
    issues: list[QualityIssue] = []
    invalid_prices: Counter[str] = Counter()
    ohlc_errors = 0
    invalid_volumes = 0
    calendar_errors = 0
    descending = 0
    duplicates = 0

    previous_timestamp: datetime | None = None
    timestamps: list[datetime] = []
    for candle in rows:
        timestamp = candle.timestamp
        timestamps.append(timestamp)
        if previous_timestamp is not None:
            if timestamp < previous_timestamp:
                descending += 1
            elif timestamp == previous_timestamp:
                duplicates += 1
        previous_timestamp = timestamp

        for field_name in ("open", "high", "low", "close"):
            value = getattr(candle, field_name)
            if not isfinite(value) or value <= 0:
                invalid_prices[field_name] += 1
        if not isfinite(candle.volume) or candle.volume < 0:
            invalid_volumes += 1
        if not (
            candle.low <= candle.high
            and candle.low <= candle.open <= candle.high
            and candle.low <= candle.close <= candle.high
        ):
            ohlc_errors += 1
        if not _is_calendar_aligned(timestamp, timeframe):
            calendar_errors += 1

    for field_name, count in sorted(invalid_prices.items()):
        _append_issue(
            issues,
            code="invalid_price",
            message=f"{field_name} must be a finite value greater than zero",
            count=count,
            details={"field": field_name},
        )
    if invalid_volumes:
        _append_issue(
            issues,
            code="invalid_volume",
            message="volume must be finite and non-negative",
            count=invalid_volumes,
        )
    if ohlc_errors:
        _append_issue(
            issues,
            code="invalid_ohlc_relationship",
            message="each candle must satisfy low <= open/close <= high",
            count=ohlc_errors,
        )
    if descending:
        _append_issue(
            issues,
            code="timestamp_descending",
            message="input timestamps must be in ascending UTC order",
            count=descending,
        )
    if duplicates:
        _append_issue(
            issues,
            code="duplicate_timestamp",
            message="each dataset may contain only one candle per timestamp",
            count=duplicates,
        )
    if calendar_errors:
        _append_issue(
            issues,
            code="trading_calendar_misalignment",
            message="timestamps must align to the configured 24x7 UTC candle calendar",
            count=calendar_errors,
            details={"calendar": "24x7", "timeframe": timeframe},
        )

    unique_timestamps = sorted(set(timestamps))
    missing_candles = 0
    interval_anomalies = 0
    for before, after in zip(unique_timestamps, unique_timestamps[1:], strict=False):
        gap = after - before
        if gap == interval:
            continue
        interval_anomalies += 1
        if gap > interval and gap.total_seconds() % interval.total_seconds() == 0:
            missing_candles += int(gap / interval) - 1
    if missing_candles:
        _append_issue(
            issues,
            code="missing_candles",
            message="one or more expected candles are missing from the 24x7 UTC calendar",
            count=missing_candles,
            details={"timeframe": timeframe},
        )
    if interval_anomalies:
        _append_issue(
            issues,
            code="interval_anomaly",
            message="adjacent timestamps do not match the declared candle interval",
            count=interval_anomalies,
            details={"expected_seconds": int(interval.total_seconds())},
        )

    return DataQualityReport(
        row_count=len(rows),
        valid=not issues,
        issues=tuple(issues),
        checks={
            "timezone": "UTC required; naive timestamps are rejected during normalization",
            "trading_calendar": "24x7 UTC continuous market calendar",
            "timeframe": timeframe,
        },
    )


__all__ = ["DataQualityReport", "QualityIssue", "assess_candles", "timeframe_delta"]
