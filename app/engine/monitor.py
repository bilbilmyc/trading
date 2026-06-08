"""
监控告警模块

周期性检查引擎健康状态、风控触发、网络连接、订单异常等，
输出结构化告警事件供 API/前端/日志消费。

告警级别：
- INFO:    常规运维信息
- WARNING: 需要关注但不紧急
- ERROR:   需要立即处理
- CRITICAL: 可能导致资金损失或系统停机
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    ENGINE = "engine"
    EXCHANGE = "exchange"
    RISK = "risk"
    ORDER = "order"
    POSITION = "position"
    SIGNAL = "signal"
    SYSTEM = "system"


@dataclass
class Alert:
    """A single structured alert event."""

    level: AlertLevel
    category: AlertCategory
    title: str
    message: str
    exchange: Optional[str] = None
    symbol: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "category": self.category.value,
            "title": self.title,
            "message": self.message,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


class Monitor:
    """系统监控器

    周期性检查：
    - 引擎运行状态
    - 交易所连接健康
    - 风控触发阈值
    - 订单执行异常
    - 持仓偏离

    通过回调 / API 输出告警事件。
    """

    def __init__(self, check_interval_seconds: int = 30, max_alerts: int = 100):
        self.check_interval_seconds = check_interval_seconds
        self.max_alerts = max_alerts
        self._alerts: List[Alert] = []
        self._callbacks: List[Callable] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Checker functions registered by the engine
        self._checkers: List[Callable] = []

    # ── 生命周期 ──────────────────────────────────────────────

    def start(self) -> None:
        """Start the background monitoring loop."""

        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info(f"Monitor started (interval={self.check_interval_seconds}s)")

    async def stop(self) -> None:
        """Stop the background monitoring loop."""

        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self._push_alert(
            AlertLevel.INFO,
            AlertCategory.SYSTEM,
            "Monitor stopped",
            "Monitoring loop has been shut down.",
        )
        logger.info("Monitor stopped")

    # ── 注册 ──────────────────────────────────────────────────

    def add_checker(self, checker: Callable) -> None:
        """Register an async checker function.

        Signature: ``async def checker() -> Optional[Alert]``
        Return None if everything is OK.
        """

        self._checkers.append(checker)

    def on_alert(self, callback: Callable) -> None:
        """Register alert callback.

        Callback signature: ``async def callback(alert: Alert)``
        """

        self._callbacks.append(callback)

    # ── 告警历史 ──────────────────────────────────────────────

    def recent_alerts(self, level: Optional[AlertLevel] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent alerts, optionally filtered by level."""

        filtered = self._alerts
        if level:
            filtered = [a for a in filtered if a.level == level]
        return [a.to_dict() for a in filtered[-limit:]]

    def last_error(self) -> Optional[Dict[str, Any]]:
        """Return the most recent ERROR/CRITICAL alert, or None."""

        for alert in reversed(self._alerts):
            if alert.level in (AlertLevel.ERROR, AlertLevel.CRITICAL):
                return alert.to_dict()
        return None

    def summary(self) -> Dict[str, Any]:
        """Return a metrics snapshot of the monitor state."""

        by_level: Dict[str, int] = {}
        for alert in self._alerts:
            by_level[alert.level.value] = by_level.get(alert.level.value, 0) + 1

        return {
            "running": self._running,
            "total_alerts": len(self._alerts),
            "by_level": by_level,
            "last_alert": self._alerts[-1].to_dict() if self._alerts else None,
            "check_interval_seconds": self.check_interval_seconds,
            "max_alerts": self.max_alerts,
        }

    # ── 推送告警 ──────────────────────────────────────────────

    def push(self, alert: Alert) -> None:
        """Push an external alert into the monitor history."""

        self._push_alert(alert.level, alert.category, alert.title, alert.message, alert.exchange, alert.symbol, alert.details)

    # ── 内部 ──────────────────────────────────────────────────

    async def _check_loop(self) -> None:
        """Background monitoring loop."""

        while self._running:
            await asyncio.sleep(self.check_interval_seconds)
            for checker in self._checkers:
                try:
                    result = await checker()
                    if result is not None:
                        self._push_alert_obj(result)
                except Exception as exc:
                    self._push_alert(
                        AlertLevel.WARNING,
                        AlertCategory.SYSTEM,
                        "Checker error",
                        f"Monitor checker raised: {exc}",
                        details={"checker": str(checker)},
                    )

    def _push_alert(
        self,
        level: AlertLevel,
        category: AlertCategory,
        title: str,
        message: str,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create and store an alert, then fire callbacks."""

        alert = Alert(
            level=level,
            category=category,
            title=title,
            message=message,
            exchange=exchange,
            symbol=symbol,
            details=details or {},
        )
        self._push_alert_obj(alert)

    def _push_alert_obj(self, alert: Alert) -> None:
        """Store one alert and notify callbacks."""

        self._alerts.append(alert)
        if len(self._alerts) > self.max_alerts:
            self._alerts.pop(0)

        # Log at appropriate level
            log_levels = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.ERROR: logger.error,
            AlertLevel.CRITICAL: logger.critical,
        }
        log_fn = log_levels.get(alert.level, logger.info)
        log_fn(f"[Monitor][{alert.category.value}] {alert.title}: {alert.message}")

        # Fire callbacks
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    asyncio.ensure_future(cb(alert))
                else:
                    cb(alert)
            except Exception as exc:
                logger.warning(f"Monitor callback error: {exc}")


# ── 工厂函数 ──────────────────────────────────────────────────

def build_engine_checkers(exchanges: Dict[str, Any], engine) -> List[Callable]:
    """Build standard checkers for a TradingEngine.

    Returns a list of async callables each returning Optional[Alert].
    """

    async def _check_exchange_health() -> Optional[Alert]:
        for name, exchange in exchanges.items():
            try:
                ok = await exchange.ping()
                if not ok:
                    return Alert(
                        level=AlertLevel.ERROR,
                        category=AlertCategory.EXCHANGE,
                        title="Exchange ping failed",
                        message=f"Exchange {name} did not respond to ping.",
                        exchange=name,
                    )
            except Exception as exc:
                return Alert(
                    level=AlertLevel.CRITICAL,
                    category=AlertCategory.EXCHANGE,
                    title="Exchange connection error",
                    message=f"Exchange {name} ping raised: {exc}",
                    exchange=name,
                )
        return None

    async def _check_risk_status() -> Optional[Alert]:
        risk = await engine.risk_manager.get_risk_status()
        if not risk.get("trading_enabled", True):
            return Alert(
                level=AlertLevel.ERROR,
                category=AlertCategory.RISK,
                title="Trading disabled by risk manager",
                message=f"Daily PnL: {risk.get('daily_pnl', 0)}, Drawdown: {risk.get('current_drawdown', 0):.2%}",
                details=risk,
            )
        drawdown = risk.get("current_drawdown", 0)
        if drawdown > 0.15:
            return Alert(
                level=AlertLevel.WARNING,
                category=AlertCategory.RISK,
                title="High drawdown",
                message=f"Current drawdown is {drawdown:.2%} (threshold 15%)",
            )
        return None

    return [_check_exchange_health, _check_risk_status]
