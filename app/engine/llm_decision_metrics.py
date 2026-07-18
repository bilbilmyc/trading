"""Replay-friendly effectiveness metrics for persisted AI decision events."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def effectiveness_summary(
    decisions: list[dict[str, Any]], outcomes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Summarize AI decisions using explicitly recorded post-signal outcomes.

    Outcomes are a separate immutable audit event keyed by ``decision_event_id``.
    This avoids rewriting historical model input/output while allowing MFE/MAE,
    hit-rate and model-version comparisons to be recomputed deterministically.
    """
    outcome_by_id: dict[int, dict[str, Any]] = {}
    for event in outcomes:
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        try:
            decision_id = int(details.get("decision_event_id"))
        except (TypeError, ValueError):
            continue
        outcome_by_id[decision_id] = details

    buckets = {
        "0.00-0.49": [],
        "0.50-0.69": [],
        "0.70-1.00": [],
    }
    model_values: dict[str, list[float]] = defaultdict(list)
    strategy_values: dict[str, list[float]] = defaultdict(list)
    mfe_values: list[float] = []
    mae_values: list[float] = []
    total_cost = 0.0
    cost_events = 0
    evaluated = 0
    hits = 0

    for event in decisions:
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        if details.get("failed"):
            continue
        if str(details.get("decision") or "").lower() not in {"buy", "sell"}:
            continue
        outcome = outcome_by_id.get(int(event.get("id") or 0))
        if not outcome:
            continue
        returned = _number(outcome.get("outcome_return_pct"))
        if returned is None:
            continue
        evaluated += 1
        hits += int(returned > 0)
        confidence = _number(details.get("confidence")) or 0.0
        bucket = "0.00-0.49" if confidence < 0.5 else "0.50-0.69" if confidence < 0.7 else "0.70-1.00"
        buckets[bucket].append(returned)
        model_values[str(details.get("model_version") or details.get("model") or "unknown")].append(returned)
        strategy_values[str(outcome.get("strategy_type") or "ai")].append(returned)
        mfe = _number(outcome.get("mfe_pct"))
        mae = _number(outcome.get("mae_pct"))
        if mfe is not None:
            mfe_values.append(mfe)
        if mae is not None:
            mae_values.append(mae)
        cost = _number(outcome.get("estimated_cost_usd"))
        if cost is not None:
            total_cost += cost
            cost_events += 1

    return {
        "evaluated_signals": evaluated,
        "signal_hit_rate": round(hits / evaluated * 100, 2) if evaluated else 0.0,
        "confidence_bucket_returns": [
            {
                "bucket": name,
                "signals": len(values),
                "average_return_pct": round(sum(values) / len(values), 4) if values else None,
            }
            for name, values in buckets.items()
        ],
        "average_mfe_pct": round(sum(mfe_values) / len(mfe_values), 4) if mfe_values else None,
        "average_mae_pct": round(sum(mae_values) / len(mae_values), 4) if mae_values else None,
        "ai_vs_rule": {
            name: {
                "signals": len(values),
                "average_return_pct": round(sum(values) / len(values), 4) if values else None,
            }
            for name, values in sorted(strategy_values.items())
        },
        "cost": {
            "known_cost_usd": round(total_cost, 6),
            "events_with_cost": cost_events,
            "coverage": round(cost_events / evaluated * 100, 2) if evaluated else 0.0,
        },
        "model_versions": [
            {
                "model_version": version,
                "signals": len(values),
                "hit_rate": round(sum(value > 0 for value in values) / len(values) * 100, 2),
                "average_return_pct": round(sum(values) / len(values), 4),
            }
            for version, values in sorted(model_values.items())
        ],
    }


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["effectiveness_summary"]
