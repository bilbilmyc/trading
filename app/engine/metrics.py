"""Prometheus metrics for the trading engine.

Centralizes the metric definitions and exposes a registry the `/metrics`
endpoint can render. Every counter/histogram is defined lazily on
first access so importing this module has no side effects.

The metrics follow Prometheus naming conventions (snake_case, suffix
unit):

  qt_orders_total{status, exchange, side}                 — order placements
  qt_risk_rejections_total{reason}                         — risk manager vetoes
  qt_llm_call_duration_seconds{provider, model, status}    — LLM latency
  qt_llm_tokens_total{provider, model, type}               — token usage
  qt_monitor_alerts_total{level, category}                 — alerts raised
  qt_paper_orders_total{side}                              — paper-trading fills
  qt_engine_loop_duration_seconds{loop}                    — background loop period
  qt_positions_active{exchange}                            — open positions gauge
  qt_app_info{version, env}                                — static label, set at boot
  qt_notifier_webhooks_total{outcome}                      — generic webhook deliveries
  qt_alert_dispatcher_total{provider, outcome}             — Feishu/DingTalk/WeCom bot webhooks
  qt_cache_events_total{cache, event}                      — TTL cache hits and misses

To instrument a code path, import the relevant counter and prefer the
``safe_*`` helpers so a metrics failure can never break the call site.

    from app.engine.metrics import safe_inc, ORDERS_TOTAL
    safe_inc(ORDERS_TOTAL, status="filled", exchange="binance_usdm", side="buy")

The ``safe_*`` helpers swallow every exception — metrics observation
must never crash the trading loop. Use the raw ``.labels(...).inc()``
form only when you genuinely need the underlying PrometheusError
to propagate (e.g. inside a test).

The `/metrics` endpoint is mounted in `app/api/server.py`.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Use the default global registry — single-process app, no need for
# per-module registries. If we ever shard by worker, this is the only
# place to change.
REGISTRY = CollectorRegistry(auto_describe=True)


# ── Order flow ───────────────────────────────────────────────────

ORDERS_TOTAL = Counter(
    "qt_orders_total",
    "Order placements by exchange / side / status.",
    labelnames=("exchange", "side", "status"),
    registry=REGISTRY,
)

RISK_REJECTIONS_TOTAL = Counter(
    "qt_risk_rejections_total",
    "Orders rejected by the risk manager.",
    labelnames=("reason",),
    registry=REGISTRY,
)


# ── LLM ──────────────────────────────────────────────────────────

LLM_CALL_DURATION = Histogram(
    "qt_llm_call_duration_seconds",
    "LLM provider call duration, by provider / model / outcome.",
    labelnames=("provider", "model", "status"),
    # Buckets tuned for typical LLM latency: 100ms … 30s
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
    registry=REGISTRY,
)

LLM_TOKENS_TOTAL = Counter(
    "qt_llm_tokens_total",
    "LLM token usage, by provider / model / type (prompt|completion).",
    labelnames=("provider", "model", "type"),
    registry=REGISTRY,
)


# ── Engine internals ─────────────────────────────────────────────

MONITOR_ALERTS_TOTAL = Counter(
    "qt_monitor_alerts_total",
    "Alerts raised by the monitor, by level / category.",
    labelnames=("level", "category"),
    registry=REGISTRY,
)

PAPER_ORDERS_TOTAL = Counter(
    "qt_paper_orders_total",
    "Paper-trading simulated fills, by side.",
    labelnames=("side",),
    registry=REGISTRY,
)

ENGINE_LOOP_DURATION = Histogram(
    "qt_engine_loop_duration_seconds",
    "Engine background loop period (sync, monitor, signal runner).",
    labelnames=("loop",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)


# ── Gauges (set periodically by the engine) ────────────────────

POSITIONS_ACTIVE = Gauge(
    "qt_positions_active",
    "Number of currently-open positions.",
    labelnames=("exchange",),
    registry=REGISTRY,
)

# ── App info (set once at boot) ─────────────────────────────────

APP_INFO = Gauge(
    "qt_app_info",
    "Static app info (value is always 1; labels carry metadata).",
    labelnames=("version", "env"),
    registry=REGISTRY,
)


NOTIFIER_WEBHOOKS_TOTAL = Counter(
    "qt_notifier_webhooks_total",
    "Generic webhook deliveries from WebhookNotifier, by outcome.",
    labelnames=("outcome",),
    registry=REGISTRY,
)

ALERT_DISPATCHER_TOTAL = Counter(
    "qt_alert_dispatcher_total",
    "Alert dispatcher deliveries to Feishu/DingTalk/WeCom webhooks, by provider / outcome.",
    labelnames=("provider", "outcome"),
    registry=REGISTRY,
)


CACHE_EVENTS_TOTAL = Counter(
    "qt_cache_events_total",
    "TTL cache hits and misses, by cache name.",
    labelnames=("cache", "event"),
    registry=REGISTRY,
)


# ── Safe instrumentation helpers ─────────────────────────────────
# Every call site that promotes a metrics observation needs to be
# best-effort: a counter import error or a misconfigured label must
# never crash the trading loop or the alert path. These helpers
# centralize that contract.

def safe_inc(metric: Counter, **labels: Any) -> bool:
    """Increment a Counter, swallow every exception. Returns whether it actually inc'd."""
    try:
        metric.labels(**labels).inc()
        return True
    except Exception:
        return False


def safe_observe(metric: Histogram, value: float, **labels: Any) -> bool:
    """Observe a Histogram, swallow every exception."""
    try:
        metric.labels(**labels).observe(value)
        return True
    except Exception:
        return False


def safe_set(metric: Gauge, value: float, **labels: Any) -> bool:
    """Set a Gauge, swallow every exception."""
    try:
        metric.labels(**labels).set(value)
        return True
    except Exception:
        return False


def render() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint.

    Prometheus exposition format — paste directly into Prometheus's
    scrape config or a `prometheus.yml` static_configs target.
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
