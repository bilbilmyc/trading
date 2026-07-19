"""风险管理模块。

所有策略和真实下单入口共享这里的预交易规则：单笔/单日名义金额、
单品种限制、杠杆、亏损与回撤、频率、交易时段及黑名单。
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.engine.atr_sizing import VolatilitySnapshot, volatility_adjusted_notional_cap
from app.engine.correlation import CorrelationSnapshot
from app.engine.live_trading_guard import LiveTradingGuard
from app.engine.pipeline_types import RiskDecision
from app.engine.portfolio_exposure import PortfolioExposure
from app.strategies.base import Signal


class RiskConfig(BaseModel):
    """风险配置。

    ``max_daily_order_notional`` 由 API 层通过 SQLite 原子预留实现，避免多
    请求/重启时绕过日累计限额；其余无状态规则在本管理器内统一判断。
    """

    max_position_size: float = Field(1.0, gt=0, description="最大持仓数量")
    max_position_value: float = Field(100000, gt=0, description="单笔最大名义金额")
    max_daily_order_notional: float = Field(
        5000, ge=0, description="单日最大下单名义金额；0 表示关闭"
    )
    max_portfolio_exposure: float = Field(0, ge=0, description="组合最大总名义暴露；0 表示关闭")
    max_asset_concentration_pct: float = Field(
        0, ge=0, le=1, description="单资产最大组合暴露占比；0 表示关闭"
    )
    max_asset_group_concentration_pct: float = Field(
        0,
        ge=0,
        le=1,
        description="单资产分组最大组合暴露占比；0 表示关闭",
    )
    asset_groups: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="资产分组到标准化交易对的显式映射；同一交易对只能属于一个分组",
    )
    max_position_correlation: float = Field(
        0, ge=0, le=1, description="最大正收益相关系数；0 表示关闭"
    )
    correlation_interval: str = Field("1h", min_length=1, description="相关性 K 线周期")
    correlation_lookback_candles: int = Field(72, ge=3, le=1500, description="相关性 K 线窗口")
    correlation_min_samples: int = Field(30, ge=2, description="最少对齐收益样本")
    volatility_sizing_enabled: bool = Field(False, description="是否按 ATR 波动率收紧下单上限")
    volatility_interval: str = Field("1h", min_length=1, description="波动率 K 线周期")
    volatility_lookback_candles: int = Field(72, ge=3, le=1500, description="波动率 K 线窗口")
    volatility_atr_period: int = Field(14, ge=2, le=500, description="ATR 计算周期")
    volatility_target_atr_pct: float = Field(0.02, gt=0, le=1, description="目标 ATR 占价格比例")
    volatility_min_multiplier: float = Field(
        0.1, ge=0, le=1, description="高波动下静态上限允许缩小到的最小倍率"
    )
    max_leverage: float = Field(5.0, ge=0, description="全局最大杠杆；0 表示不限制")
    stop_loss_pct: float = Field(0.05, gt=0, le=1, description="止损百分比")
    take_profit_pct: float = Field(0.10, gt=0, description="止盈百分比")
    max_daily_loss: float = Field(1000, gt=0, description="每日最大亏损")
    max_drawdown_pct: float = Field(0.20, gt=0, le=1, description="最大回撤百分比")
    max_orders_per_minute: int = Field(10, gt=0, description="每分钟最大订单数")
    max_consecutive_losses: int = Field(0, ge=0, description="连续亏损暂停阈值；0 表示关闭")
    blocked_symbols: tuple[str, ...] = Field(
        default_factory=tuple, description="禁止开新仓的交易对"
    )
    trading_start_hour_utc: int = Field(0, ge=0, le=23, description="允许交易起始 UTC 小时")
    trading_end_hour_utc: int = Field(
        24, ge=1, le=24, description="允许交易结束 UTC 小时；24 表示当天结束"
    )

    # Format: {"BTCUSDT": {"max_leverage": 3.0, "max_position_value": 500.0}}
    symbol_overrides: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Per-symbol risk overrides.",
    )

    @field_validator("asset_groups")
    @classmethod
    def _normalize_asset_groups(
        cls, asset_groups: dict[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        """Validate a deterministic, one-group-per-symbol classification."""
        normalized_groups: dict[str, tuple[str, ...]] = {}
        assigned_symbols: set[str] = set()
        for raw_group, raw_symbols in asset_groups.items():
            group = raw_group.strip()
            if not group:
                raise ValueError("资产分组名称不能为空")
            symbols = tuple(
                dict.fromkeys(symbol.strip().upper() for symbol in raw_symbols if symbol.strip())
            )
            if not symbols:
                raise ValueError(f"资产分组 {group} 至少需要一个交易对")
            duplicate = assigned_symbols.intersection(symbols)
            if duplicate:
                rendered = ", ".join(sorted(duplicate))
                raise ValueError(f"交易对只能属于一个资产分组：{rendered}")
            assigned_symbols.update(symbols)
            normalized_groups[group] = symbols
        return normalized_groups

    @model_validator(mode="after")
    def _validate_market_data_windows(self) -> "RiskConfig":
        if self.correlation_min_samples >= self.correlation_lookback_candles:
            raise ValueError("相关性最少样本必须小于 K 线窗口")
        if self.volatility_atr_period >= self.volatility_lookback_candles:
            raise ValueError("ATR 周期必须小于波动率 K 线窗口")
        return self


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
        self._portfolio_exposure = PortfolioExposure()
        self._portfolio_exposure_provider: (
            Callable[[str, float], Awaitable[PortfolioExposure]] | None
        ) = None
        self._correlation_provider: (
            Callable[[str, str | None, str, int, int], Awaitable[CorrelationSnapshot]] | None
        ) = None
        self._correlation_snapshot: CorrelationSnapshot | None = None
        self._volatility_provider: (
            Callable[[str, str | None, str, int, int], Awaitable[VolatilitySnapshot | None]] | None
        ) = None
        self._volatility_snapshot: VolatilitySnapshot | None = None
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
        increases_exposure: bool = True,
        exchange: str | None = None,
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

        exposure = await self._current_portfolio_exposure(normalized_symbol, price)
        correlation_snapshot = None
        if increases_exposure and self.config.max_position_correlation > 0:
            correlation_snapshot = await self._current_correlation(normalized_symbol, exchange)
        volatility_snapshot = None
        if increases_exposure and self.config.volatility_sizing_enabled:
            volatility_snapshot = await self._current_volatility(normalized_symbol, exchange)

        async with self._lock:
            self._portfolio_exposure = exposure
            if not self.is_trading_enabled:
                return False, "交易已禁用"
            if normalized_symbol in {item.upper() for item in self.config.blocked_symbols}:
                return False, f"交易对 {normalized_symbol} 已被风险黑名单禁止"
            if not self._is_trading_hour(check_time.hour):
                return False, "当前不在允许交易时段（UTC）"

            order_value = quantity * price
            if order_value > self.config.max_position_value:
                return False, f"订单价值 {order_value} 超过限制 {self.config.max_position_value}"

            if increases_exposure and volatility_snapshot is not None:
                self._volatility_snapshot = volatility_snapshot
                volatility_cap, multiplier = volatility_adjusted_notional_cap(
                    self.config.max_position_value,
                    volatility_snapshot.atr_pct,
                    target_atr_pct=self.config.volatility_target_atr_pct,
                    min_multiplier=self.config.volatility_min_multiplier,
                )
                if order_value > volatility_cap:
                    return False, (
                        f"订单价值 {order_value:.2f} 超过 ATR 波动率自适应上限 "
                        f"{volatility_cap:.2f}（ATR {volatility_snapshot.atr_pct:.2%}，"
                        f"倍率 {multiplier:.2%}）"
                    )

            overrides = self._symbol_overrides(normalized_symbol)
            per_symbol_value_cap = overrides.get("max_position_value")
            if per_symbol_value_cap is not None and order_value > per_symbol_value_cap:
                return False, (
                    f"per-symbol max position value {per_symbol_value_cap} exceeded "
                    f"({order_value:.2f}; 单品种最大名义金额超过限制)"
                )

            if increases_exposure:
                projected_exposure = exposure.projected(normalized_symbol, order_value)
                if (
                    self.config.max_portfolio_exposure > 0
                    and projected_exposure.total_notional > self.config.max_portfolio_exposure
                ):
                    return False, (
                        f"组合总名义暴露 {projected_exposure.total_notional:.2f} 超过限制 "
                        f"{self.config.max_portfolio_exposure:.2f}"
                    )
                if (
                    self.config.max_asset_concentration_pct > 0
                    and exposure.total_notional > 0
                    and projected_exposure.concentration(normalized_symbol)
                    > self.config.max_asset_concentration_pct
                ):
                    return False, (
                        f"单资产 {normalized_symbol} 暴露占比 "
                        f"{projected_exposure.concentration(normalized_symbol):.2%} 超过限制 "
                        f"{self.config.max_asset_concentration_pct:.2%}"
                    )

                asset_group = self._asset_group_for_symbol(normalized_symbol)
                if (
                    self.config.max_asset_group_concentration_pct > 0
                    and exposure.total_notional > 0
                    and asset_group is not None
                ):
                    group_name, group_symbols = asset_group
                    group_concentration = projected_exposure.group_concentration(group_symbols)
                    if group_concentration > self.config.max_asset_group_concentration_pct:
                        return False, (
                            f"资产分组 {group_name} 暴露占比 "
                            f"{group_concentration:.2%} 超过限制 "
                            f"{self.config.max_asset_group_concentration_pct:.2%}"
                        )

                if correlation_snapshot is not None:
                    self._correlation_snapshot = correlation_snapshot
                    max_pair = correlation_snapshot.max_positive_pair()
                    if (
                        self.config.max_position_correlation > 0
                        and max_pair is not None
                        and max_pair[1] > self.config.max_position_correlation
                    ):
                        compared_symbol, correlation = max_pair
                        samples = correlation_snapshot.sample_sizes[compared_symbol]
                        return False, (
                            f"标的 {normalized_symbol} 与持仓 {compared_symbol} 收益相关系数 "
                            f"{correlation:.2f}（{samples} 个样本）超过限制 "
                            f"{self.config.max_position_correlation:.2f}"
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
        return await self.check_with_exchange(signal, price)

    async def check_with_exchange(
        self, signal: Signal, price: float, exchange: str | None = None
    ) -> RiskDecision:
        """Evaluate a pipeline signal with its source exchange when available."""
        quantity = signal.quantity or 0.001
        allowed, reason = await self.check_order(
            symbol=signal.symbol,
            side=signal.action.value,
            quantity=quantity,
            price=price,
            exchange=exchange,
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

    def set_portfolio_exposure_provider(
        self,
        provider: Callable[[str, float], Awaitable[PortfolioExposure]] | None,
    ) -> None:
        """Attach the engine-owned local position snapshot provider."""
        self._portfolio_exposure_provider = provider

    def set_correlation_provider(
        self,
        provider: Callable[[str, str | None, str, int, int], Awaitable[CorrelationSnapshot]] | None,
    ) -> None:
        """Attach the engine-owned aligned market-history provider."""
        self._correlation_provider = provider

    async def _current_correlation(
        self, symbol: str, exchange: str | None
    ) -> CorrelationSnapshot | None:
        if self._correlation_provider is None:
            return None
        return await self._correlation_provider(
            symbol,
            exchange,
            self.config.correlation_interval,
            self.config.correlation_lookback_candles,
            self.config.correlation_min_samples,
        )

    def set_volatility_provider(
        self,
        provider: Callable[[str, str | None, str, int, int], Awaitable[VolatilitySnapshot | None]]
        | None,
    ) -> None:
        """Attach the engine-owned ATR snapshot provider."""
        self._volatility_provider = provider

    async def _current_volatility(
        self, symbol: str, exchange: str | None
    ) -> VolatilitySnapshot | None:
        if self._volatility_provider is None:
            return None
        return await self._volatility_provider(
            symbol,
            exchange,
            self.config.volatility_interval,
            self.config.volatility_lookback_candles,
            self.config.volatility_atr_period,
        )

    async def _current_portfolio_exposure(self, symbol: str, price: float) -> PortfolioExposure:
        """Read current gross exposure without coupling the risk layer to positions."""
        if self._portfolio_exposure_provider is None:
            return self._portfolio_exposure
        return await self._portfolio_exposure_provider(symbol, price)

    def _symbol_overrides(self, symbol: str) -> dict[str, float]:
        """Look up per-symbol limits case-insensitively."""
        normalized_symbol = symbol.upper()
        for configured_symbol, overrides in self.config.symbol_overrides.items():
            if configured_symbol.upper() == normalized_symbol:
                return overrides
        return {}

    def _asset_group_for_symbol(self, symbol: str) -> tuple[str, tuple[str, ...]] | None:
        """Return the explicit asset group that contains a normalized symbol."""
        normalized_symbol = symbol.upper()
        for group_name, symbols in self.config.asset_groups.items():
            if normalized_symbol in symbols:
                return group_name, symbols
        return None

    def _asset_group_exposure(self, exposure: PortfolioExposure) -> dict[str, dict[str, float]]:
        """Build JSON-safe configured group exposure state for status consumers."""
        return {
            group_name: {
                "notional": exposure.group_notional(symbols),
                "concentration": exposure.group_concentration(symbols),
            }
            for group_name, symbols in sorted(self.config.asset_groups.items())
        }

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

    async def get_risk_status(self) -> dict[str, Any]:
        """获取包含本地组合暴露快照的风险状态。"""
        exposure = await self._current_portfolio_exposure("", 0.0)
        async with self._lock:
            self._portfolio_exposure = exposure
            return {
                "trading_enabled": self.is_trading_enabled,
                "daily_pnl": self._daily_pnl,
                "current_drawdown": self.current_drawdown,
                "consecutive_losses": self._consecutive_losses,
                "max_daily_loss": self.config.max_daily_loss,
                "max_drawdown_pct": self.config.max_drawdown_pct,
                "max_daily_order_notional": self.config.max_daily_order_notional,
                "orders_last_minute": len(self._order_timestamps),
                "max_orders_per_minute": self.config.max_orders_per_minute,
                "max_portfolio_exposure": self.config.max_portfolio_exposure,
                "max_asset_concentration_pct": self.config.max_asset_concentration_pct,
                "max_asset_group_concentration_pct": self.config.max_asset_group_concentration_pct,
                "max_position_correlation": self.config.max_position_correlation,
                "correlation_interval": self.config.correlation_interval,
                "correlation_lookback_candles": self.config.correlation_lookback_candles,
                "correlation_min_samples": self.config.correlation_min_samples,
                "correlation_snapshot": self._correlation_snapshot.as_dict()
                if self._correlation_snapshot
                else None,
                "volatility_sizing_enabled": self.config.volatility_sizing_enabled,
                "volatility_interval": self.config.volatility_interval,
                "volatility_lookback_candles": self.config.volatility_lookback_candles,
                "volatility_atr_period": self.config.volatility_atr_period,
                "volatility_target_atr_pct": self.config.volatility_target_atr_pct,
                "volatility_min_multiplier": self.config.volatility_min_multiplier,
                "volatility_snapshot": self._volatility_snapshot.as_dict()
                if self._volatility_snapshot
                else None,
                "asset_groups": {
                    name: list(symbols)
                    for name, symbols in sorted(self.config.asset_groups.items())
                },
                "asset_group_exposure": self._asset_group_exposure(exposure),
                "portfolio_exposure": exposure.as_dict(),
                "max_leverage": self.config.max_leverage,
                "blocked_symbols": list(self.config.blocked_symbols),
            }
