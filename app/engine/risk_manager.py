"""风险管理模块。

所有策略和真实下单入口共享这里的预交易规则：单笔/单日名义金额、
单品种限制、杠杆、亏损与回撤、频率、交易时段及黑名单。
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.engine.live_trading_guard import LiveTradingGuard
from app.engine.pipeline_types import RiskDecision
from app.strategies.base import Signal


class RiskConfig(BaseModel):
    """风险配置。

    ``max_daily_order_notional`` 由 API 层通过 SQLite 原子预留实现，避免多
    请求/重启时绕过日累计限额；其余无状态规则在本管理器内统一判断。
    """

    max_position_size: float = Field(1.0, gt=0, description="最大持仓数量")
    max_position_value: float = Field(100000, gt=0, description="单笔最大名义金额")
    max_daily_order_notional: float = Field(5000, ge=0, description="单日最大下单名义金额；0 表示关闭")
    max_leverage: float = Field(5.0, ge=0, description="全局最大杠杆；0 表示不限制")
    stop_loss_pct: float = Field(0.05, gt=0, le=1, description="止损百分比")
    take_profit_pct: float = Field(0.10, gt=0, description="止盈百分比")
    max_daily_loss: float = Field(1000, gt=0, description="每日最大亏损")
    max_drawdown_pct: float = Field(0.20, gt=0, le=1, description="最大回撤百分比")
    max_orders_per_minute: int = Field(10, gt=0, description="每分钟最大订单数")
    max_consecutive_losses: int = Field(0, ge=0, description="连续亏损暂停阈值；0 表示关闭")
    blocked_symbols: tuple[str, ...] = Field(default_factory=tuple, description="禁止开新仓的交易对")
    trading_start_hour_utc: int = Field(0, ge=0, le=23, description="允许交易起始 UTC 小时")
    trading_end_hour_utc: int = Field(24, ge=1, le=24, description="允许交易结束 UTC 小时；24 表示当天结束")

    # Format: {"BTCUSDT": {"max_leverage": 3.0, "max_position_value": 500.0}}
    symbol_overrides: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Per-symbol risk overrides.",
    )


class RiskManager:
    """统一风险管理器。

    它只决定一笔订单能否进入执行流程；日累计名义金额由 SQLite 预留保证
    跨请求原子性。调用方应在幂等重放判断之后调用本类，避免重试占用频率槽。
    """

    def __init__(
        self,
        config: RiskConfig | None = None,
        trading_guard: LiveTradingGuard | None = None,
    ):
        self.config = config or RiskConfig()
        self._daily_pnl = 0.0
        self._peak_value = 0.0
        self._current_value = 0.0
        self._consecutive_losses = 0
        self._order_timestamps: list[datetime] = []
        self._trading_enabled = True
        self._guard = trading_guard
        self._lock = asyncio.Lock()

    @property
    def is_trading_enabled(self) -> bool:
        """Return whether the local kill switch permits trading."""
        if self._guard is not None:
            return not self._guard.kill_switch_enabled
        return self._trading_enabled

    @property
    def daily_pnl(self) -> float:
        """当日已实现盈亏。"""
        return self._daily_pnl

    @property
    def consecutive_losses(self) -> int:
        """当前连续亏损笔数。"""
        return self._consecutive_losses

    @property
    def current_drawdown(self) -> float:
        """当前回撤百分比。"""
        if self._peak_value == 0:
            return 0.0
        return (self._peak_value - self._current_value) / self._peak_value

    async def check_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        *,
        leverage: float | None = None,
        now: datetime | None = None,
    ) -> tuple[bool, str]:
        """检查订单是否符合统一预交易风控要求。

        只有全部非频率规则通过后才消耗一个频率槽，防止无效请求把正常订单
        挤出限额。``now`` 仅用于确定性测试，生产调用保持默认 UTC 时间。
        """
        del side  # Side is retained in the stable public API for future directional limits.
        if quantity <= 0 or price <= 0:
            return False, "订单数量和价格必须为正数"

        normalized_symbol = symbol.upper()
        check_time = now or datetime.now(UTC)
        if check_time.tzinfo is None:
            check_time = check_time.replace(tzinfo=UTC)

        async with self._lock:
            if not self.is_trading_enabled:
                return False, "交易已禁用"
            if normalized_symbol in {item.upper() for item in self.config.blocked_symbols}:
                return False, f"交易对 {normalized_symbol} 已被风险黑名单禁止"
            if not self._is_trading_hour(check_time.hour):
                return False, "当前不在允许交易时段（UTC）"

            order_value = quantity * price
            if order_value > self.config.max_position_value:
                return False, f"订单价值 {order_value} 超过限制 {self.config.max_position_value}"

            overrides = self._symbol_overrides(normalized_symbol)
            per_symbol_value_cap = overrides.get("max_position_value")
            if per_symbol_value_cap is not None and order_value > per_symbol_value_cap:
                return False, (
                    f"per-symbol max position value {per_symbol_value_cap} exceeded "
                    f"({order_value:.2f}; 单品种最大名义金额超过限制)"
                )

            if leverage is not None:
                leverage_cap = overrides.get("max_leverage", self.config.max_leverage)
                if leverage_cap > 0 and leverage > leverage_cap:
                    if "max_leverage" in overrides:
                        return False, (
                            f"per-symbol max leverage {leverage_cap}x exceeded "
                            f"({leverage}x; 单品种最大杠杆超过限制)"
                        )
                    return False, (
                        f"global max leverage {leverage_cap}x exceeded "
                        f"({leverage}x; 全局最大杠杆超过限制)"
                    )

            if self._daily_pnl < -self.config.max_daily_loss:
                return False, "触及每日最大亏损限制"
            if self.current_drawdown > self.config.max_drawdown_pct:
                return False, "触及最大回撤限制"
            if (
                self.config.max_consecutive_losses > 0
                and self._consecutive_losses >= self.config.max_consecutive_losses
            ):
                return False, "触及连续亏损暂停限制"
            if not self._check_rate_limit(check_time):
                return False, "超出交易频率限制"

            return True, "通过风控检查"

    async def check(self, signal: Signal, price: float) -> RiskDecision:
        """RiskGate port surface, returning a typed :class:`RiskDecision`."""
        quantity = signal.quantity or 0.001
        allowed, reason = await self.check_order(
            symbol=signal.symbol,
            side=signal.action.value,
            quantity=quantity,
            price=price,
        )
        if not allowed:
            return RiskDecision(allowed=False, reason=reason)

        return RiskDecision(
            allowed=True,
            reason=reason,
            stop_loss=self.calculate_stop_loss(price, signal.action.value),
            take_profit=self.calculate_take_profit(price, signal.action.value),
        )

    async def check_with_leverage(
        self,
        signal: Signal,
        price: float,
        leverage: float | None = None,
    ) -> RiskDecision:
        """Run the canonical risk check with an optional contract leverage."""
        quantity = signal.quantity or 0.001
        allowed, reason = await self.check_order(
            symbol=signal.symbol,
            side=signal.action.value,
            quantity=quantity,
            price=price,
            leverage=leverage,
        )
        if not allowed:
            return RiskDecision(allowed=False, reason=reason)
        return RiskDecision(
            allowed=True,
            reason=reason,
            stop_loss=self.calculate_stop_loss(price, signal.action.value),
            take_profit=self.calculate_take_profit(price, signal.action.value),
        )

    def _symbol_overrides(self, symbol: str) -> dict[str, float]:
        """Look up per-symbol limits case-insensitively."""
        normalized_symbol = symbol.upper()
        for configured_symbol, overrides in self.config.symbol_overrides.items():
            if configured_symbol.upper() == normalized_symbol:
                return overrides
        return {}

    def _is_trading_hour(self, hour: int) -> bool:
        """Return whether an UTC hour is within the configured half-open window."""
        start = self.config.trading_start_hour_utc
        end = self.config.trading_end_hour_utc
        if start == 0 and end == 24:
            return True
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def _check_rate_limit(self, now: datetime) -> bool:
        """Consume one frequency slot only if a slot is currently available."""
        self._order_timestamps = [
            timestamp
            for timestamp in self._order_timestamps
            if (now - timestamp).total_seconds() < 60
        ]
        if len(self._order_timestamps) >= self.config.max_orders_per_minute:
            return False
        self._order_timestamps.append(now)
        return True

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """计算止损价。"""
        if side.lower() == "buy":
            return entry_price * (1 - self.config.stop_loss_pct)
        return entry_price * (1 + self.config.stop_loss_pct)

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """计算止盈价。"""
        if side.lower() == "buy":
            return entry_price * (1 + self.config.take_profit_pct)
        return entry_price * (1 - self.config.take_profit_pct)

    def update_portfolio_value(self, value: float) -> None:
        """更新组合价值用于回撤计算。"""
        self._current_value = value
        if value > self._peak_value:
            self._peak_value = value

    def update_daily_pnl(self, pnl: float) -> None:
        """记录一笔已实现盈亏，并维护连续亏损闸门状态。"""
        self._daily_pnl += pnl
        if pnl < 0:
            self._consecutive_losses += 1
        elif pnl > 0:
            self._consecutive_losses = 0

    def reset_daily_pnl(self) -> None:
        """重置每日盈亏与连续亏损计数（每日调用）。"""
        self._daily_pnl = 0.0
        self._consecutive_losses = 0

    def enable_trading(self, reason: str | None = None) -> None:
        """启用交易。"""
        if self._guard is not None:
            self._guard.enable_trading(reason=reason)
            return
        self._trading_enabled = True

    def disable_trading(self, reason: str | None = None) -> None:
        """禁用交易。"""
        if self._guard is not None:
            self._guard.disable_trading(reason=reason)
            return
        self._trading_enabled = False

    def get_risk_status(self) -> dict[str, Any]:
        """获取风险状态。"""
        return {
            "trading_enabled": self.is_trading_enabled,
            "daily_pnl": self._daily_pnl,
            "current_drawdown": self.current_drawdown,
            "consecutive_losses": self._consecutive_losses,
            "max_daily_loss": self.config.max_daily_loss,
            "max_drawdown_pct": self.config.max_drawdown_pct,
            "max_daily_order_notional": self.config.max_daily_order_notional,
            "max_leverage": self.config.max_leverage,
            "blocked_symbols": list(self.config.blocked_symbols),
        }
