"""
FastAPI HTTP 入口。

读这层代码时可以按下面的调用链理解：

1. `main.py api` 启动 uvicorn，uvicorn 调用这里的 `create_app()`。
2. `create_app()` 创建一个 `AppState`，里面放配置、SQLite、交易引擎和交易所客户端缓存。
3. 每个 `@app.get/post/delete(...)` 都是一个 HTTP 路由处理函数。
4. 路由参数里的 `state: AppState = Depends(get_state)` 是 FastAPI 依赖注入：
   请求进来时，FastAPI 先调用 `get_state()`，再把同一个 `AppState` 传给路由函数。
5. 路由函数通常先从 `state` 取 engine/store/exchange，再调用具体业务方法。
"""

import hashlib
import json
import platform
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import require_api_key
from app.api.cache import TTLCache
from app.api.helpers import (
    ensure_client_order_id,
    ensure_contract_client_order_id,
    execution_fingerprint,
    extract_order_id,
    infer_liquidity,
)
from app.api.middleware import ScopeContextMiddleware
from app.api.schemas import (
    AIAnalyzeRequest,
    AIDecisionOutcomeRequest,
    BacktestRequest,
    BootstrapBacktestRequest,
    BotAutopilotOrderRequest,
    ClosePositionRequest,
    CustomSourceRequest,
    GridSearchRequest,
    InOutSampleBacktestRequest,
    KillSwitchRequest,
    LLMStrategyCreateRequest,
    MarketDataImportRequest,
    MonteCarloBacktestRequest,
    OrderRequest,
    PaperResetRequest,
    ParameterSensitivityRequest,
    PortfolioBacktestRequest,
    ReconciliationRecoveryRequest,
    RollingBacktestRequest,
    SignalRunnerRequest,
    SizingRequest,
    SMAStrategyRequest,
    StrategyModeRequest,
    StrategyPromotionDecisionRequest,
    StrategyPromotionEvaluateRequest,
    SuggestRequest,
    WalkForwardRequest,
)
from app.bot.autopilot import analyze_multi_timeframe
from app.core.logging import setup_logger
from app.core.sqlite_store import SQLiteStore
from app.data_sources.generic_http import GenericHttpDataSource
from app.engine.live_trading_guard import LiveTradingGuard
from app.engine.llm_decision_metrics import effectiveness_summary
from app.engine.risk_manager import RiskConfig
from app.engine.trader import TradingEngine
from app.exchanges.base import ExchangeBase
from app.exchanges.contract_base import ContractExchangeBase
from app.exchanges.factory import ExchangeFactory
from app.market_data import (
    DatasetNotFoundError,
    DatasetQualityError,
    MarketDataCatalog,
    MarketDataError,
)
from app.models.contract import ContractOrderRequest, LiquidityType, MarginMode, PositionSide
from app.models.order import Order, OrderSide, OrderStatus, OrderType
from app.strategies.sma import SMAStrategy
from config import Settings, load_settings

T = TypeVar("T")


def _bot_status_payload(settings: Settings) -> dict[str, Any]:
    """Serialize the bot config to a frontend-safe dict.

    Only the *last 4* characters of the Telegram token are exposed; this is
    useful for the user to confirm "is my bot online" without leaking the
    bearer secret that the bot uses to talk to the engine. Quiet hours
    round-trip as a 2-tuple or `None` to keep JSON simple.
    """
    bot = settings.bot
    token = bot.telegram_token or ""
    return {
        "enabled": bool(bot.enabled),
        "allowed_chat_ids": list(bot.allowed_chat_ids),
        "token_tail": (token[-4:] if token and len(token) >= 4 else None),
        "quiet_hours": list(bot.quiet_hours) if bot.quiet_hours is not None else None,
        "min_alert_level": bot.min_alert_level,
        "alert_fingerprint_cooldown_seconds": bot.alert_fingerprint_cooldown_seconds,
        "autopilot": {
            "analysis_enabled": bool(bot.autopilot_enabled),
            "live_order_enabled": bool(bot.autopilot_live_order_enabled),
            "exchange": bot.autopilot_exchange,
            "symbols": list(bot.autopilot_symbols),
            "cycle_seconds": bot.autopilot_cycle_seconds,
            "min_return_pct": bot.autopilot_min_return_pct,
            "max_order_notional": bot.autopilot_max_order_notional,
            "max_daily_notional": bot.autopilot_max_daily_notional,
        },
    }


class AppState:
    """一个 API worker 内共享的运行时对象。

    你可以把它理解成“后端服务的内存上下文”：
    - settings：环境配置和交易所开关。
    - store：SQLite 持久化入口。
    - engine：策略、风控、模拟盘、订单同步等核心业务。
    - exchanges：交易所客户端缓存，避免每个请求都重新创建 HTTP 客户端。

    注意：如果 uvicorn 使用多个 worker，每个 worker 都会有自己的 AppState。
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = SQLiteStore(settings.sqlite_path)
        self.market_data = MarketDataCatalog(
            settings.market_data_catalog_path, settings.market_data_parquet_dir
        )
        self.trading_guard = LiveTradingGuard(live_trading_enabled=settings.enable_live_trading)
        self.engine = TradingEngine(
            risk_config=RiskConfig(**settings.risk.model_dump()),
            trading_guard=self.trading_guard,
            max_concurrent_orders=5,
            store=self.store,
            llm_allowed_symbols=settings.llm_allowed_symbols or None,
        )
        if self.engine.restore_persisted_strategies() == 0:
            self.engine.add_strategy(
                "sma_5_20_btcusdt",
                SMAStrategy(short_window=5, long_window=20),
                exchange="binance_usdm",
                symbol="BTCUSDT",
                interval="1m",
                enabled=False,
                mode="signal",
            )
        # Persist sync outcomes back to the durable execution-intent ledger,
        # then restore every non-terminal intent after a process restart.
        self.engine.order_sync.on_sync(self._persist_execution_intent_from_sync)
        self.engine.position_sync.on_reconciliation(self._persist_reconciliation_outcome)
        self._restore_execution_intents()
        self._restore_reconciliation_blocks()
        # Two-layer exchange registry (ADR-0003):
        # - data_sources: public market data only, no auth required.
        # - trading_exchanges: private + order operations, require keys + flag.
        # ExchangeBase already implements the DataSource surface, so existing
        # adapters serve both roles once registered.
        self.exchanges: dict[str, ExchangeBase] = {}
        self.data_sources: dict[str, ExchangeBase] = {}
        self.trading_exchanges: dict[str, ExchangeBase] = {}
        # User-registered custom data sources (any HTTP API via GenericHttpDataSource).
        self.custom_sources: dict[str, Any] = {}
        # In-process TTL cache for slow endpoints (config / capabilities / venues).
        # `name` propagates to qt_cache_events_total{cache="config"`.

        self.cache = TTLCache(name="config", default_ttl=30.0)
        # Separate cache for ticker snapshots so the heavy `get_ticker`
        # calls on the default exchange don't pile up at the same TTL
        # boundary as /config. Counter shows up as cache="ticker24h".
        self.ticker_cache = TTLCache(name="ticker24h", default_ttl=20.0)
        self._register_data_sources()
        self._register_trading_exchanges()

    def _register_data_sources(self) -> None:
        """Register every enabled exchange as a data source.

        Public endpoints (ticker, klines, trades, contracts) work without
        any API key, so we register the client regardless of credentials.
        """
        for name in ExchangeFactory.list_supported_exchanges():
            exchange_settings = self.settings.exchange(name)
            if exchange_settings is None or not exchange_settings.enabled:
                continue
            try:
                exchange = ExchangeFactory.get_or_create(
                    name,
                    api_key=exchange_settings.api_key,
                    secret_key=exchange_settings.secret_key,
                    passphrase=exchange_settings.passphrase,
                    use_testnet=exchange_settings.use_testnet,
                )
            except Exception:
                # Don't let a single bad adapter prevent the app from booting.
                continue
            self.data_sources[name] = exchange
            self.engine.add_exchange(name, exchange)
            # Also cache for the legacy get_exchange() path used by trading routes.
            self.exchanges[name] = exchange

    def _register_trading_exchanges(self) -> None:
        """Promote data sources that have keys + flag to trading exchanges.

        Trading requires BOTH `enable_live_trading=true` AND a non-empty
        API key. The promotion is one-way: removing keys later does not
        demote, but a restart resets state.
        """
        if not self.settings.enable_live_trading:
            return
        for name, exchange in list(self.data_sources.items()):
            exchange_settings = self.settings.exchange(name)
            if exchange_settings is None or not exchange_settings.api_key:
                continue
            self.trading_exchanges[name] = exchange

    def get_exchange(self, name: str) -> ExchangeBase:
        """按需创建交易所客户端。

        API 路由不会直接 new Binance/Bitget/OKX，而是统一走这里：
        1. 检查该交易所是否启用。
        2. 第一次请求时通过 ExchangeFactory 创建客户端。
        3. 缓存在 self.exchanges，后续请求复用。
        4. 同时注册到 TradingEngine，策略执行时也能找到同一个客户端。
        """

        exchange_name = name.lower()
        if exchange_name in self.exchanges:
            return self.exchanges[exchange_name]

        exchange_settings = self.settings.exchange(exchange_name)
        if exchange_settings is None or not exchange_settings.enabled:
            raise HTTPException(status_code=404, detail=f"Exchange is not enabled: {name}")

        # ExchangeFactory 负责根据名字选择适配器，例如 binance_usdm -> BinanceUSDMExchange。
        # 这里不写 if/else，是为了让 API 层不关心每家交易所的构造细节。
        exchange = ExchangeFactory.get_or_create(
            exchange_name,
            api_key=exchange_settings.api_key,
            secret_key=exchange_settings.secret_key,
            passphrase=exchange_settings.passphrase,
            use_testnet=exchange_settings.use_testnet,
        )
        self.exchanges[exchange_name] = exchange
        self.engine.add_exchange(exchange_name, exchange)
        return exchange

    def get_contract_exchange(self, name: str) -> ContractExchangeBase:
        """取得“合约交易所”客户端。

        有些适配器只支持现货，有些支持永续合约。合约相关 API 统一走这里，
        如果客户端不是 ContractExchangeBase，就直接返回 400。
        """

        exchange = self.get_exchange(name)
        if not isinstance(exchange, ContractExchangeBase):
            raise HTTPException(status_code=400, detail=f"Exchange is not contract-capable: {name}")
        return exchange

    def _restore_execution_intents(self) -> None:
        """Reload durable, non-terminal submissions into the reconciliation loop."""

        for intent in self.store.pending_execution_intents():
            self._track_execution_intent(intent["client_order_id"])

    def _restore_reconciliation_blocks(self) -> None:
        """Keep critical account discrepancies fail-closed across restarts."""

        self.engine.account_reconciliation.restore(self.store.reconciliation_issues(status="open"))

    async def _persist_reconciliation_outcome(self, outcome) -> None:
        """Persist authoritative account snapshots and trigger venue-local blocks."""

        payload = outcome.as_dict()
        self.store.append_account_snapshot(payload)
        # A synchronized quote-currency balance is the authoritative baseline
        # for drawdown.  Post-trade attribution applies realized PnL between
        # these reconciliation snapshots.
        quote_value = sum(
            float(balance.get("total", 0) or 0)
            for balance in outcome.balances
            if str(balance.get("currency", "")).upper() in {"USD", "USDT", "USDC"}
        )
        if quote_value > 0:
            self.engine.risk_manager.update_portfolio_value(quote_value)
        self.store.upsert_reconciliation_issues(outcome.exchange, outcome.issues)
        if self.engine.account_reconciliation.observe(outcome):
            self.store.append_event(
                {
                    "category": "risk",
                    "event_type": "account_reconciliation_blocked",
                    "level": "critical",
                    "exchange": outcome.exchange,
                    "message": "New exposure blocked due to account/position reconciliation discrepancy",
                    "details": {"issues": outcome.issues},
                    "timestamp": outcome.completed_at,
                }
            )

    def _track_execution_intent(self, client_order_id: str) -> Order | None:
        """Build an order from a durable intent and enroll non-terminals in sync."""

        intent = self.store.get_execution_intent(client_order_id)
        if intent is None:
            return None
        try:
            status = OrderStatus(intent["status"])
        except ValueError:
            status = OrderStatus.UNKNOWN
        try:
            side = OrderSide(str(intent["side"]).lower())
        except ValueError:
            return None
        order_type = (
            OrderType.MARKET if str(intent["order_type"]).lower() == "market" else OrderType.LIMIT
        )
        response = intent.get("response") or {}
        try:
            filled_quantity = max(
                0.0,
                float(
                    response.get(
                        "filled_quantity", response.get("executedQty", response.get("filled", 0))
                    )
                    or 0
                ),
            )
        except (TypeError, ValueError):
            filled_quantity = 0.0
        try:
            raw_average = response.get(
                "avg_fill_price", response.get("avgPrice", response.get("average"))
            )
            average_price = float(raw_average) if raw_average not in (None, "", "0", 0) else None
        except (TypeError, ValueError):
            average_price = None
        order = Order(
            order_id=intent.get("exchange_order_id"),
            client_order_id=intent["client_order_id"],
            exchange=intent["exchange"],
            symbol=intent["symbol"],
            side=side,
            order_type=order_type,
            quantity=float(intent["quantity"]),
            price=intent.get("price"),
            status=status,
            filled_quantity=filled_quantity,
            avg_fill_price=average_price,
        )
        if status not in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }:
            self.engine.order_sync.track(order)
        return order

    async def track_execution_intent(self, client_order_id: str) -> None:
        """Track an intent and immediately attribute any confirmed response fill."""

        order = self._track_execution_intent(client_order_id)
        if order is None:
            return
        attribution = await self.engine.post_trade_attributor.record_order(order)
        if attribution is not None:
            self.store.append_event(
                {
                    "category": "risk",
                    "event_type": "post_trade_risk_attributed",
                    "level": "info",
                    "exchange": attribution.exchange,
                    "symbol": attribution.symbol,
                    "order_id": order.order_id or client_order_id,
                    "message": "Confirmed fill attributed to post-trade risk state",
                    "details": attribution.as_dict(),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    async def _persist_execution_intent_from_sync(self, order: Order, changed: bool) -> None:
        """Reflect reconciliation results in SQLite without blocking order sync."""

        if not order.client_order_id:
            return
        status = order.status.value if isinstance(order.status, OrderStatus) else str(order.status)
        self.store.update_execution_intent(
            order.client_order_id,
            status=status,
            exchange_order_id=order.order_id,
            clear_error=status not in {OrderStatus.SUBMITTING.value, OrderStatus.UNKNOWN.value},
        )
        attribution = await self.engine.post_trade_attributor.record_order(order)
        if attribution is not None:
            self.store.append_event(
                {
                    "category": "risk",
                    "event_type": "post_trade_risk_attributed",
                    "level": "info",
                    "exchange": attribution.exchange,
                    "symbol": attribution.symbol,
                    "order_id": order.order_id or order.client_order_id,
                    "message": "Confirmed synchronized fill attributed to post-trade risk state",
                    "details": attribution.as_dict(),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    def ensure_strategy_exchanges(self) -> None:
        """策略运行前，先把策略配置里需要的交易所客户端创建好。"""

        for strategy in self.engine.list_strategies():
            exchange_name = strategy.get("exchange")
            if exchange_name:
                self.get_exchange(str(exchange_name))

    async def close(self) -> None:
        """API worker 关闭时释放交易所连接和 SQLite 连接。"""

        for exchange in self.exchanges.values():
            await exchange.close()
        self.exchanges.clear()
        self.market_data.close()
        self.store.close()


def get_settings() -> Settings:
    return load_settings()


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。

    这是整个 HTTP 服务的装配点：配置日志、创建 AppState、注册中间件、
    定义路由，然后把 app 返回给 uvicorn。
    """

    settings = settings or load_settings()
    setup_logger(settings.log_level)
    state = AppState(settings)

    # Wire alert dispatcher (Feishu / DingTalk / WeCom webhooks) into
    # the monitor. Disabled-by-default — providers are only enabled when
    # their webhook URL is set in .env. See docs/alerts.md.
    from loguru import logger as _loguru_logger

    from app.engine.alert_dispatcher import AlertDispatcher, DispatcherConfig
    from app.engine.monitor import AlertLevel as _AlertLevel

    try:
        min_level = _AlertLevel(settings.alert_min_level.lower())
    except ValueError:
        min_level = _AlertLevel.WARNING

    _dispatcher = AlertDispatcher(
        DispatcherConfig(
            min_level=min_level,
            feishu_url=settings.alert_feishu_webhook,
            dingtalk_url=settings.alert_dingtalk_webhook,
            wecom_url=settings.alert_wecom_webhook,
            http_timeout=settings.alert_http_timeout,
        )
    )
    if _dispatcher.providers:
        state.engine.monitor.on_alert(_dispatcher.handle_alert)
        _loguru_logger.info(
            f"Alert dispatcher wired to {len(_dispatcher.providers)} provider(s) "
            f"(min_level={min_level.value})"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # lifespan 是 FastAPI 的启动/关闭钩子。
        # 启动时把 state 挂到 app.state，便于调试；关闭时统一释放资源。
        # Stamp APP_INFO gauge so Prometheus picks up version + env labels.
        from app.engine.metrics import APP_INFO

        APP_INFO.labels(version=app.version, env=settings.app_env).set(1)

        app.state.trading = state
        yield
        await state.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    # GZip compression for JSON responses — large payloads (klines, audit
    # events, portfolio metrics) shrink dramatically. Free perf win.
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=512)
    # Tag every request with X-Bot-Scope so audit logs can distinguish
    # bot calls from web-ui calls.
    app.add_middleware(ScopeContextMiddleware)

    # 前端开发时 Vite 跑在 5180，浏览器会跨端口调用 8000 的 API。
    # CORS 只放开本地前端地址，不把 API 暴露给任意网站。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5180",
            "http://localhost:5180",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_state() -> AppState:
        # FastAPI 的 Depends(get_state) 会调用这个函数，并把返回值注入到路由参数。
        # 因为这里闭包捕获了 create_app() 里创建的 state，所以所有路由拿到的是同一个对象。
        return state

    async def call_exchange(
        operation: Callable[[], Awaitable[T]],
        *,
        is_private: bool = False,
    ) -> T:
        """统一包装交易所调用，把网络/交易所异常转换成 HTTP 响应。

        路由里常见写法：

            client = state.get_exchange(exchange)
            return await call_exchange(lambda: client.get_ticker(symbol))

        当 is_private=True 时，错误分类为 "private"（账户/订单/杠杆），前端可以按
        类别决定是否提示用户检查 API Key。公开行情失败时分类为 "public"，
        不应因为缺少 API Key 就阻断前端使用。
        """

        category = "private" if is_private else "public"
        try:
            return await operation()
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": str(exc),
                    "error_category": category,
                },
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail: Any
            try:
                detail = exc.response.json()
            except ValueError:
                detail = exc.response.text or exc.response.reason_phrase
            body: dict[str, Any] = {
                "message": "Exchange returned an error response",
                "error_category": category,
                "status_code": exc.response.status_code,
                "exchange_detail": detail,
            }
            if is_private and exc.response.status_code in (401, 403):
                body["hint"] = (
                    "请检查 .env 中对应交易所的 API Key / Secret 是否正确配置，以及账户权限是否足够。"
                )
            raise HTTPException(status_code=502, detail=body) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": f"Exchange network error: {exc.__class__.__name__}",
                    "error_category": category,
                },
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": str(exc),
                    "error_category": category,
                },
            ) from exc

    async def build_contract_order_preview(request: ContractOrderRequest) -> dict[str, Any]:
        """构建合约下单预览，不产生任何交易所状态变更。"""

        preview_request = ensure_contract_client_order_id(request)
        client = state.get_contract_exchange(preview_request.exchange)
        side, inferred_position_side, inferred_reduce_only = client.resolve_order_intent(
            preview_request.intent
        )
        position_side = (
            preview_request.position_side
            if preview_request.position_side != PositionSide.NET
            else inferred_position_side
        )
        reduce_only = (
            inferred_reduce_only
            if preview_request.reduce_only is None
            else preview_request.reduce_only
        )
        liquidity = infer_liquidity(preview_request.order_type)
        notes = [
            "这是下单前预览，不会向交易所提交订单。",
            "强平风险需要结合交易所保证金、仓位和维护保证金率计算，这里只做风险提示。",
        ]

        preview_price = preview_request.price
        if preview_price is None:
            try:
                ticker = await call_exchange(lambda: client.get_ticker(preview_request.symbol))
                preview_price = float(ticker.get("last_price") or 0)
                notes.append("市价单预览使用当前 ticker last_price 估算名义价值。")
            except HTTPException as exc:
                notes.append(f"无法获取市价单参考价格：{exc.detail}")
        if not preview_price or preview_price <= 0:
            raise HTTPException(status_code=400, detail="price is required for order preview")

        notional = preview_request.quantity * preview_price
        leverage = preview_request.leverage or 1
        initial_margin = notional / leverage if leverage > 0 else notional
        fee_rate = None
        estimated_fee = None
        try:
            fee = await call_exchange(lambda: client.get_fee_rate(preview_request.symbol))
            fee_rate = fee.maker if liquidity == LiquidityType.MAKER else fee.taker
            estimated_fee = notional * abs(fee_rate)
        except HTTPException as exc:
            notes.append(f"未能获取实时手续费率：{exc.detail}")

        return {
            "exchange": preview_request.exchange,
            "symbol": preview_request.symbol,
            "intent": preview_request.intent.value,
            "side": side,
            "quantity": preview_request.quantity,
            "order_type": preview_request.order_type.lower(),
            "price": preview_price,
            "notional": notional,
            "leverage": leverage,
            "initial_margin": initial_margin,
            "margin_mode": preview_request.margin_mode.value,
            "position_side": position_side.value,
            "reduce_only": reduce_only,
            "liquidity": liquidity.value,
            "fee_rate": fee_rate,
            "estimated_fee": estimated_fee,
            "client_order_id": preview_request.client_order_id,
            "live_trading_enabled": state.settings.enable_live_trading,
            "liquidation_risk_note": "预览不是强平价计算；高杠杆、全仓和市价单会放大强平与滑点风险。",
            "notes": notes,
            "request": preview_request.model_dump(mode="json"),
        }

    def record_event(
        *,
        category: str,
        event_type: str,
        message: str,
        level: str = "info",
        exchange: str | None = None,
        symbol: str | None = None,
        strategy: str | None = None,
        order_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        # 订单/风控事件统一写 SQLite。前端右侧“审计事件”面板读取的就是这张表。
        state.store.append_event(
            {
                "category": category,
                "event_type": event_type,
                "level": level,
                "exchange": exchange,
                "symbol": symbol,
                "strategy": strategy,
                "order_id": order_id,
                "message": message,
                "details": details or {},
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    def reject_pretrade_risk(
        *,
        action: str,
        reason: str,
        exchange: str,
        symbol: str,
        details: dict[str, Any],
        order_id: str | None = None,
    ) -> None:
        """Persist a machine-readable pre-trade rejection before returning 422."""
        record_event(
            category="risk",
            event_type="risk_order_blocked",
            level="warning",
            exchange=exchange,
            symbol=symbol,
            order_id=order_id,
            message=f"Pre-trade risk blocked {action}: {reason}",
            details={"action": action, "reason": reason, **details},
        )
        raise HTTPException(status_code=422, detail=f"Pre-trade risk check failed: {reason}")

    async def resolve_reference_price(
        *,
        client: ExchangeBase,
        symbol: str,
        quantity: float,
        limit_price: float | None,
        quote_order_qty: float | None = None,
    ) -> float:
        """Return a conservative notional reference without trusting caller input alone."""
        if limit_price is not None:
            return float(limit_price)
        if quote_order_qty is not None:
            return float(quote_order_qty) / quantity

        ticker = await call_exchange(lambda: client.get_ticker(symbol))
        for field in ("last_price", "price", "last"):
            try:
                reference_price = float(ticker.get(field) or 0.0)
            except (AttributeError, TypeError, ValueError):
                reference_price = 0.0
            if reference_price > 0:
                return reference_price
        raise HTTPException(
            status_code=502, detail="Cannot obtain a valid reference price for risk check"
        )

    async def ensure_pretrade_risk(
        *,
        action: str,
        exchange: str,
        symbol: str,
        side: str,
        quantity: float,
        reference_price: float,
        details: dict[str, Any],
        leverage: float | None = None,
        increases_exposure: bool = True,
    ) -> None:
        """Apply the canonical in-memory rules shared by every live order route."""
        allowed, reason = await state.engine.risk_manager.check_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=reference_price,
            leverage=leverage,
            increases_exposure=increases_exposure,
            exchange=exchange,
        )
        if not allowed:
            reject_pretrade_risk(
                action=action,
                reason=reason,
                exchange=exchange,
                symbol=symbol,
                details={
                    **details,
                    "reference_price": reference_price,
                    "notional": quantity * reference_price,
                    "leverage": leverage,
                },
            )

    def reserve_shared_daily_notional(
        *,
        action: str,
        client_order_id: str,
        exchange: str,
        symbol: str,
        notional: float,
        details: dict[str, Any],
    ) -> None:
        """Atomically reserve the configured cross-route daily live-trading budget."""
        maximum = state.engine.risk_manager.config.max_daily_order_notional
        if maximum <= 0:
            return
        allowed, used_before, _ = state.store.reserve_risk_daily_notional(
            client_order_id=client_order_id,
            budget_date=datetime.now(UTC).date().isoformat(),
            notional=notional,
            maximum_notional=maximum,
            created_at=datetime.now(UTC).isoformat(),
        )
        if not allowed:
            reject_pretrade_risk(
                action=action,
                reason="触及单日最大下单名义金额限制",
                exchange=exchange,
                symbol=symbol,
                order_id=client_order_id,
                details={
                    **details,
                    "notional": notional,
                    "daily_notional_before": used_before,
                    "daily_notional_limit": maximum,
                },
            )

    def _intent_status_from_response(response: dict[str, Any]) -> str:
        raw = str(response.get("status") or response.get("state") or "submitted").lower()
        mapping = {
            "new": "pending",
            "open": "pending",
            "live": "pending",
            "pending": "pending",
            "partially_filled": "partially_filled",
            "partial": "partially_filled",
            "filled": "filled",
            "closed": "filled",
            "cancelled": "cancelled",
            "canceled": "cancelled",
            "rejected": "rejected",
            "expired": "expired",
            "submitting": "submitting",
            "submitted": "submitted",
            "unknown": "unknown",
        }
        return mapping.get(raw, "submitted")

    def _existing_execution_intent(
        *,
        client_order_id: str,
        request: Any,
    ) -> dict[str, Any] | None:
        """Return a validated replay before risk checks without creating an intent.

        A newly blocked request must never leave a durable ``submitting`` intent.
        The actual claim happens only after risk approval and budget reservation.
        """
        existing = state.store.get_execution_intent(client_order_id)
        if existing is None:
            return None
        if existing["fingerprint"] != execution_fingerprint(request):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "client_order_id was already used for a different order request.",
                    "client_order_id": client_order_id,
                },
            )
        return existing

    def _claim_execution_intent(
        *,
        client_order_id: str,
        request: Any,
        side: str,
    ) -> dict[str, Any] | None:
        """Atomically reserve an order key before touching an exchange.

        A repeat with identical economic parameters returns the existing durable
        result. Reusing a key for different parameters is rejected explicitly.
        """

        fingerprint = execution_fingerprint(request)
        existing = state.store.get_execution_intent(client_order_id)
        if existing is not None:
            if existing["fingerprint"] != fingerprint:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "client_order_id was already used for a different order request.",
                        "client_order_id": client_order_id,
                    },
                )
            return existing

        now = datetime.utcnow().isoformat()
        created = state.store.create_execution_intent(
            {
                "client_order_id": client_order_id,
                "fingerprint": fingerprint,
                "exchange": request.exchange,
                "symbol": request.symbol,
                "side": side,
                "order_type": request.order_type,
                "quantity": request.quantity,
                "price": request.price,
                "status": "submitting",
                "request": request.model_dump(mode="json"),
                "created_at": now,
                "updated_at": now,
            }
        )
        if created:
            return None

        # A concurrent request claimed it first. Read the winner and apply the
        # same fingerprint rule rather than issuing a second external request.
        existing = state.store.get_execution_intent(client_order_id)
        if existing is None:
            raise HTTPException(status_code=503, detail="Unable to reserve order idempotency key.")
        if existing["fingerprint"] != fingerprint:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "client_order_id was already used for a different order request.",
                    "client_order_id": client_order_id,
                },
            )
        return existing

    def _replay_execution_intent(intent: dict[str, Any]) -> dict[str, Any]:
        response = dict(intent.get("response") or {})
        response.setdefault("order_id", intent.get("exchange_order_id"))
        response.update(
            {
                "client_order_id": intent["client_order_id"],
                "execution_status": intent["status"],
                "idempotent_replay": True,
                "reconciliation_required": intent["status"] in {"submitting", "unknown"},
            }
        )
        return response

    async def _mark_submission_unknown(
        *,
        request: Any,
        action: str,
        error: HTTPException,
    ) -> None:
        state.store.update_execution_intent(
            request.client_order_id,
            status="unknown",
            last_error=str(error.detail),
        )
        await state.track_execution_intent(request.client_order_id)
        record_event(
            category="order",
            event_type=f"{action}_submission_unknown",
            level="warning",
            exchange=request.exchange,
            symbol=request.symbol,
            order_id=request.client_order_id,
            message="Order submission outcome is unknown; reconciliation is required before retrying.",
            details={"request": request.model_dump(mode="json"), "exchange_error": error.detail},
        )

    async def _on_llm_decision(payload: dict[str, Any]) -> None:
        """Observer for LLMAnalyzer — persists every fresh decision (and
        LLMError) to the events table so the right-hand audit panel can
        show "why did the model say hold?" alongside orders and risk
        transitions.

        Failures here are swallowed by LLMAnalyzer itself (audit must
        never block the trading path). Errors writing to the store are
        additionally guarded here so the closure is safe to await.
        """
        # Failed LLM calls get level=warning so they stand out from
        # successful 'hold' (low-confidence neutral) decisions.
        level = "warning" if payload.get("failed") else "info"
        decision = payload.get("decision") or "hold"
        confidence = payload.get("confidence")
        reason = payload.get("reason") or ""
        message = (
            f"LLM → {decision}"
            f"{f' (conf={confidence:.2f})' if isinstance(confidence, (int, float)) else ''}"
            f"{f' — {reason}' if reason else ''}"
        )
        try:
            record_event(
                category="llm",
                event_type="llm_decision",
                level=level,
                exchange=payload.get("exchange") or None,
                symbol=payload.get("symbol"),
                strategy=None,
                message=message,
                details={
                    "decision": decision,
                    "confidence": confidence,
                    "reason": reason,
                    "provider": payload.get("provider"),
                    "model": payload.get("model"),
                    "risk_level": payload.get("risk_level"),
                    "interval": payload.get("interval"),
                    "prompt_tokens": payload.get("prompt_tokens"),
                    "completion_tokens": payload.get("completion_tokens"),
                    "latency_ms": payload.get("latency_ms"),
                    "failed": payload.get("failed"),
                    "cache_hit": payload.get("cache_hit"),
                    "data_timestamp": payload.get("data_timestamp"),
                    "model_version": payload.get("model_version"),
                    "prompt_version": payload.get("prompt_version"),
                    "interception_reasons": payload.get("interception_reasons"),
                    "input_summary": payload.get("input_summary"),
                    "output_summary": payload.get("output_summary"),
                },
            )
        except Exception:
            # Belt-and-suspenders: LLMAnalyzer already swallows observer
            # errors, but if a caller awaits us directly we don't want
            # store hiccups to bubble up either.
            _loguru_logger.exception("failed to persist llm_decision event")

    def reject_live_disabled(
        *,
        action: str,
        detail: str,
        exchange: str | None = None,
        symbol: str | None = None,
        order_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        # 实盘关闭时，不能只返回 403；量化系统要留下“谁、对哪个交易所/币对、试图做什么”的审计记录。
        payload = {"action": action, **(details or {})}
        record_event(
            category="risk",
            event_type="live_trading_blocked",
            level="warning",
            exchange=exchange,
            symbol=symbol,
            order_id=order_id,
            message=detail,
            details=payload,
        )
        raise HTTPException(status_code=403, detail=detail)

    def reject_kill_switch_enabled(
        *,
        action: str,
        exchange: str | None = None,
        symbol: str | None = None,
        order_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        # Kill Switch 是运行时紧急熔断。触发后，所有会改变交易所状态的接口都必须先被挡住并留审计。
        detail = "Global kill switch is active. Disable it before trading."
        record_event(
            category="risk",
            event_type="kill_switch_blocked",
            level="critical",
            exchange=exchange,
            symbol=symbol,
            order_id=order_id,
            message=detail,
            details={"action": action, **(details or {})},
        )
        raise HTTPException(status_code=423, detail=detail)

    def ensure_trading_not_killed(
        *,
        action: str,
        exchange: str | None = None,
        symbol: str | None = None,
        order_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        # RiskManager.trading_enabled 是引擎层风控总闸；API 层在创建交易所客户端前先检查它。
        if not state.engine.risk_manager.is_trading_enabled:
            reject_kill_switch_enabled(
                action=action,
                exchange=exchange,
                symbol=symbol,
                order_id=order_id,
                details=details,
            )

    def ensure_account_reconciled(
        *,
        action: str,
        exchange: str,
        symbol: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Fail closed for new exposure on a venue with unresolved position drift."""

        guard = state.engine.account_reconciliation
        if not guard.is_blocked(exchange):
            return
        reason = guard.rejection_reason(exchange) or "account reconciliation is blocked"
        record_event(
            category="risk",
            event_type="account_reconciliation_blocked_order",
            level="critical",
            exchange=exchange,
            symbol=symbol,
            message=f"{action} rejected: {reason}",
            details={"action": action, **(details or {})},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "account_reconciliation_blocked",
                "message": reason,
                "exchange": exchange,
                "reconciliation_required": True,
            },
        )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "env": settings.app_env}

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus exposition endpoint.

        Returns `qt_orders_total`, `qt_risk_rejections_total`,
        `qt_llm_call_duration_seconds`, `qt_llm_tokens_total`,
        `qt_monitor_alerts_total`, `qt_paper_orders_total`,
        `qt_engine_loop_duration_seconds`, `qt_positions_active`,
        `qt_app_info`. Body is the standard Prometheus text format —
        no auth (assumes the endpoint is reachable only from the
        monitoring network, e.g. behind a Prometheus IP allowlist).
        """
        from app.engine.metrics import render as render_metrics

        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    @app.get("/api/v1/health/venues")
    async def venue_health(state: AppState = Depends(get_state)) -> dict[str, Any]:
        """检查每个已启用交易所的健康状态。

        对每个 venue 执行：
        - 公开 API 可达性 (ping ticker)
        - 私有 API 可达性 (如果配置了 API Key，尝试余额查询)
        - 时钟偏差 (本地 vs 交易所服务器时间)
        - 凭证存在性
        - 频率限制状态 (取决于交易所是否返回 rate-limit 头)
        """

        venues: dict[str, Any] = {}
        for name in ExchangeFactory.list_supported_exchanges():
            exchange_settings = settings.exchange(name)
            if exchange_settings is None or not exchange_settings.enabled:
                continue

            has_keys = bool(exchange_settings.api_key)
            result: dict[str, Any] = {
                "enabled": True,
                "use_testnet": exchange_settings.use_testnet,
                "credentials_present": has_keys,
                "public_api_ok": False,
                "public_api_error": None,
                "private_api_ok": None,
                "private_api_error": None,
                "clock_skew_ms": None,
                "rate_limit_ok": None,
                "checked_at": datetime.utcnow().isoformat(),
            }

            try:
                client = state.get_exchange(name)
            except HTTPException as exc:
                result["public_api_error"] = exc.detail
                venues[name] = result
                continue

            # 公开 API 检查
            try:
                ticker = await call_exchange(lambda: client.get_ticker("BTCUSDT"))
                result["public_api_ok"] = True
                # 尝试从 ticker 时间戳估算时钟偏差
                ticker_ts = ticker.get("timestamp")
                if isinstance(ticker_ts, datetime):
                    skew = (datetime.utcnow() - ticker_ts).total_seconds() * 1000
                    result["clock_skew_ms"] = round(skew, 1)
            except HTTPException as exc:
                result["public_api_error"] = exc.detail

            # 私有 API 检查（仅当配置了 API Key）
            if has_keys:
                try:
                    await call_exchange(client.get_account_balance, is_private=True)
                    result["private_api_ok"] = True
                except HTTPException as exc:
                    result["private_api_ok"] = False
                    result["private_api_error"] = exc.detail

            venues[name] = result

        return {"venues": venues, "timestamp": datetime.utcnow().isoformat()}

    @app.get("/api/v1/config")
    async def get_config(state: AppState = Depends(get_state)) -> dict[str, Any]:
        async def build():
            configured = {}
            capabilities = {}
            for name in ExchangeFactory.list_supported_exchanges():
                exchange_settings = settings.exchange(name)
                configured[name] = {
                    "enabled": bool(exchange_settings and exchange_settings.enabled),
                    "use_testnet": bool(exchange_settings and exchange_settings.use_testnet),
                    "has_api_key": bool(exchange_settings and exchange_settings.api_key),
                }
                capabilities[name] = ExchangeFactory.get_capabilities(name)
            return {
                "app_name": settings.app_name,
                "app_env": settings.app_env,
                "default_exchange": settings.default_exchange,
                "default_symbol": settings.default_symbol,
                "live_trading_enabled": settings.enable_live_trading,
                "frontend_static_dir": settings.frontend_static_dir,
                "persistence": {
                    "driver": "sqlite",
                    "path": str(Path(settings.sqlite_path)),
                },
                "exchanges": configured,
                "exchange_capabilities": capabilities,
                "risk": settings.risk.model_dump(),
            }

        return await state.cache.get_or_set("config", build, ttl=30.0)

    @app.get("/api/v1/exchanges")
    async def list_exchanges() -> dict[str, Any]:
        supported = ExchangeFactory.list_supported_exchanges()
        enabled = [
            name
            for name in supported
            if (exchange_settings := settings.exchange(name)) is not None
            and exchange_settings.enabled
        ]
        return {"exchanges": supported, "enabled": enabled}

    @app.get("/api/v1/risk/kill-switch")
    async def get_kill_switch_status(state: AppState = Depends(get_state)) -> dict[str, Any]:
        """读取全局 Kill Switch 状态。

        前端风控面板用这个接口判断是否允许真实下单。这里同时返回 risk 快照，
        是为了让 UI 能把“是否熔断”和“当前风控指标”放在同一个区域展示。
        """

        risk = await state.engine.risk_manager.get_risk_status()
        trading_enabled = bool(risk["trading_enabled"])
        return {
            "enabled": not trading_enabled,
            "trading_enabled": trading_enabled,
            "risk": risk,
        }

    @app.post("/api/v1/risk/kill-switch", dependencies=[Depends(require_api_key)])
    async def set_kill_switch(
        request: KillSwitchRequest,
        state: AppState = Depends(get_state),
    ) -> dict[str, Any]:
        """切换全局 Kill Switch。

        enabled=true 会调用 RiskManager.disable_trading()；策略实盘执行和手动下单都会被同一状态拦截。

        v0.4.3: 不再在这里写 audit 事件 —— LiveTradingGuard 的 observer
        会统一记录（带 reason）。保留这里只是为了让 set_kill_switch
        路径和 guard 路径走同一份审计代码。
        """

        if request.enabled:
            state.engine.risk_manager.disable_trading(reason=request.reason)
        else:
            state.engine.risk_manager.enable_trading(reason=request.reason)

        risk = await state.engine.risk_manager.get_risk_status()
        trading_enabled = bool(risk["trading_enabled"])
        return {
            "enabled": not trading_enabled,
            "trading_enabled": trading_enabled,
            "risk": risk,
        }

    @app.get("/api/v1/risk/history")
    async def risk_history(
        state: AppState = Depends(get_state),
        minutes: int = 30,
        limit: int = 200,
    ) -> dict[str, Any]:
        """最近 N 分钟的 risk snapshot 序列（5 重风控 sparkline 数据源）。

        由 engine 的 _risk_snapshot_loop 每 30s 写一行到 events 表
        (category='risk', event_type='snapshot')。空数据返回空列表，
        不抛错。
        """
        from datetime import datetime, timedelta

        if state.store is None:
            return {"snapshots": [], "minutes": minutes, "limit": limit}

        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        rows = state.store.recent_events(category="risk", event_type="snapshot", limit=limit)
        snapshots: list[dict[str, Any]] = []
        for row in rows:
            ts = row.get("timestamp", "")
            if ts < cutoff:
                continue
            details = row.get("details") or {}
            snapshots.append(
                {
                    "timestamp": ts,
                    "daily_pnl": details.get("daily_pnl", 0.0),
                    "current_drawdown": details.get("current_drawdown", 0.0),
                    "orders_last_minute": details.get("orders_last_minute", 0),
                    "max_orders_per_minute": details.get("max_orders_per_minute", 0),
                    "total_unrealized_pnl": details.get("total_unrealized_pnl", 0.0),
                    "kill_switch_enabled": details.get("kill_switch_enabled", False),
                }
            )
        return {
            "snapshots": snapshots,
            "minutes": minutes,
            "limit": limit,
            "count": len(snapshots),
        }

    @app.get("/api/v1/ticker/{exchange}/{symbol}")
    async def get_ticker(exchange: str, symbol: str, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        return await call_exchange(lambda: client.get_ticker(symbol))

    @app.get("/api/v1/klines/{exchange}/{symbol}")
    async def get_klines(
        exchange: str,
        symbol: str,
        interval: str = Query("1m"),
        limit: int = Query(100, ge=1, le=1000),
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        return await call_exchange(
            lambda: client.get_klines(symbol, interval=interval, limit=limit)
        )

    def _recent_autopilot_decision(
        decision_id: str,
        *,
        exchange: str,
        symbol: str,
        side: str,
    ) -> dict[str, Any] | None:
        """Return a fresh matching analysis audit record, otherwise fail closed.

        A Bot caller cannot turn an arbitrary REST request into a trade: the
        order must refer to a just-recorded, same-symbol actionable decision.
        """
        cutoff = datetime.now(UTC) - timedelta(
            seconds=state.settings.bot.autopilot_cycle_seconds * 2
        )
        for event in reversed(
            state.store.recent_events(category="bot", event_type="autopilot_analysis", limit=500)
        ):
            details = event.get("details") or {}
            decision = details.get("decision") or {}
            if decision.get("decision_id") != decision_id:
                continue
            if event.get("exchange") != exchange or event.get("symbol") != symbol:
                continue
            if decision.get("action") != side:
                continue
            try:
                timestamp = datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            if timestamp.astimezone(UTC) >= cutoff:
                return decision
        return None

    @app.get("/api/v1/bot/autopilot/analysis", dependencies=[Depends(require_api_key)])
    async def bot_autopilot_analysis(
        exchange: str = Query(..., min_length=1, max_length=64),
        symbol: str = Query(..., min_length=1, max_length=32),
        state: AppState = Depends(get_state),
    ) -> dict[str, Any]:
        """Analyze closed 1h candles for Bot 1h/5h/24h consensus.

        This endpoint never submits an order. It deliberately records every
        result so an automatic order can later prove which analysis authorized
        it, and so observe/no-trade decisions remain visible to operators.
        """
        bot = state.settings.bot
        normalized_exchange = exchange.lower()
        normalized_symbol = symbol.upper()
        if not bot.autopilot_enabled:
            raise HTTPException(status_code=409, detail="Bot autopilot analysis is disabled")
        if normalized_exchange != bot.autopilot_exchange.lower():
            raise HTTPException(status_code=403, detail="Exchange is not allowed for Bot autopilot")
        if normalized_symbol not in set(bot.autopilot_symbols):
            raise HTTPException(status_code=403, detail="Symbol is not allowed for Bot autopilot")

        client = state.data_sources.get(normalized_exchange)
        if client is None:
            raise HTTPException(status_code=404, detail=f"Data source not configured: {exchange}")
        candles = await call_exchange(
            lambda: client.get_klines(normalized_symbol, interval="1h", limit=26)
        )
        # Exchange klines commonly include the currently-forming candle. Drop
        # it unconditionally so the 1h / 5h / 24h decision only sees closes
        # that existed when the decision was made.
        decision = analyze_multi_timeframe(
            candles[:-1],
            min_return_pct=bot.autopilot_min_return_pct,
        )
        payload = decision.to_dict()
        record_event(
            category="bot",
            event_type="autopilot_analysis",
            message=f"Bot autopilot analysis: {decision.action.upper()} {normalized_symbol}",
            exchange=normalized_exchange,
            symbol=normalized_symbol,
            details={"decision": payload},
        )
        return {
            "exchange": normalized_exchange,
            "symbol": normalized_symbol,
            "live_order_allowed": bool(
                bot.autopilot_live_order_enabled and state.settings.enable_live_trading
            ),
            **payload,
        }

    @app.post("/api/v1/bot/autopilot/order", dependencies=[Depends(require_api_key)])
    async def bot_autopilot_order(
        request: BotAutopilotOrderRequest,
        state: AppState = Depends(get_state),
    ) -> dict[str, Any]:
        """Submit one strictly budgeted Bot market order after an audit-backed decision."""
        bot = state.settings.bot
        exchange = request.exchange.lower()
        symbol = request.symbol.upper()
        side = request.side.lower()
        if not bot.autopilot_enabled or not bot.autopilot_live_order_enabled:
            raise HTTPException(status_code=409, detail="Bot autopilot live orders are disabled")
        if exchange != bot.autopilot_exchange.lower() or symbol not in set(bot.autopilot_symbols):
            raise HTTPException(
                status_code=403, detail="Bot autopilot exchange or symbol is not allowed"
            )
        if request.notional > bot.autopilot_max_order_notional:
            raise HTTPException(
                status_code=422, detail="Bot autopilot single-order notional limit exceeded"
            )
        if not state.settings.enable_live_trading:
            reject_live_disabled(
                action="bot_autopilot_order",
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true only after testnet validation.",
                exchange=exchange,
                symbol=symbol,
                details=request.model_dump(mode="json"),
            )
        ensure_trading_not_killed(
            action="bot_autopilot_order",
            exchange=exchange,
            symbol=symbol,
            details=request.model_dump(mode="json"),
        )
        ensure_account_reconciled(
            action="bot_autopilot_order",
            exchange=exchange,
            symbol=symbol,
            details=request.model_dump(mode="json"),
        )
        decision = _recent_autopilot_decision(
            request.decision_id, exchange=exchange, symbol=symbol, side=side
        )
        if decision is None:
            raise HTTPException(status_code=409, detail="No fresh matching Bot autopilot decision")
        signal_key = str(decision.get("signal_key") or "")
        if len(signal_key) < 16:
            raise HTTPException(
                status_code=409, detail="Bot autopilot decision has no stable signal key"
            )
        # A random decision ID is intentionally not the idempotency key: the
        # scheduler may restart and re-analyze the same closed candle. Key the
        # order and budget to the stable consensus instead, so that retrying
        # one candle can never create a second live trade.
        client_order_id = (
            "bot-"
            + hashlib.sha256(f"{exchange}|{symbol}|{side}|{signal_key}".encode()).hexdigest()[:32]
        )
        # Replays must return before ticker/risk checks. Otherwise a Bot restart
        # could consume rate-limit slots while merely recovering an already
        # submitted or unknown order; this path never contacts the exchange.
        existing_intent = state.store.get_execution_intent(client_order_id)
        if existing_intent is not None:
            return {**_replay_execution_intent(existing_intent), "autopilot": True}

        if exchange not in state.trading_exchanges:
            raise HTTPException(
                status_code=403,
                detail="Bot autopilot requires a configured private trading exchange",
            )
        client = state.get_exchange(exchange)
        ticker = await call_exchange(lambda: client.get_ticker(symbol))
        try:
            reference_price = float(ticker.get("last_price") or ticker.get("price") or 0.0)
        except (TypeError, ValueError):
            reference_price = 0.0
        if reference_price <= 0:
            raise HTTPException(
                status_code=502, detail="Cannot obtain a valid reference price for Bot order"
            )
        quantity = request.notional / reference_price
        await ensure_pretrade_risk(
            action="bot_autopilot_order",
            exchange=exchange,
            symbol=symbol,
            side=side,
            quantity=quantity,
            reference_price=reference_price,
            details=request.model_dump(mode="json"),
        )

        budget_date = datetime.now(UTC).date().isoformat()
        budget_allowed, used_notional, budget_idempotent = (
            state.store.reserve_bot_autopilot_notional(
                decision_id=client_order_id,
                budget_date=budget_date,
                notional=request.notional,
                maximum_notional=bot.autopilot_max_daily_notional,
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        if not budget_allowed:
            reject_pretrade_risk(
                action="bot_autopilot_order",
                reason="Bot autopilot daily notional limit exceeded",
                exchange=exchange,
                symbol=symbol,
                order_id=client_order_id,
                details={
                    **request.model_dump(mode="json"),
                    "notional": request.notional,
                    "daily_notional_before": used_notional,
                    "daily_notional_limit": bot.autopilot_max_daily_notional,
                },
            )
        reserve_shared_daily_notional(
            action="bot_autopilot_order",
            client_order_id=client_order_id,
            exchange=exchange,
            symbol=symbol,
            notional=request.notional,
            details=request.model_dump(mode="json"),
        )

        order_request = OrderRequest(
            exchange=exchange,
            symbol=symbol,
            side=side,
            order_type="market",
            quantity=quantity,
            client_order_id=client_order_id,
        )
        existing = _claim_execution_intent(
            client_order_id=client_order_id,
            request=order_request,
            side=side,
        )
        if existing is not None:
            return {**_replay_execution_intent(existing), "autopilot": True}

        try:
            result = await call_exchange(
                lambda: client.place_order(
                    symbol=symbol,
                    side=side,
                    order_type="market",
                    quantity=quantity,
                    price=None,
                    quote_order_qty=None,
                    client_order_id=client_order_id,
                ),
                is_private=True,
            )
        except HTTPException as exc:
            await _mark_submission_unknown(
                request=order_request, action="bot_autopilot_order", error=exc
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Bot order submission outcome is unknown; do not retry with a new decision id.",
                    "client_order_id": client_order_id,
                    "reconciliation_required": True,
                    "exchange_error": exc.detail,
                },
            ) from exc

        response = dict(result)
        order_id = extract_order_id(response)
        status = _intent_status_from_response(response)
        state.store.update_execution_intent(
            client_order_id,
            status=status,
            exchange_order_id=order_id,
            response=response,
            clear_error=True,
        )
        await state.track_execution_intent(client_order_id)
        record_event(
            category="bot",
            event_type="autopilot_order_submitted",
            message=f"Bot autopilot order submitted: {side.upper()} {quantity:.8f} {symbol}",
            exchange=exchange,
            symbol=symbol,
            order_id=order_id or client_order_id,
            details={
                "decision_id": request.decision_id,
                "notional": request.notional,
                "reference_price": reference_price,
                "quantity": quantity,
                "daily_notional_before": used_notional,
                "daily_notional_limit": bot.autopilot_max_daily_notional,
                "daily_budget_reservation_idempotent": budget_idempotent,
                "single_order_notional_limit": bot.autopilot_max_order_notional,
                "response": response,
            },
        )
        return {
            **response,
            "autopilot": True,
            "client_order_id": client_order_id,
            "execution_status": status,
            "idempotent_replay": False,
            "reference_price": reference_price,
            "notional": request.notional,
        }

    @app.get("/api/v1/trades/{exchange}/{symbol}")
    async def get_recent_trades(
        exchange: str,
        symbol: str,
        limit: int = Query(50, ge=1, le=1000),
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        return await call_exchange(lambda: client.get_recent_trades(symbol, limit=limit))

    @app.get("/api/v1/balances/{exchange}")
    async def get_balances(exchange: str, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        return await call_exchange(client.get_account_balance, is_private=True)

    @app.get("/api/v1/balances/{exchange}/available")
    async def get_available_balances(exchange: str, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        return await call_exchange(client.get_available_balances, is_private=True)

    @app.get("/api/v1/order/{exchange}/{symbol}/{order_id}")
    async def get_order(
        exchange: str,
        symbol: str,
        order_id: str,
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        return await call_exchange(lambda: client.get_order(symbol, order_id), is_private=True)

    @app.get("/api/v1/orders/{exchange}/open")
    async def get_open_orders(
        exchange: str,
        symbol: str | None = None,
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        return await call_exchange(lambda: client.get_open_orders(symbol), is_private=True)

    @app.get("/api/v1/contracts/{exchange}")
    async def list_contract_markets(
        exchange: str,
        quote_asset: str = Query("USDT", min_length=1),
        search: str = Query("", max_length=32),
        limit: int = Query(200, ge=1, le=1000),
        state: AppState = Depends(get_state),
    ):
        client = state.get_contract_exchange(exchange)
        markets = await call_exchange(lambda: client.get_contract_markets(quote_asset=quote_asset))
        needle = search.strip().upper()
        if needle:
            markets = [
                market
                for market in markets
                if needle in market.symbol.upper() or needle in market.base_asset.upper()
            ]
        return {"contracts": markets[:limit], "total": len(markets)}

    @app.get("/api/v1/contracts/{exchange}/{symbol}/fee-rate")
    async def get_contract_fee_rate(
        exchange: str,
        symbol: str,
        state: AppState = Depends(get_state),
    ):
        client = state.get_contract_exchange(exchange)
        return await call_exchange(lambda: client.get_fee_rate(symbol), is_private=True)

    @app.get("/api/v1/contracts/{exchange}/{symbol}/cost-estimate")
    async def estimate_contract_cost(
        exchange: str,
        symbol: str,
        quantity: float = Query(..., gt=0),
        price: float = Query(..., gt=0),
        liquidity: LiquidityType = Query(LiquidityType.MAKER),
        state: AppState = Depends(get_state),
    ):
        client = state.get_contract_exchange(exchange)
        return await call_exchange(
            lambda: client.estimate_order_cost(symbol, quantity, price, liquidity)
        )

    @app.post("/api/v1/contracts/order/preview")
    async def preview_contract_order(
        request: ContractOrderRequest,
        state: AppState = Depends(get_state),
    ):
        """合约下单预览。

        调用关系：
        前端填写订单 -> POST /preview -> 后端补 client_order_id 并估算成本 ->
        前端展示预览 -> 用户确认 -> POST /api/v1/contracts/order。
        """

        preview = await build_contract_order_preview(request)
        record_event(
            category="order",
            event_type="contract_order_previewed",
            exchange=preview["exchange"],
            symbol=preview["symbol"],
            order_id=preview["client_order_id"],
            message=f"Contract order previewed: {preview['intent']} {preview['quantity']} {preview['symbol']}",
            details=preview,
        )
        return preview

    @app.post(
        "/api/v1/contracts/{exchange}/{symbol}/leverage",
        dependencies=[Depends(require_api_key)],
    )
    async def set_contract_leverage(
        exchange: str,
        symbol: str,
        leverage: int = Query(..., gt=0),
        margin_mode: MarginMode = Query(MarginMode.CROSS),
        position_side: PositionSide = Query(PositionSide.NET),
        state: AppState = Depends(get_state),
    ):
        if not state.settings.enable_live_trading:
            reject_live_disabled(
                action="set_leverage",
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to change leverage.",
                exchange=exchange,
                symbol=symbol,
                details={
                    "leverage": leverage,
                    "margin_mode": margin_mode.value,
                    "position_side": position_side.value,
                },
            )
        ensure_trading_not_killed(
            action="set_leverage",
            exchange=exchange,
            symbol=symbol,
            details={
                "leverage": leverage,
                "margin_mode": margin_mode.value,
                "position_side": position_side.value,
            },
        )
        client = state.get_contract_exchange(exchange)
        result = await call_exchange(
            lambda: client.set_leverage(symbol, leverage, margin_mode, position_side),
            is_private=True,
        )
        record_event(
            category="order",
            event_type="leverage_changed",
            exchange=exchange,
            symbol=symbol,
            message=f"Leverage set to {leverage}x for {symbol}",
            details={
                "leverage": leverage,
                "margin_mode": margin_mode.value,
                "position_side": position_side.value,
                "response": result,
            },
        )
        return result

    @app.post("/api/v1/order", dependencies=[Depends(require_api_key)])
    async def place_order(request: OrderRequest, state: AppState = Depends(get_state)):
        request = ensure_client_order_id(request)
        # 默认只允许读操作；真实下单必须在 .env 里显式开启 ENABLE_LIVE_TRADING。
        if not state.settings.enable_live_trading:
            reject_live_disabled(
                action="place_order",
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to place orders.",
                exchange=request.exchange,
                symbol=request.symbol,
                details=request.model_dump(mode="json"),
            )
        ensure_trading_not_killed(
            action="place_order",
            exchange=request.exchange,
            symbol=request.symbol,
            details=request.model_dump(mode="json"),
        )
        ensure_account_reconciled(
            action="place_order",
            exchange=request.exchange,
            symbol=request.symbol,
            details=request.model_dump(mode="json"),
        )

        existing = _existing_execution_intent(
            client_order_id=request.client_order_id,
            request=request,
        )
        if existing is not None:
            return _replay_execution_intent(existing)

        client = state.get_exchange(request.exchange)
        reference_price = await resolve_reference_price(
            client=client,
            symbol=request.symbol,
            quantity=request.quantity,
            limit_price=request.price,
            quote_order_qty=request.quote_order_qty,
        )
        await ensure_pretrade_risk(
            action="place_order",
            exchange=request.exchange,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            reference_price=reference_price,
            increases_exposure=request.side.lower() == "buy",
            details=request.model_dump(mode="json"),
        )
        reserve_shared_daily_notional(
            action="place_order",
            client_order_id=request.client_order_id,
            exchange=request.exchange,
            symbol=request.symbol,
            notional=request.quote_order_qty or request.quantity * reference_price,
            details=request.model_dump(mode="json"),
        )
        existing = _claim_execution_intent(
            client_order_id=request.client_order_id,
            request=request,
            side=request.side,
        )
        if existing is not None:
            return _replay_execution_intent(existing)
        try:
            result = await call_exchange(
                lambda: client.place_order(
                    symbol=request.symbol,
                    side=request.side,
                    order_type=request.order_type,
                    quantity=request.quantity,
                    price=request.price,
                    quote_order_qty=request.quote_order_qty,
                    client_order_id=request.client_order_id,
                ),
                is_private=True,
            )
        except HTTPException as exc:
            await _mark_submission_unknown(request=request, action="spot_order", error=exc)
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Spot order submission outcome is unknown; do not retry with a new client_order_id.",
                    "client_order_id": request.client_order_id,
                    "reconciliation_required": True,
                    "exchange_error": exc.detail,
                },
            ) from exc

        response = dict(result)
        order_id = extract_order_id(response)
        status = _intent_status_from_response(response)
        state.store.update_execution_intent(
            request.client_order_id,
            status=status,
            exchange_order_id=order_id,
            response=response,
            clear_error=True,
        )
        await state.track_execution_intent(request.client_order_id)
        record_event(
            category="order",
            event_type="spot_order_submitted",
            exchange=request.exchange,
            symbol=request.symbol,
            order_id=order_id or request.client_order_id,
            message=f"Spot order submitted: {request.side.upper()} {request.quantity} {request.symbol}",
            details={"request": request.model_dump(mode="json"), "response": response},
        )
        return {
            **response,
            "client_order_id": request.client_order_id,
            "execution_status": status,
            "idempotent_replay": False,
        }

    @app.post("/api/v1/contracts/order", dependencies=[Depends(require_api_key)])
    async def place_contract_order(
        request: ContractOrderRequest,
        state: AppState = Depends(get_state),
    ):
        request = ensure_contract_client_order_id(request)
        # 合约订单可能打开杠杆仓位，所以必须和现货下单一样受实盘开关保护。
        if not state.settings.enable_live_trading:
            reject_live_disabled(
                action="place_contract_order",
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to place contract orders.",
                exchange=request.exchange,
                symbol=request.symbol,
                details=request.model_dump(mode="json"),
            )
        ensure_trading_not_killed(
            action="place_contract_order",
            exchange=request.exchange,
            symbol=request.symbol,
            details=request.model_dump(mode="json"),
        )
        ensure_account_reconciled(
            action="place_contract_order",
            exchange=request.exchange,
            symbol=request.symbol,
            details=request.model_dump(mode="json"),
        )

        client = state.get_contract_exchange(request.exchange)
        side, _, reduce_only = client.resolve_order_intent(request.intent)
        existing = _existing_execution_intent(
            client_order_id=request.client_order_id,
            request=request,
        )
        if existing is not None:
            return _replay_execution_intent(existing)

        reference_price = await resolve_reference_price(
            client=client,
            symbol=request.symbol,
            quantity=request.quantity,
            limit_price=request.price,
        )
        await ensure_pretrade_risk(
            action="place_contract_order",
            exchange=request.exchange,
            symbol=request.symbol,
            side=side,
            quantity=request.quantity,
            reference_price=reference_price,
            leverage=request.leverage,
            increases_exposure=not reduce_only,
            details=request.model_dump(mode="json"),
        )
        reserve_shared_daily_notional(
            action="place_contract_order",
            client_order_id=request.client_order_id,
            exchange=request.exchange,
            symbol=request.symbol,
            notional=request.quantity * reference_price,
            details=request.model_dump(mode="json"),
        )
        existing = _claim_execution_intent(
            client_order_id=request.client_order_id,
            request=request,
            side=side,
        )
        if existing is not None:
            return _replay_execution_intent(existing)
        try:
            result = await call_exchange(
                lambda: client.place_contract_order(request), is_private=True
            )
        except HTTPException as exc:
            await _mark_submission_unknown(request=request, action="contract_order", error=exc)
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Contract order submission outcome is unknown; do not retry with a new client_order_id.",
                    "client_order_id": request.client_order_id,
                    "reconciliation_required": True,
                    "exchange_error": exc.detail,
                },
            ) from exc

        response = dict(result)
        order_id = extract_order_id(response)
        status = _intent_status_from_response(response)
        state.store.update_execution_intent(
            request.client_order_id,
            status=status,
            exchange_order_id=order_id,
            response=response,
            clear_error=True,
        )
        await state.track_execution_intent(request.client_order_id)
        record_event(
            category="order",
            event_type="contract_order_submitted",
            exchange=request.exchange,
            symbol=request.symbol,
            order_id=order_id or request.client_order_id,
            message=f"Contract order submitted: {request.intent.value} {request.quantity} {request.symbol}",
            details={"request": request.model_dump(mode="json"), "response": response},
        )
        return {
            **response,
            "client_order_id": request.client_order_id,
            "execution_status": status,
            "idempotent_replay": False,
        }

    @app.delete(
        "/api/v1/order/{exchange}/{symbol}/{order_id}",
        dependencies=[Depends(require_api_key)],
    )
    async def cancel_order(
        exchange: str,
        symbol: str,
        order_id: str,
        state: AppState = Depends(get_state),
    ):
        # 撤单也会改变交易所状态，因此同样必须受实盘开关保护。
        if not state.settings.enable_live_trading:
            reject_live_disabled(
                action="cancel_order",
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to cancel orders.",
                exchange=exchange,
                symbol=symbol,
                order_id=order_id,
            )
        ensure_trading_not_killed(
            action="cancel_order",
            exchange=exchange,
            symbol=symbol,
            order_id=order_id,
        )
        client = state.get_exchange(exchange)
        result = await call_exchange(lambda: client.cancel_order(symbol, order_id), is_private=True)
        record_event(
            category="order",
            event_type="order_cancel_requested",
            exchange=exchange,
            symbol=symbol,
            order_id=order_id,
            message=f"Cancel requested for {symbol} order {order_id}",
            details={"response": result},
        )
        return result

    @app.delete(
        "/api/v1/orders/{exchange}/open",
        dependencies=[Depends(require_api_key)],
    )
    async def cancel_all_orders(
        exchange: str,
        symbol: str | None = None,
        state: AppState = Depends(get_state),
    ):
        if not state.settings.enable_live_trading:
            reject_live_disabled(
                action="cancel_all_orders",
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to cancel orders.",
                exchange=exchange,
                symbol=symbol,
            )
        ensure_trading_not_killed(
            action="cancel_all_orders",
            exchange=exchange,
            symbol=symbol,
        )
        client = state.get_exchange(exchange)
        cancelled = await call_exchange(lambda: client.cancel_all_orders(symbol), is_private=True)
        record_event(
            category="order",
            event_type="cancel_all_requested",
            exchange=exchange,
            symbol=symbol,
            message=f"Cancel-all requested on {exchange}{f' for {symbol}' if symbol else ''}",
            details={"cancelled": cancelled},
        )
        return {"cancelled": cancelled}

    @app.get("/api/v1/engine/status")
    async def engine_status(state: AppState = Depends(get_state)):
        status = await state.engine.get_status()
        # Augment with bot config so the frontend (Spine + BotMonitorPage)
        # has a single round-trip to learn whether the bot is enabled, which
        # chats are whitelisted, and what quiet hours / min alert level apply.
        # Never expose the raw token — only its tail — to keep the bearer
        # secret fully off-wire.
        status["bot"] = _bot_status_payload(state.settings)
        return status

    @app.get("/api/v1/bot")
    async def bot_status(state: AppState = Depends(get_state)):
        """Standalone bot endpoint — same payload as engine_status['bot']."""
        return _bot_status_payload(state.settings)

    @app.get("/api/v1/runner/status")
    async def signal_runner_status(state: AppState = Depends(get_state)):
        return state.engine.get_signal_runner_status()

    @app.post("/api/v1/runner/start", dependencies=[Depends(require_api_key)])
    async def start_signal_runner(
        request: SignalRunnerRequest,
        state: AppState = Depends(get_state),
    ):
        state.ensure_strategy_exchanges()
        return await state.engine.start_signal_runner(
            poll_seconds=request.poll_seconds,
            candle_limit=request.candle_limit,
        )

    @app.post("/api/v1/runner/stop", dependencies=[Depends(require_api_key)])
    async def stop_signal_runner(state: AppState = Depends(get_state)):
        return await state.engine.stop_signal_runner()

    @app.post("/api/v1/runner/run-once", dependencies=[Depends(require_api_key)])
    async def run_signal_cycle(
        request: SignalRunnerRequest,
        state: AppState = Depends(get_state),
    ):
        state.ensure_strategy_exchanges()
        return await state.engine.run_signal_cycle(candle_limit=request.candle_limit)

    @app.get("/api/v1/paper")
    async def paper_summary(state: AppState = Depends(get_state)):
        return state.engine.get_paper_summary()

    @app.post("/api/v1/paper/positions/close", dependencies=[Depends(require_api_key)])
    async def close_paper_position_endpoint(
        request: ClosePositionRequest,
        state: AppState = Depends(get_state),
    ):
        """Close all or part of a simulated position without touching a venue."""
        exchange_name = request.exchange.lower()
        try:
            order = state.engine.close_paper_position(
                exchange=exchange_name,
                symbol=request.symbol,
                exit_quantity=request.exit_quantity,
                position_size_pct=request.position_size_pct,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if order is None:
            raise HTTPException(status_code=400, detail="No paper position to close")

        state.engine._record_event(
            category="paper",
            event_type="paper_position_closed",
            level="info",
            exchange=exchange_name,
            symbol=request.symbol,
            order_id=str(order.get("order_id", "")) or None,
            message=f"Closed {order.get('quantity', 0)} {request.symbol} in paper account",
            details={
                "quantity": order.get("quantity"),
                "price": order.get("price"),
                "realized_pnl": order.get("realized_pnl"),
                "position_size_pct": request.position_size_pct,
                "requested_exit_quantity": request.exit_quantity,
            },
        )
        return {"closed_quantity": order["quantity"], "order": order}

    @app.post("/api/v1/paper/reset", dependencies=[Depends(require_api_key)])
    async def reset_paper_account(
        request: PaperResetRequest,
        state: AppState = Depends(get_state),
    ):
        return state.engine.reset_paper_account(initial_cash=request.initial_cash)

    @app.get("/api/v1/storage/status")
    async def storage_status(state: AppState = Depends(get_state)):
        db_path = Path(state.settings.sqlite_path)
        return {
            "driver": "sqlite",
            "path": str(db_path),
            "exists": db_path.exists(),
            "size_bytes": db_path.stat().st_size if db_path.exists() else 0,
            "strategies": len(state.store.list_strategies()),
            "recent_signals": len(state.store.recent_signals(limit=200)),
            "recent_events": len(state.store.recent_events(limit=200)),
        }

    @app.get("/api/v1/strategies")
    async def list_strategies(state: AppState = Depends(get_state)):
        return {"strategies": state.engine.list_strategies()}

    @app.post("/api/v1/strategies/sma", dependencies=[Depends(require_api_key)])
    async def create_sma_strategy(
        request: SMAStrategyRequest,
        state: AppState = Depends(get_state),
    ):
        if request.short_window >= request.long_window:
            raise HTTPException(
                status_code=400, detail="short_window must be smaller than long_window"
            )

        strategy_name = request.name or (
            f"sma_{request.short_window}_{request.long_window}_"
            f"{request.exchange}_{request.symbol}".lower()
        )
        strategy = SMAStrategy(
            short_window=request.short_window,
            long_window=request.long_window,
            min_data_points=request.min_data_points or request.long_window,
        )
        state.engine.add_strategy(
            strategy_name,
            strategy,
            exchange=request.exchange,
            symbol=request.symbol,
            interval=request.interval,
            enabled=request.enabled,
            mode=request.mode,
        )
        return {
            "strategy": next(
                item for item in state.engine.list_strategies() if item["name"] == strategy_name
            )
        }

    @app.post("/api/v1/strategies/{name}/start", dependencies=[Depends(require_api_key)])
    async def start_strategy(name: str, state: AppState = Depends(get_state)):
        try:
            state.engine.set_strategy_enabled(name, True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}") from exc
        return {
            "strategy": next(
                item for item in state.engine.list_strategies() if item["name"] == name
            )
        }

    @app.post("/api/v1/strategies/{name}/stop", dependencies=[Depends(require_api_key)])
    async def stop_strategy(name: str, state: AppState = Depends(get_state)):
        try:
            state.engine.set_strategy_enabled(name, False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}") from exc
        return {
            "strategy": next(
                item for item in state.engine.list_strategies() if item["name"] == name
            )
        }

    @app.post("/api/v1/strategies/{name}/mode", dependencies=[Depends(require_api_key)])
    async def update_strategy_mode(
        name: str,
        request: StrategyModeRequest,
        state: AppState = Depends(get_state),
    ):
        try:
            state.engine.set_strategy_mode(name, request.mode)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "strategy": next(
                item for item in state.engine.list_strategies() if item["name"] == name
            )
        }

    @app.delete("/api/v1/strategies/{name}", dependencies=[Depends(require_api_key)])
    async def delete_strategy(name: str, state: AppState = Depends(get_state)):
        if not state.engine.remove_strategy(name):
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")
        return {"deleted": name}

    @app.get("/api/v1/signals/recent")
    async def recent_signals(
        limit: int = Query(20, ge=1, le=200),
        state: AppState = Depends(get_state),
    ):
        return {"signals": state.engine.get_recent_signals(limit=limit)}

    @app.get("/api/v1/events/recent")
    async def recent_events(
        category: str | None = Query(None, min_length=1, max_length=32),
        event_type: str | None = Query(None, min_length=1, max_length=64),
        minutes: int | None = Query(None, ge=1, le=1440),
        limit: int = Query(30, ge=1, le=200),
        state: AppState = Depends(get_state),
    ):
        events = state.store.recent_events(
            category=category,
            event_type=event_type,
            limit=limit,
        )
        if minutes is not None:
            from datetime import datetime, timedelta

            cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
            events = [e for e in events if e.get("timestamp", "") >= cutoff]
        return {"events": events, "count": len(events)}

    @app.post("/api/v1/signals/evaluate")
    async def evaluate_strategy_signals(
        exchange: str = Query(..., min_length=1),
        symbol: str = Query(..., min_length=1),
        interval: str = Query("1m", min_length=1),
        limit: int = Query(80, ge=20, le=500),
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        klines = await call_exchange(
            lambda: client.get_klines(symbol, interval=interval, limit=limit)
        )
        for candle in sorted(klines, key=lambda item: item.get("open_time", "")):
            await state.engine.process_market_data(exchange, symbol, candle)
        signals = await state.engine.evaluate_signals(exchange, symbol)
        return {
            "exchange": exchange,
            "symbol": symbol,
            "interval": interval,
            "candles_processed": len(klines),
            "signals": signals,
            "recent_signals": state.engine.get_recent_signals(limit=10),
        }

    @app.post("/api/v1/engine/strategy/sma", dependencies=[Depends(require_api_key)])
    async def add_sma_strategy(
        short_window: int = Query(5, ge=1),
        long_window: int = Query(20, ge=2),
        state: AppState = Depends(get_state),
    ):
        strategy = SMAStrategy(short_window=short_window, long_window=long_window)
        state.engine.add_strategy(strategy.name, strategy)
        return {"strategy": strategy.name}

    # ── AI 大模型分析 API ──────────────────────────────────────

    @app.post("/api/v1/sizing")
    async def sizing(request: SizingRequest):
        """Compute recommended contract quantity sized to a target risk %.

        Used by the frontend position-sizing panel and by automated risk
        checks before order placement.
        """
        from app.engine.position_sizer import calculate_position_size

        try:
            r = calculate_position_size(
                account_equity=request.account_equity,
                entry_price=request.entry_price,
                stop_loss_price=request.stop_loss_price,
                take_profit_price=request.take_profit_price,
                leverage=request.leverage,
                risk_pct=request.risk_pct,
                contract_size=request.contract_size,
                min_quantity=request.min_quantity,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "quantity": r.quantity,
            "notional": r.notional,
            "margin": r.margin,
            "risk_amount": r.risk_amount,
            "risk_pct": r.risk_pct,
            "risk_reward_ratio": r.risk_reward_ratio,
        }

    @app.post(
        "/api/v1/market-data/datasets",
        dependencies=[Depends(require_api_key)],
        status_code=201,
    )
    async def import_market_dataset(
        request: MarketDataImportRequest,
        state: AppState = Depends(get_state),
    ):
        """Import canonical JSON candles into the immutable DuckDB/Parquet catalog."""

        try:
            dataset = state.market_data.import_candles(
                request.candles,
                symbol=request.symbol,
                timeframe=request.timeframe,
                source=request.source,
            )
        except MarketDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _public_dataset(dataset)

    @app.post(
        "/api/v1/market-data/datasets/parquet",
        dependencies=[Depends(require_api_key)],
        status_code=201,
    )
    async def import_market_dataset_parquet(
        payload: bytes = Body(..., media_type="application/vnd.apache.parquet"),
        symbol: str = Query(..., min_length=1, max_length=32),
        timeframe: str = Query(..., pattern=r"^[1-9][0-9]*[mhdwMHDW]$"),
        source: str = Query(..., min_length=1, max_length=100),
        state: AppState = Depends(get_state),
    ):
        """Import a raw Parquet payload, then retain only its canonical dataset copy."""

        try:
            dataset = state.market_data.import_parquet_bytes(
                payload,
                symbol=symbol,
                timeframe=timeframe,
                source=source,
            )
        except MarketDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _public_dataset(dataset)

    @app.get("/api/v1/market-data/datasets")
    async def market_datasets_endpoint(
        state: AppState = Depends(get_state),
        limit: int = Query(100, ge=1, le=500),
    ):
        """List immutable historical dataset versions and their quality status."""

        return {
            "datasets": [_public_dataset(item) for item in state.market_data.datasets(limit=limit)]
        }

    @app.get("/api/v1/market-data/datasets/{version}")
    async def market_dataset_endpoint(version: str, state: AppState = Depends(get_state)):
        """Return provenance, content hash, and quality report for one dataset version."""

        try:
            return _public_dataset(state.market_data.dataset(version))
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/market-data/datasets/{version}/candles")
    async def market_dataset_candles_endpoint(
        version: str,
        state: AppState = Depends(get_state),
        symbol: str | None = Query(None, min_length=1, max_length=32),
        timeframe: str | None = Query(None, pattern=r"^[1-9][0-9]*[mhdwMHDW]$"),
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        """Query a dataset's Parquet candles by symbol, timeframe, and UTC time range."""

        try:
            candles = state.market_data.query_candles(
                version,
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MarketDataError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"version": version, "candles": candles}

    def _public_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in dataset.items() if key != "parquet_path"}

    def _serialize_kline(kline: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in kline.items()
        }

    def _strategy_version() -> str:
        from app.engine import backtest as backtest_module

        return hashlib.sha256(Path(backtest_module.__file__).read_bytes()).hexdigest()

    def _load_backtest_candles(
        request: BacktestRequest,
        state: AppState,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Resolve an approved backtest dataset and adapt its timestamp boundary."""

        if request.data_version is not None:
            candles = state.market_data.query_candles(
                request.data_version,
                start=request.start,
                end=request.end,
                require_quality=True,
            )
        else:
            candles = request.klines or []
        if not candles:
            raise MarketDataError("the requested dataset range contains no candles")
        # The simulation core uses `open_time`; catalog rows expose the public
        # canonical name `timestamp`, so adapt only at this boundary.
        return candles, [
            {**candle, "open_time": candle.get("open_time", candle.get("timestamp"))}
            for candle in candles
        ]

    def _run_backtest(
        request: BacktestRequest,
        state: AppState,
        *,
        persist: bool,
    ) -> dict[str, Any]:
        """Run, fingerprint, and optionally persist a deterministic SMA experiment."""

        from app.engine.backtest import run_sma_backtest

        if request.short_window >= request.long_window:
            raise HTTPException(
                status_code=400,
                detail="short_window must be smaller than long_window",
            )
        try:
            candles, backtest_candles = _load_backtest_candles(request, state)
            result = run_sma_backtest(
                candles=backtest_candles,
                short_window=request.short_window,
                long_window=request.long_window,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid kline data: {exc}") from exc

        execution_model = {
            "signal_execution": "next_bar_open",
            "fee_rate": request.fee_rate,
            "slippage_rate": request.slippage_rate,
            "max_volume_participation": request.max_volume_participation,
            "volume_limit_behavior": "partial_fill_then_cancel",
        }
        payload: dict[str, Any] = {
            "initial_capital": result.initial_capital,
            "final_equity": result.final_equity,
            "total_pnl": result.total_pnl,
            "trades": result.trades,
            "win_rate": result.win_rate,
            "max_drawdown": result.max_drawdown,
            "equity_curve": result.equity_curve,
            "total_fees": result.total_fees,
            "gross_pnl": result.gross_pnl,
            "total_return_pct": result.total_return_pct,
            "profit_factor": result.profit_factor,
            "execution_model": execution_model,
            "trade_history": [
                {
                    "entry_index": trade.entry_index,
                    "exit_index": trade.exit_index,
                    "entry_time": _serialize_kline({"value": trade.entry_time})["value"],
                    "exit_time": _serialize_kline({"value": trade.exit_time})["value"],
                    "quantity": trade.quantity,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "gross_pnl": trade.gross_pnl,
                    "fees": trade.fees,
                    "net_pnl": trade.net_pnl,
                    "exit_reason": trade.exit_reason,
                }
                for trade in result.trade_history
            ],
            "fill_history": [
                {
                    "order_id": fill.order_id,
                    "index": fill.index,
                    "time": _serialize_kline({"value": fill.time})["value"],
                    "side": fill.side,
                    "requested_quantity": fill.requested_quantity,
                    "filled_quantity": fill.filled_quantity,
                    "price": fill.price,
                    "fee": fill.fee,
                    "remaining_quantity": fill.remaining_quantity,
                    "status": fill.status,
                    "reason": fill.reason,
                }
                for fill in result.fill_history
            ],
            "klines_used": [_serialize_kline(kline) for kline in candles],
            "data_version": request.data_version,
        }
        result_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload["result_hash"] = result_hash

        if persist:
            strategy_parameters = {
                "short_window": request.short_window,
                "long_window": request.long_window,
                "initial_capital": request.initial_capital,
                "position_size_pct": request.position_size_pct,
            }
            risk_model = {
                "stop_loss_pct": request.stop_loss_pct,
                "take_profit_pct": request.take_profit_pct,
            }
            environment = {
                "app_version": "0.1.0",
                "python_version": platform.python_version(),
                "model_version": "not_applicable:sma_rule",
                "backtest_engine": "event_driven_simulation_v1",
            }
            run_id = state.store.save_backtest_experiment(
                strategy_name="sma_crossover",
                strategy_version=_strategy_version(),
                data_version=request.data_version,
                data_start=str(backtest_candles[0].get("open_time")) if backtest_candles else None,
                data_end=str(backtest_candles[-1].get("open_time")) if backtest_candles else None,
                strategy_parameters=strategy_parameters,
                execution_model=execution_model,
                risk_model=risk_model,
                environment=environment,
                request=request.model_dump(mode="json", exclude_none=True),
                result=payload,
                result_hash=result_hash,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            payload["backtest_run_id"] = run_id
        return payload

    def _backtest_metrics_payload(result: Any) -> dict[str, Any]:
        """Serialize one engine result without experiment-specific metadata."""

        return {
            "initial_capital": result.initial_capital,
            "final_equity": result.final_equity,
            "total_pnl": result.total_pnl,
            "trades": result.trades,
            "win_rate": result.win_rate,
            "max_drawdown": result.max_drawdown,
            "equity_curve": result.equity_curve,
            "total_fees": result.total_fees,
            "gross_pnl": result.gross_pnl,
            "total_return_pct": result.total_return_pct,
            "profit_factor": result.profit_factor,
            "trade_history": [
                {
                    "entry_index": trade.entry_index,
                    "exit_index": trade.exit_index,
                    "entry_time": _serialize_kline({"value": trade.entry_time})["value"],
                    "exit_time": _serialize_kline({"value": trade.exit_time})["value"],
                    "quantity": trade.quantity,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "gross_pnl": trade.gross_pnl,
                    "fees": trade.fees,
                    "net_pnl": trade.net_pnl,
                    "exit_reason": trade.exit_reason,
                }
                for trade in result.trade_history
            ],
            "fill_history": [
                {
                    "order_id": fill.order_id,
                    "index": fill.index,
                    "time": _serialize_kline({"value": fill.time})["value"],
                    "side": fill.side,
                    "requested_quantity": fill.requested_quantity,
                    "filled_quantity": fill.filled_quantity,
                    "price": fill.price,
                    "fee": fill.fee,
                    "remaining_quantity": fill.remaining_quantity,
                    "status": fill.status,
                    "reason": fill.reason,
                }
                for fill in result.fill_history
            ],
        }

    def _run_in_out_sample_backtest(
        request: InOutSampleBacktestRequest, state: AppState, *, persist: bool
    ) -> dict[str, Any]:
        """Run one fixed SMA configuration on contiguous in/out sample segments."""
        from app.engine.in_out_sample import run_in_out_sample_sma_backtest

        try:
            candles, backtest_candles = _load_backtest_candles(request, state)
            result = run_in_out_sample_sma_backtest(
                backtest_candles,
                in_sample_size=request.in_sample_size,
                short_window=request.short_window,
                long_window=request.long_window,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid in/out-sample backtest data: {exc}"
            ) from exc

        execution_model = {
            "signal_execution": "next_bar_open",
            "fee_rate": request.fee_rate,
            "slippage_rate": request.slippage_rate,
            "max_volume_participation": request.max_volume_participation,
            "volume_limit_behavior": "partial_fill_then_cancel",
        }
        payload: dict[str, Any] = {
            "split": {
                "in_sample_size": result.in_sample_size,
                "out_sample_size": result.out_sample_size,
                "parameter_mode": "fixed",
                "selection_on_out_sample": False,
                "capital_model": "independent_per_segment",
            },
            "in_sample": _backtest_metrics_payload(result.in_sample),
            "out_sample": _backtest_metrics_payload(result.out_sample),
            "parameters": {
                "short_window": request.short_window,
                "long_window": request.long_window,
                "initial_capital": request.initial_capital,
                "position_size_pct": request.position_size_pct,
            },
            "execution_model": execution_model,
            "klines_used": [_serialize_kline(kline) for kline in candles],
            "data_version": request.data_version,
        }
        result_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload["result_hash"] = result_hash
        if persist:
            run_id = state.store.save_backtest_experiment(
                strategy_name="sma_in_out_sample",
                strategy_version=_strategy_version(),
                data_version=request.data_version,
                data_start=str(backtest_candles[0].get("open_time")),
                data_end=str(backtest_candles[-1].get("open_time")),
                strategy_parameters={
                    "short_window": request.short_window,
                    "long_window": request.long_window,
                    "in_sample_size": request.in_sample_size,
                    "initial_capital": request.initial_capital,
                    "position_size_pct": request.position_size_pct,
                },
                execution_model=execution_model,
                risk_model={
                    "stop_loss_pct": request.stop_loss_pct,
                    "take_profit_pct": request.take_profit_pct,
                },
                environment={
                    "app_version": "0.1.0",
                    "python_version": platform.python_version(),
                    "model_version": "not_applicable:sma_rule",
                    "backtest_engine": "event_driven_simulation_v1",
                },
                request=request.model_dump(mode="json", exclude_none=True),
                result=payload,
                result_hash=result_hash,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            payload["backtest_run_id"] = run_id
        return payload

    def _run_bootstrap_backtest(
        request: BootstrapBacktestRequest, state: AppState, *, persist: bool
    ) -> dict[str, Any]:
        """Run deterministic with-replacement Bootstrap diagnostics for one SMA result."""
        from app.engine.backtest import run_sma_backtest
        from app.engine.bootstrap import run_trade_pnl_bootstrap

        try:
            candles, backtest_candles = _load_backtest_candles(request, state)
            baseline = run_sma_backtest(
                backtest_candles,
                short_window=request.short_window,
                long_window=request.long_window,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
            simulation = run_trade_pnl_bootstrap(
                [trade.net_pnl for trade in baseline.trade_history],
                initial_capital=request.initial_capital,
                simulations=request.simulations,
                seed=request.seed,
                drawdown_threshold_pct=request.drawdown_threshold_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid Bootstrap backtest data: {exc}"
            ) from exc

        execution_model = {
            "signal_execution": "next_bar_open",
            "fee_rate": request.fee_rate,
            "slippage_rate": request.slippage_rate,
            "max_volume_participation": request.max_volume_participation,
            "volume_limit_behavior": "partial_fill_then_cancel",
        }
        payload: dict[str, Any] = {
            "bootstrap": simulation.as_dict(),
            "baseline": _backtest_metrics_payload(baseline),
            "parameters": {
                "short_window": request.short_window,
                "long_window": request.long_window,
                "initial_capital": request.initial_capital,
                "position_size_pct": request.position_size_pct,
            },
            "execution_model": execution_model,
            "klines_used": [_serialize_kline(kline) for kline in candles],
            "data_version": request.data_version,
        }
        result_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload["result_hash"] = result_hash
        if persist:
            run_id = state.store.save_backtest_experiment(
                strategy_name="sma_bootstrap",
                strategy_version=_strategy_version(),
                data_version=request.data_version,
                data_start=str(backtest_candles[0].get("open_time")),
                data_end=str(backtest_candles[-1].get("open_time")),
                strategy_parameters={
                    "short_window": request.short_window,
                    "long_window": request.long_window,
                    "initial_capital": request.initial_capital,
                    "position_size_pct": request.position_size_pct,
                },
                execution_model=execution_model,
                risk_model={
                    "stop_loss_pct": request.stop_loss_pct,
                    "take_profit_pct": request.take_profit_pct,
                },
                environment={
                    "app_version": "0.1.0",
                    "python_version": platform.python_version(),
                    "model_version": "not_applicable:sma_rule",
                    "backtest_engine": "event_driven_simulation_v1",
                },
                request=request.model_dump(mode="json", exclude_none=True),
                result=payload,
                result_hash=result_hash,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            payload["backtest_run_id"] = run_id
        return payload

    def _run_monte_carlo_backtest(
        request: MonteCarloBacktestRequest, state: AppState, *, persist: bool
    ) -> dict[str, Any]:
        """Run a deterministic trade-order Monte Carlo study for one SMA result."""
        from app.engine.backtest import run_sma_backtest
        from app.engine.monte_carlo import run_trade_sequence_monte_carlo

        try:
            candles, backtest_candles = _load_backtest_candles(request, state)
            baseline = run_sma_backtest(
                backtest_candles,
                short_window=request.short_window,
                long_window=request.long_window,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
            simulation = run_trade_sequence_monte_carlo(
                [trade.net_pnl for trade in baseline.trade_history],
                initial_capital=request.initial_capital,
                simulations=request.simulations,
                seed=request.seed,
                return_jitter_pct=request.return_jitter_pct,
                drawdown_threshold_pct=request.drawdown_threshold_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid Monte Carlo backtest data: {exc}"
            ) from exc

        execution_model = {
            "signal_execution": "next_bar_open",
            "fee_rate": request.fee_rate,
            "slippage_rate": request.slippage_rate,
            "max_volume_participation": request.max_volume_participation,
            "volume_limit_behavior": "partial_fill_then_cancel",
        }
        payload: dict[str, Any] = {
            "monte_carlo": simulation.as_dict(),
            "baseline": _backtest_metrics_payload(baseline),
            "parameters": {
                "short_window": request.short_window,
                "long_window": request.long_window,
                "initial_capital": request.initial_capital,
                "position_size_pct": request.position_size_pct,
            },
            "execution_model": execution_model,
            "klines_used": [_serialize_kline(kline) for kline in candles],
            "data_version": request.data_version,
        }
        result_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload["result_hash"] = result_hash
        if persist:
            run_id = state.store.save_backtest_experiment(
                strategy_name="sma_monte_carlo",
                strategy_version=_strategy_version(),
                data_version=request.data_version,
                data_start=str(backtest_candles[0].get("open_time")),
                data_end=str(backtest_candles[-1].get("open_time")),
                strategy_parameters={
                    "short_window": request.short_window,
                    "long_window": request.long_window,
                    "initial_capital": request.initial_capital,
                    "position_size_pct": request.position_size_pct,
                },
                execution_model=execution_model,
                risk_model={
                    "stop_loss_pct": request.stop_loss_pct,
                    "take_profit_pct": request.take_profit_pct,
                },
                environment={
                    "app_version": "0.1.0",
                    "python_version": platform.python_version(),
                    "model_version": "not_applicable:sma_rule",
                    "backtest_engine": "event_driven_simulation_v1",
                },
                request=request.model_dump(mode="json", exclude_none=True),
                result=payload,
                result_hash=result_hash,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            payload["backtest_run_id"] = run_id
        return payload

    def _run_rolling_backtest(
        request: RollingBacktestRequest,
        state: AppState,
        *,
        persist: bool,
    ) -> dict[str, Any]:
        """Run and optionally persist a fixed-parameter rolling-window study."""

        from app.engine.rolling_backtest import run_rolling_sma_backtest

        try:
            candles, backtest_candles = _load_backtest_candles(request, state)
            result = run_rolling_sma_backtest(
                candles=backtest_candles,
                window_size=request.window_size,
                step_size=request.step_size,
                short_window=request.short_window,
                long_window=request.long_window,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid rolling backtest data: {exc}"
            ) from exc

        execution_model = {
            "signal_execution": "next_bar_open",
            "fee_rate": request.fee_rate,
            "slippage_rate": request.slippage_rate,
            "max_volume_participation": request.max_volume_participation,
            "volume_limit_behavior": "partial_fill_then_cancel",
            "capital_allocation": "independent_per_window",
        }
        payload: dict[str, Any] = {
            **result.as_dict(),
            "parameters": {
                "short_window": request.short_window,
                "long_window": request.long_window,
                "initial_capital": request.initial_capital,
                "position_size_pct": request.position_size_pct,
            },
            "execution_model": execution_model,
            "klines_used": [_serialize_kline(kline) for kline in candles],
            "data_version": request.data_version,
        }
        result_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload["result_hash"] = result_hash

        if persist:
            run_id = state.store.save_backtest_experiment(
                strategy_name="sma_rolling_window",
                strategy_version=_strategy_version(),
                data_version=request.data_version,
                data_start=str(backtest_candles[0].get("open_time")) if backtest_candles else None,
                data_end=str(backtest_candles[-1].get("open_time")) if backtest_candles else None,
                strategy_parameters={
                    "short_window": request.short_window,
                    "long_window": request.long_window,
                    "initial_capital": request.initial_capital,
                    "position_size_pct": request.position_size_pct,
                    "window_size": request.window_size,
                    "step_size": request.step_size or request.window_size,
                },
                execution_model=execution_model,
                risk_model={
                    "stop_loss_pct": request.stop_loss_pct,
                    "take_profit_pct": request.take_profit_pct,
                },
                environment={
                    "app_version": "0.1.0",
                    "python_version": platform.python_version(),
                    "model_version": "not_applicable:sma_rule",
                    "backtest_engine": "event_driven_simulation_v1",
                },
                request=request.model_dump(mode="json", exclude_none=True),
                result=payload,
                result_hash=result_hash,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            payload["backtest_run_id"] = run_id
        return payload

    def _run_parameter_sensitivity(
        request: ParameterSensitivityRequest,
        state: AppState,
        *,
        persist: bool,
    ) -> dict[str, Any]:
        """Compare bounded local fixed-parameter SMA variations without selecting a winner."""

        from app.engine.parameter_sensitivity import (
            MAX_SENSITIVITY_CANDIDATES,
            run_sma_parameter_sensitivity,
        )

        try:
            candles, backtest_candles = _load_backtest_candles(request, state)
            trials = run_sma_parameter_sensitivity(
                candles=backtest_candles,
                short_window=request.short_window,
                long_window=request.long_window,
                short_offsets=request.short_offsets,
                long_offsets=request.long_offsets,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid parameter-sensitivity backtest data: {exc}"
            ) from exc

        baseline = next(
            trial for trial in trials if trial.short_offset == 0 and trial.long_offset == 0
        )
        execution_model = {
            "signal_execution": "next_bar_open",
            "fee_rate": request.fee_rate,
            "slippage_rate": request.slippage_rate,
            "max_volume_participation": request.max_volume_participation,
            "volume_limit_behavior": "partial_fill_then_cancel",
        }
        payload: dict[str, Any] = {
            "sensitivity": {
                "baseline_parameters": {
                    "short_window": request.short_window,
                    "long_window": request.long_window,
                },
                "short_offsets": sorted(set(request.short_offsets)),
                "long_offsets": sorted(set(request.long_offsets)),
                "candidate_count": len(trials),
                "maximum_candidate_count": MAX_SENSITIVITY_CANDIDATES,
                "parameter_mode": "bounded_local_variation",
                "in_sample_only": True,
                "auto_selection": False,
            },
            "baseline": baseline.as_dict(),
            "candidates": [trial.as_dict() for trial in trials],
            "execution_model": execution_model,
            "klines_used": [_serialize_kline(kline) for kline in candles],
            "data_version": request.data_version,
        }
        result_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload["result_hash"] = result_hash

        if persist:
            run_id = state.store.save_backtest_experiment(
                strategy_name="sma_parameter_sensitivity",
                strategy_version=_strategy_version(),
                data_version=request.data_version,
                data_start=str(backtest_candles[0].get("open_time")),
                data_end=str(backtest_candles[-1].get("open_time")),
                strategy_parameters={
                    "short_window": request.short_window,
                    "long_window": request.long_window,
                    "short_offsets": sorted(set(request.short_offsets)),
                    "long_offsets": sorted(set(request.long_offsets)),
                    "initial_capital": request.initial_capital,
                    "position_size_pct": request.position_size_pct,
                },
                execution_model=execution_model,
                risk_model={
                    "stop_loss_pct": request.stop_loss_pct,
                    "take_profit_pct": request.take_profit_pct,
                },
                environment={
                    "app_version": "0.1.0",
                    "python_version": platform.python_version(),
                    "model_version": "not_applicable:sma_rule",
                    "backtest_engine": "event_driven_simulation_v1",
                },
                request=request.model_dump(mode="json", exclude_none=True),
                result=payload,
                result_hash=result_hash,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            payload["backtest_run_id"] = run_id
        return payload

    def _run_grid_search(
        request: GridSearchRequest,
        state: AppState,
        *,
        persist: bool,
    ) -> dict[str, Any]:
        """Run and optionally persist a bounded in-sample SMA parameter grid."""

        from app.engine.backtest import run_sma_grid_search

        try:
            candles, backtest_candles = _load_backtest_candles(request, state)
            result = run_sma_grid_search(
                candles=backtest_candles,
                short_windows=request.short_windows,
                long_windows=request.long_windows,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid grid-search backtest data: {exc}"
            ) from exc

        execution_model = {
            "signal_execution": "next_bar_open",
            "fee_rate": request.fee_rate,
            "slippage_rate": request.slippage_rate,
            "max_volume_participation": request.max_volume_participation,
            "volume_limit_behavior": "partial_fill_then_cancel",
        }
        payload: dict[str, Any] = {
            "search": {
                "ranking": [
                    "total_pnl_desc",
                    "max_drawdown_asc",
                    "trades_desc",
                    "short_window_asc",
                    "long_window_asc",
                ],
                "short_windows": result.short_windows,
                "long_windows": result.long_windows,
                "candidate_count": len(result.trials),
                "in_sample_only": True,
            },
            "best": {
                "parameters": {
                    "short_window": result.best_trial.parameters.short_window,
                    "long_window": result.best_trial.parameters.long_window,
                },
                "result": _backtest_metrics_payload(result.best_trial.result),
            },
            "candidates": [
                {
                    "parameters": {
                        "short_window": trial.parameters.short_window,
                        "long_window": trial.parameters.long_window,
                    },
                    "total_pnl": trial.result.total_pnl,
                    "total_return_pct": trial.result.total_return_pct,
                    "max_drawdown": trial.result.max_drawdown,
                    "trades": trial.result.trades,
                    "win_rate": trial.result.win_rate,
                    "profit_factor": trial.result.profit_factor,
                    "total_fees": trial.result.total_fees,
                }
                for trial in result.trials
            ],
            "execution_model": execution_model,
            "klines_used": [_serialize_kline(kline) for kline in candles],
            "data_version": request.data_version,
        }
        result_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload["result_hash"] = result_hash

        if persist:
            strategy_parameters = {
                "short_windows": result.short_windows,
                "long_windows": result.long_windows,
                "initial_capital": request.initial_capital,
                "position_size_pct": request.position_size_pct,
            }
            risk_model = {
                "stop_loss_pct": request.stop_loss_pct,
                "take_profit_pct": request.take_profit_pct,
            }
            environment = {
                "app_version": "0.1.0",
                "python_version": platform.python_version(),
                "model_version": "not_applicable:sma_rule",
                "backtest_engine": "event_driven_simulation_v1",
            }
            run_id = state.store.save_backtest_experiment(
                strategy_name="sma_grid_search",
                strategy_version=_strategy_version(),
                data_version=request.data_version,
                data_start=str(backtest_candles[0].get("open_time")),
                data_end=str(backtest_candles[-1].get("open_time")),
                strategy_parameters=strategy_parameters,
                execution_model=execution_model,
                risk_model=risk_model,
                environment=environment,
                request=request.model_dump(mode="json", exclude_none=True),
                result=payload,
                result_hash=result_hash,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            payload["backtest_run_id"] = run_id
        return payload

    def _run_portfolio_backtest(
        request: PortfolioBacktestRequest,
        state: AppState,
        *,
        persist: bool,
    ) -> dict[str, Any]:
        """Run and optionally persist a fixed-weight SMA portfolio experiment."""

        from app.engine.backtest import PortfolioStrategyConfig, run_multi_sma_backtest

        try:
            candles, backtest_candles = _load_backtest_candles(request, state)
            result = run_multi_sma_backtest(
                candles=backtest_candles,
                strategies=[
                    PortfolioStrategyConfig(
                        name=strategy.name,
                        short_window=strategy.short_window,
                        long_window=strategy.long_window,
                        weight=strategy.weight,
                    )
                    for strategy in request.strategies
                ],
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid portfolio backtest data: {exc}"
            ) from exc

        execution_model = {
            "signal_execution": "next_bar_open",
            "fee_rate": request.fee_rate,
            "slippage_rate": request.slippage_rate,
            "max_volume_participation": request.max_volume_participation,
            "volume_limit_behavior": "partial_fill_then_cancel",
            "capital_allocation": "fixed_weight_separate_capital",
        }
        payload: dict[str, Any] = {
            "initial_capital": result.initial_capital,
            "final_equity": result.final_equity,
            "total_pnl": result.total_pnl,
            "trades": result.trades,
            "win_rate": result.win_rate,
            "max_drawdown": result.max_drawdown,
            "equity_curve": result.equity_curve,
            "total_fees": result.total_fees,
            "gross_pnl": result.gross_pnl,
            "total_return_pct": result.total_return_pct,
            "profit_factor": result.profit_factor,
            "portfolio": {
                "allocation_model": "fixed_weight_separate_capital",
                "strategies": [
                    {
                        "name": item.name,
                        "weight": item.weight,
                        "allocated_capital": item.allocated_capital,
                        "result": _backtest_metrics_payload(item.result),
                    }
                    for item in result.strategies
                ],
            },
            "execution_model": execution_model,
            "klines_used": [_serialize_kline(kline) for kline in candles],
            "data_version": request.data_version,
        }
        result_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload["result_hash"] = result_hash

        if persist:
            strategy_parameters = {
                "strategies": [strategy.model_dump() for strategy in request.strategies],
                "initial_capital": request.initial_capital,
                "position_size_pct": request.position_size_pct,
            }
            risk_model = {
                "stop_loss_pct": request.stop_loss_pct,
                "take_profit_pct": request.take_profit_pct,
            }
            environment = {
                "app_version": "0.1.0",
                "python_version": platform.python_version(),
                "model_version": "not_applicable:sma_rule",
                "backtest_engine": "event_driven_simulation_v1",
            }
            run_id = state.store.save_backtest_experiment(
                strategy_name="sma_portfolio",
                strategy_version=_strategy_version(),
                data_version=request.data_version,
                data_start=str(backtest_candles[0].get("open_time")) if backtest_candles else None,
                data_end=str(backtest_candles[-1].get("open_time")) if backtest_candles else None,
                strategy_parameters=strategy_parameters,
                execution_model=execution_model,
                risk_model=risk_model,
                environment=environment,
                request=request.model_dump(mode="json", exclude_none=True),
                result=payload,
                result_hash=result_hash,
                created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            payload["backtest_run_id"] = run_id
        return payload

    @app.post("/api/v1/backtest/in-out-sample")
    async def in_out_sample_backtest_endpoint(
        request: InOutSampleBacktestRequest, state: AppState = Depends(get_state)
    ):
        """Run fixed-parameter in-sample / out-of-sample SMA diagnostics."""
        return _run_in_out_sample_backtest(request, state, persist=True)

    @app.post("/api/v1/backtest/bootstrap")
    async def bootstrap_backtest_endpoint(
        request: BootstrapBacktestRequest, state: AppState = Depends(get_state)
    ):
        """Run bounded deterministic with-replacement Bootstrap diagnostics."""
        return _run_bootstrap_backtest(request, state, persist=True)

    @app.post("/api/v1/backtest/monte-carlo")
    async def monte_carlo_backtest_endpoint(
        request: MonteCarloBacktestRequest, state: AppState = Depends(get_state)
    ):
        """Run bounded deterministic trade-order Monte Carlo diagnostics."""
        return _run_monte_carlo_backtest(request, state, persist=True)

    @app.post("/api/v1/backtest/rolling")
    async def rolling_backtest_endpoint(
        request: RollingBacktestRequest,
        state: AppState = Depends(get_state),
    ):
        """Run independent fixed-parameter SMA diagnostics over rolling windows."""

        return _run_rolling_backtest(request, state, persist=True)

    @app.post("/api/v1/backtest/parameter-sensitivity")
    async def parameter_sensitivity_backtest_endpoint(
        request: ParameterSensitivityRequest,
        state: AppState = Depends(get_state),
    ):
        """Run bounded local SMA parameter-sensitivity diagnostics."""

        return _run_parameter_sensitivity(request, state, persist=True)

    @app.post("/api/v1/backtest/grid-search")
    async def grid_search_backtest_endpoint(
        request: GridSearchRequest,
        state: AppState = Depends(get_state),
    ):
        """Run a bounded deterministic SMA parameter grid search."""

        return _run_grid_search(request, state, persist=True)

    @app.post("/api/v1/backtest/portfolio")
    async def portfolio_backtest_endpoint(
        request: PortfolioBacktestRequest,
        state: AppState = Depends(get_state),
    ):
        """Run a deterministic fixed-weight portfolio of SMA strategies."""

        return _run_portfolio_backtest(request, state, persist=True)

    @app.post("/api/v1/backtest")
    async def backtest_endpoint(
        request: BacktestRequest,
        state: AppState = Depends(get_state),
    ):
        """Run SMA backtest from inline candles or a quality-approved data version."""

        return _run_backtest(request, state, persist=True)

    @app.get("/api/v1/backtests/{run_id}", dependencies=[Depends(require_api_key)])
    async def backtest_experiment_endpoint(run_id: int, state: AppState = Depends(get_state)):
        """Fetch the immutable metadata needed to audit one backtest run."""

        run = state.store.backtest_experiment(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Backtest run {run_id} was not found")
        return run

    @app.post("/api/v1/backtests/{run_id}/reproduce", dependencies=[Depends(require_api_key)])
    async def reproduce_backtest_endpoint(run_id: int, state: AppState = Depends(get_state)):
        """Replay a version-bound backtest and report whether the result hash matches."""

        run = state.store.backtest_experiment(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Backtest run {run_id} was not found")
        if not run["data_version"]:
            raise HTTPException(
                status_code=409,
                detail="only data-version-bound backtests can be reproduced through the catalog",
            )
        raw_request = run["request"]
        if "strategies" in raw_request:
            request = PortfolioBacktestRequest.model_validate(raw_request)
            replay = _run_portfolio_backtest(request, state, persist=False)
        elif run["strategy_name"] == "sma_parameter_sensitivity":
            request = ParameterSensitivityRequest.model_validate(raw_request)
            replay = _run_parameter_sensitivity(request, state, persist=False)
        elif "short_windows" in raw_request and "long_windows" in raw_request:
            request = GridSearchRequest.model_validate(raw_request)
            replay = _run_grid_search(request, state, persist=False)
        elif "window_size" in raw_request:
            request = RollingBacktestRequest.model_validate(raw_request)
            replay = _run_rolling_backtest(request, state, persist=False)
        elif run["strategy_name"] == "sma_in_out_sample":
            request = InOutSampleBacktestRequest.model_validate(raw_request)
            replay = _run_in_out_sample_backtest(request, state, persist=False)
        elif run["strategy_name"] == "sma_bootstrap":
            request = BootstrapBacktestRequest.model_validate(raw_request)
            replay = _run_bootstrap_backtest(request, state, persist=False)
        elif "simulations" in raw_request and "seed" in raw_request:
            request = MonteCarloBacktestRequest.model_validate(raw_request)
            replay = _run_monte_carlo_backtest(request, state, persist=False)
        else:
            request = BacktestRequest.model_validate(raw_request)
            replay = _run_backtest(request, state, persist=False)
        return {
            "run_id": run_id,
            "expected_result_hash": run["result_hash"],
            "actual_result_hash": replay["result_hash"],
            "reproducible": replay["result_hash"] == run["result_hash"],
            "result": replay,
        }

    @app.get("/api/v1/strategies/{name}/versions", dependencies=[Depends(require_api_key)])
    async def strategy_versions_endpoint(
        name: str,
        state: AppState = Depends(get_state),
        limit: int = Query(50, ge=1, le=200),
    ):
        if not any(item["name"] == name for item in state.engine.list_strategies()):
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")
        return {"strategy": name, "versions": state.store.strategy_versions(name, limit=limit)}

    @app.get("/api/v1/strategies/{name}/backtests", dependencies=[Depends(require_api_key)])
    async def strategy_backtests_endpoint(
        name: str,
        state: AppState = Depends(get_state),
        limit: int = Query(20, ge=1, le=100),
    ):
        if not any(item["name"] == name for item in state.engine.list_strategies()):
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")
        return {
            "strategy": name,
            "runs": state.store.recent_strategy_backtest_runs(name, limit=limit),
        }

    @app.post(
        "/api/v1/strategies/{name}/backtests/walk-forward",
        dependencies=[Depends(require_api_key)],
    )
    async def strategy_walk_forward_endpoint(
        name: str,
        request: WalkForwardRequest,
        state: AppState = Depends(get_state),
    ):
        """Run and persist strictly out-of-sample WFO evidence for one strategy version."""
        if not any(item["name"] == name for item in state.engine.list_strategies()):
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")
        version = state.store.latest_strategy_version(name)
        if version is None:
            raise HTTPException(status_code=409, detail="strategy has no immutable version record")
        from app.engine.strategy_governance import SMAParameters, run_walk_forward_backtest

        try:
            _, backtest_candles = _load_backtest_candles(request, state)
            result = run_walk_forward_backtest(
                backtest_candles,
                train_size=request.train_size,
                test_size=request.test_size,
                step_size=request.step_size,
                candidate_parameters=[
                    SMAParameters(short_window=item.short_window, long_window=item.long_window)
                    for item in request.candidate_parameters
                ]
                or None,
                short_window=request.short_window,
                long_window=request.long_window,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
                fee_rate=request.fee_rate,
                slippage_rate=request.slippage_rate,
                max_volume_participation=request.max_volume_participation,
                stop_loss_pct=request.stop_loss_pct,
                take_profit_pct=request.take_profit_pct,
            )
        except DatasetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetQualityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (KeyError, MarketDataError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid walk-forward data: {exc}"
            ) from exc

        payload = result.as_dict()
        run_id = state.store.save_strategy_backtest_run(
            strategy_name=name,
            strategy_version=int(version["version"]),
            kind="walk_forward",
            request=request.model_dump(mode="json"),
            result=payload,
            created_at=datetime.utcnow().isoformat(),
        )
        return {
            "id": run_id,
            "strategy": name,
            "strategy_version": version["version"],
            "kind": "walk_forward",
            "result": payload,
            "disclaimer": "Only out-of-sample folds are aggregated; this does not approve or enable live trading.",
        }

    @app.post(
        "/api/v1/strategies/{name}/promotion/evaluate",
        dependencies=[Depends(require_api_key)],
    )
    async def evaluate_strategy_promotion_endpoint(
        name: str,
        request: StrategyPromotionEvaluateRequest,
        state: AppState = Depends(get_state),
    ):
        """Create an auditable promotion review from persisted paper executions."""
        if not any(item["name"] == name for item in state.engine.list_strategies()):
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}")
        version = state.store.latest_strategy_version(name)
        if version is None:
            raise HTTPException(status_code=409, detail="strategy has no immutable version record")
        evidence = state.store.paper_strategy_performance(name)
        thresholds = request.model_dump(mode="json")
        profit_factor = evidence["profit_factor"]
        profit_factor_ok = (profit_factor is None and evidence["total_pnl"] > 0) or (
            profit_factor is not None and profit_factor >= request.min_profit_factor
        )
        checks = {
            "closed_trades": evidence["closed_trades"] >= request.min_closed_trades,
            "win_rate": evidence["win_rate"] >= request.min_win_rate,
            "profit_factor": profit_factor_ok,
            "total_pnl": evidence["total_pnl"] >= request.min_total_pnl,
        }
        evidence["checks"] = checks
        status = "eligible" if all(checks.values()) else "insufficient_evidence"
        review = state.store.create_strategy_promotion_review(
            strategy_name=name,
            strategy_version=int(version["version"]),
            status=status,
            evidence=evidence,
            thresholds=thresholds,
            requested_at=datetime.utcnow().isoformat(),
        )
        return {
            "review": review,
            "can_request_manual_approval": status == "eligible",
            "live_mode_changed": False,
            "disclaimer": "Promotion evidence never changes strategy mode or bypasses live-trading guards.",
        }

    @app.post(
        "/api/v1/strategies/{name}/promotion/{review_id}/decision",
        dependencies=[Depends(require_api_key)],
    )
    async def decide_strategy_promotion_endpoint(
        name: str,
        review_id: int,
        request: StrategyPromotionDecisionRequest,
        state: AppState = Depends(get_state),
    ):
        review = state.store.decide_strategy_promotion_review(
            review_id,
            strategy_name=name,
            approved=request.approved,
            decided_by=request.decided_by,
            note=request.note,
            decided_at=datetime.utcnow().isoformat(),
        )
        if review is None:
            raise HTTPException(
                status_code=409, detail="promotion review is not eligible or already decided"
            )
        return {
            "review": review,
            "live_mode_changed": False,
            "next_step": "Use the existing strategy mode endpoint only after reviewing all live-trading safeguards.",
        }

    @app.post("/api/v1/strategies/suggest")
    async def suggest_strategy_endpoint(request: SuggestRequest):
        """Suggest a strategy (kind + params + rationale) from klines."""
        from app.engine.strategy_recommender import recommend_strategy

        return recommend_strategy(
            candles=request.klines,
            prefer=request.prefer,
        )

    @app.get("/api/v1/strategies/leaderboard")
    async def strategies_leaderboard(state: AppState = Depends(get_state)):
        """Rank strategies by composite score (Sharpe + winrate + DD-adjusted)."""

        # Use a fresh tracker from in-memory equity (no real persistence).
        # In production, this would aggregate from store-recorded outcomes.
        return {"strategies": [], "note": "live leaderboard requires trade history"}

    @app.get("/api/v1/portfolio/metrics")
    async def portfolio_metrics(state: AppState = Depends(get_state)):
        """Compute Sharpe / Sortino / max DD from running equity curve."""
        # Without persistent trade history, return empty metrics.
        from app.engine.portfolio_metrics import compute_metrics

        return compute_metrics([]).__dict__

    @app.get("/api/v1/portfolio/equity-curves")
    async def portfolio_equity_curves(
        since: str | None = None,
        state: AppState = Depends(get_state),
    ):
        """Multi-strategy equity curves for portfolio chart."""
        from app.engine.equity_curve import EquityCurveStore

        store = EquityCurveStore(state.settings.sqlite_path)
        curves = store.all_strategies_equity_curves(since=since)
        # Return as JSON-serializable dict.
        out: dict[str, Any] = {}
        for strategy, snaps in curves.items():
            out[strategy] = [
                {"timestamp": s.timestamp, "equity": s.equity, "trade_id": s.trade_id}
                for s in snaps
            ]
        return {"curves": out}

    @app.get("/api/v1/strategies/{name}/equity-curve")
    async def strategy_equity_curve(name: str, state: AppState = Depends(get_state)):
        """Single strategy equity curve time series."""
        from app.engine.equity_curve import EquityCurveStore

        store = EquityCurveStore(state.settings.sqlite_path)
        history = store.history(name)
        return {
            "strategy": name,
            "history": [
                {"timestamp": s.timestamp, "equity": s.equity, "trade_id": s.trade_id}
                for s in history
            ],
        }

    @app.get("/api/v1/trade-history")
    async def trade_history(
        limit: int = 100,
        strategy: str | None = None,
        exchange: str | None = None,
        state: AppState = Depends(get_state),
    ):
        """List paper (or live) trade history — newest first."""
        orders = state.store.recent_paper_orders(limit=limit, strategy=strategy, exchange=exchange)
        return {"trades": orders}

    @app.post("/api/v1/atr-sizing")
    async def atr_sizing_endpoint(request: AIAnalyzeRequest):
        """ATR-based volatility-adjusted position sizing."""

        from app.engine.atr_sizing import atr_position_size, compute_atr

        closes = []
        if state.data_sources:
            client = state.data_sources.get(request.exchange.lower())
            if client is not None:
                try:
                    klines = await client.get_klines(
                        request.symbol, interval=request.interval, limit=50
                    )
                    closes = [float(k.get("close", 0)) for k in klines]
                except Exception:
                    pass

        atr = compute_atr(closes) if closes else 0.0
        if atr <= 0:
            return {"error": "insufficient data to compute ATR"}

        try:
            r = atr_position_size(
                account_equity=10_000.0,
                entry_price=request.entry_price
                if hasattr(request, "entry_price")
                else closes[-1]
                if closes
                else 100.0,
                atr=atr,
                risk_pct=0.02,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return r.__dict__

    @app.get("/api/v1/prices")
    async def prices_snapshot(state: AppState = Depends(get_state)):
        """Latest price feed snapshot — sourced from registered exchanges."""
        from app.engine.realtime_feed import PriceFeed

        # Singleton: attached to app.state for shared access.
        feed: PriceFeed = getattr(app.state, "price_feed", None) or PriceFeed()
        return feed.latest_dict()

    @app.get("/api/v1/market/top-movers")
    async def top_movers(
        state: AppState = Depends(get_state),
        exchange: str | None = None,
        symbols: str | None = None,
    ) -> dict[str, Any]:
        """24h price change for a small watchlist (used by the TopTicker).

        Default behaviour: pull the TopTicker watchlist (10 popular USDT
        perpetuals) from the default exchange. Override either via query
        params — `exchange` chooses the venue, `symbols` is a CSV.

        The result is cached for 20s per (exchange, symbols) key. The
        upstream `get_ticker` call is what carries `price_change_pct_24h`
        (Binance `/fapi/v1/ticker/24hr`, OKX `/api/v5/market/ticker`), so
        adapters that don't surface the field will return 0.0 there.
        """
        watchlist = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "ADAUSDT",
            "DOGEUSDT",
            "AVAXUSDT",
            "LINKUSDT",
            "DOTUSDT",
        ]
        ex_name = (exchange or settings.default_exchange).lower()
        sym_list = [s.strip() for s in (symbols or ",".join(watchlist)).split(",") if s.strip()]
        cache_key = f"{ex_name}:{','.join(sym_list)}"

        async def _fetch() -> dict[str, Any]:
            items: list[dict[str, Any]] = []
            try:
                client = state.get_exchange(ex_name)
            except HTTPException as exc:
                return {
                    "exchange": ex_name,
                    "items": items,
                    "error": exc.detail,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            for sym in sym_list:
                try:
                    t = await call_exchange(lambda: client.get_ticker(sym))
                except HTTPException as exc:
                    items.append(
                        {
                            "symbol": sym,
                            "price": None,
                            "change_pct_24h": None,
                            "error": exc.detail,
                        }
                    )
                    continue
                items.append(
                    {
                        "symbol": sym,
                        "price": float(t.get("last_price", 0)) or None,
                        "change_pct_24h": t.get("price_change_pct_24h"),
                        "change_24h": t.get("price_change_24h"),
                        "high_24h": t.get("high_24h"),
                        "low_24h": t.get("low_24h"),
                    }
                )
            return {
                "exchange": ex_name,
                "items": items,
                "timestamp": datetime.utcnow().isoformat(),
            }

        return await state.ticker_cache.get_or_set(cache_key, _fetch)

    @app.get("/api/v1/ai/insights", dependencies=[Depends(require_api_key)])
    async def llm_insights(
        minutes: int = Query(1440, ge=1, le=43_200),
        limit: int = Query(2_000, ge=1, le=5_000),
        state: AppState = Depends(get_state),
    ):
        """Aggregate persisted LLM decision events for the audit workspace.

        This endpoint deliberately uses SQLite audit events rather than
        Prometheus counters: it provides a bounded, restart-safe operational
        history and does not attempt to estimate provider billing.
        """
        cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
        events = state.store.recent_events(category="llm", event_type="llm_decision", limit=limit)
        events = [event for event in events if event.get("timestamp", "") >= cutoff]
        outcome_events = state.store.recent_events(
            category="llm", event_type="llm_decision_outcome", limit=limit
        )
        outcome_events = [event for event in outcome_events if event.get("timestamp", "") >= cutoff]

        def as_non_negative_int(value: Any) -> int:
            try:
                return max(0, int(float(value or 0)))
            except (TypeError, ValueError):
                return 0

        def percentile_95(values: list[int]) -> int:
            if not values:
                return 0
            ordered = sorted(values)
            index = max(0, (len(ordered) * 95 + 99) // 100 - 1)
            return ordered[index]

        decisions = {"buy": 0, "sell": 0, "hold": 0}
        failures: dict[str, int] = {}
        model_stats: dict[tuple[str, str], dict[str, Any]] = {}
        successful_calls = 0
        failed_calls = 0
        prompt_tokens = 0
        completion_tokens = 0
        latencies: list[int] = []

        for event in events:
            details = event.get("details")
            if not isinstance(details, dict):
                details = {}
            provider = str(details.get("provider") or "unknown")
            model = str(details.get("model") or state.settings.llm_model or "unconfigured")
            key = (provider, model)
            stats = model_stats.setdefault(
                key,
                {
                    "provider": provider,
                    "model": model,
                    "calls": 0,
                    "successful_calls": 0,
                    "failed_calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "latencies": [],
                },
            )
            stats["calls"] += 1

            prompt = as_non_negative_int(details.get("prompt_tokens"))
            completion = as_non_negative_int(details.get("completion_tokens"))
            latency = as_non_negative_int(details.get("latency_ms"))
            prompt_tokens += prompt
            completion_tokens += completion
            latencies.append(latency)
            stats["prompt_tokens"] += prompt
            stats["completion_tokens"] += completion
            stats["latencies"].append(latency)

            failure = details.get("failed")
            if failure:
                failure_name = str(failure)
                failed_calls += 1
                stats["failed_calls"] += 1
                failures[failure_name] = failures.get(failure_name, 0) + 1
                continue

            successful_calls += 1
            stats["successful_calls"] += 1
            decision = str(details.get("decision") or "hold").lower()
            if decision in decisions:
                decisions[decision] += 1

        calls_total = len(events)
        models = [
            {
                "provider": stats["provider"],
                "model": stats["model"],
                "calls": stats["calls"],
                "successful_calls": stats["successful_calls"],
                "failed_calls": stats["failed_calls"],
                "prompt_tokens": stats["prompt_tokens"],
                "completion_tokens": stats["completion_tokens"],
                "total_tokens": stats["prompt_tokens"] + stats["completion_tokens"],
                "avg_latency_ms": round(sum(stats["latencies"]) / len(stats["latencies"]), 2)
                if stats["latencies"]
                else 0,
                "p95_latency_ms": percentile_95(stats["latencies"]),
            }
            for stats in model_stats.values()
        ]
        models.sort(key=lambda item: (-item["calls"], item["provider"], item["model"]))

        return {
            "window_minutes": minutes,
            "generated_at": datetime.utcnow().isoformat(),
            "event_limit": limit,
            "calls_total": calls_total,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "safety_rejections": failures.get("safety_rejected", 0),
            "success_rate": round(successful_calls / calls_total * 100, 2) if calls_total else 0,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "p95_latency_ms": percentile_95(latencies),
            "decisions": decisions,
            "failures": failures,
            "models": models,
            "effectiveness": effectiveness_summary(events, outcome_events),
        }

    @app.get("/api/v1/ai/decisions", dependencies=[Depends(require_api_key)])
    async def llm_decision_history(
        symbol: str | None = Query(None, min_length=1, max_length=32),
        limit: int = Query(100, ge=1, le=1_000),
        state: AppState = Depends(get_state),
    ):
        """Return persisted AI input/output summaries for audit and replay."""
        events = state.store.recent_events(category="llm", event_type="llm_decision", limit=limit)
        if symbol:
            events = [event for event in events if event.get("symbol") == symbol]
        return {"items": events, "count": len(events)}

    @app.get("/api/v1/ai/decisions/{event_id}/replay", dependencies=[Depends(require_api_key)])
    async def llm_decision_replay(event_id: int, state: AppState = Depends(get_state)):
        """Replay a historical decision's immutable input/output audit payload."""
        events = state.store.recent_events(category="llm", event_type="llm_decision", limit=5_000)
        event = next((item for item in events if item.get("id") == event_id), None)
        if event is None:
            raise HTTPException(status_code=404, detail=f"AI decision {event_id} was not found")
        outcomes = state.store.recent_events(
            category="llm", event_type="llm_decision_outcome", limit=5_000
        )
        outcome = next(
            (
                item
                for item in outcomes
                if isinstance(item.get("details"), dict)
                and item["details"].get("decision_event_id") == event_id
            ),
            None,
        )
        return {"decision": event, "outcome": outcome}

    @app.post("/api/v1/ai/decisions/{event_id}/outcome", dependencies=[Depends(require_api_key)])
    async def record_llm_decision_outcome(
        event_id: int,
        request: AIDecisionOutcomeRequest,
        state: AppState = Depends(get_state),
    ):
        """Append an outcome event without mutating the original AI decision."""
        events = state.store.recent_events(category="llm", event_type="llm_decision", limit=5_000)
        decision = next((item for item in events if item.get("id") == event_id), None)
        if decision is None:
            raise HTTPException(status_code=404, detail=f"AI decision {event_id} was not found")
        record_event(
            category="llm",
            event_type="llm_decision_outcome",
            message=f"AI decision {event_id} outcome recorded",
            exchange=decision.get("exchange"),
            symbol=decision.get("symbol"),
            details={"decision_event_id": event_id, **request.model_dump(mode="json")},
        )
        return {"decision_event_id": event_id, "recorded": True}

    @app.post("/api/v1/ai/analyze", dependencies=[Depends(require_api_key)])
    async def ai_analyze(
        request: AIAnalyzeRequest,
        state: AppState = Depends(get_state),
    ):
        """调用大模型分析市场并返回开单建议（不自动下单）。"""

        from app.engine.llm_context import DefaultLLMContextProvider
        from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalyzerConfig

        llm_config = LLMAnalyzerConfig(
            api_key=state.settings.llm_api_key,
            base_url=state.settings.llm_base_url,
            model=state.settings.llm_model,
            temperature=state.settings.llm_temperature,
            max_tokens=state.settings.llm_max_tokens,
            request_timeout=state.settings.llm_request_timeout,
            min_request_interval_seconds=state.settings.llm_min_request_interval_seconds,
            circuit_failure_threshold=state.settings.llm_circuit_failure_threshold,
            circuit_cooldown_seconds=state.settings.llm_circuit_cooldown_seconds,
            min_candles=state.settings.llm_min_candles,
            max_candles=state.settings.llm_max_candles,
        )

        client = state.data_sources.get(request.exchange.lower())
        if client is None:
            raise HTTPException(
                status_code=404,
                detail=f"Data source not configured: {request.exchange}",
            )

        # 获取持仓上下文（如果有）
        position_ctx = None
        position = await state.engine.position_manager.get_position(
            request.exchange, request.symbol
        )
        if position and not position.is_flat():
            position_ctx = {
                "side": position.side,
                "quantity": position.quantity,
                "avg_entry_price": position.avg_entry_price,
                "unrealized_pnl": position.unrealized_pnl,
                "equity": state.engine.paper_account.cash
                + state.engine.paper_account.summary().get("unrealized_pnl", 0),
            }

        context_provider = DefaultLLMContextProvider(
            risk_manager=state.engine.risk_manager, store=state.store
        )
        analyzer = LLMAnalyzer(llm_config, on_decision=_on_llm_decision)
        try:
            risk_context = await context_provider.get_risk_context()
            trade_history = await context_provider.get_trade_history(request.symbol)
            backtest_performance = await context_provider.get_backtest_performance(request.symbol)
            recent_ai_decisions = await context_provider.get_recent_ai_decisions(request.symbol)
            result = await analyzer.analyze(
                exchange=client,
                symbol=request.symbol,
                interval=request.interval,
                limit=request.limit,
                position_context=position_ctx,
                risk_context=risk_context,
                trade_history=trade_history,
                backtest_performance=backtest_performance,
                recent_ai_decisions=recent_ai_decisions,
            )
            return result.to_dict()
        finally:
            await analyzer.close()

    # ── LLM 策略（D / B / A）管理 API ─────────────────────────

    @app.post("/api/v1/strategies/llm", dependencies=[Depends(require_api_key)])
    async def create_llm_strategy(
        request: LLMStrategyCreateRequest,
        state: AppState = Depends(get_state),
    ):
        """创建 LLM 策略。

        mode 说明:
          signal (D) — 只发信号，引擎不执行
          paper     — 模拟盘执行
          live (A)  — 全自动执行
        """

        from app.engine.llm_context import DefaultLLMContextProvider
        from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalyzerConfig
        from app.strategies.llm_strategy import LLMStrategy

        llm_config = LLMAnalyzerConfig(
            api_key=state.settings.llm_api_key,
            base_url=state.settings.llm_base_url,
            model=state.settings.llm_model,
            temperature=state.settings.llm_temperature,
            max_tokens=state.settings.llm_max_tokens,
            request_timeout=state.settings.llm_request_timeout,
            min_request_interval_seconds=state.settings.llm_min_request_interval_seconds,
            circuit_failure_threshold=state.settings.llm_circuit_failure_threshold,
            circuit_cooldown_seconds=state.settings.llm_circuit_cooldown_seconds,
            min_candles=state.settings.llm_min_candles,
            max_candles=state.settings.llm_max_candles,
        )
        analyzer = LLMAnalyzer(llm_config, on_decision=_on_llm_decision)

        amount = request.default_order_amount or state.settings.llm_default_order_amount
        strategy_name = request.name or f"llm_{request.symbol.lower()}_{request.interval}"

        # P1-4 Slice 2: pipe live risk metrics + trade history into the LLM
        # prompt. The provider adapts engine state (RiskManager + SQLiteStore)
        # so the strategy stays engine-agnostic.
        context_provider = DefaultLLMContextProvider(
            risk_manager=state.engine.risk_manager,
            store=state.store,
        )

        strategy = LLMStrategy(
            analyzer=analyzer,
            name=strategy_name,
            default_order_amount_usdt=amount,
            min_confidence=request.min_confidence,
            allowed_symbols=state.settings.llm_allowed_symbols or None,
            context_provider=context_provider,
            fallback_strategy=SMAStrategy(name=f"{strategy_name}_rule_fallback"),
        )
        state.engine.add_strategy(
            strategy_name,
            strategy,
            exchange=request.exchange,
            symbol=request.symbol,
            interval=request.interval,
            enabled=request.enabled,
            mode=request.mode,
        )
        return {
            "strategy": next(
                item for item in state.engine.list_strategies() if item["name"] == strategy_name
            )
        }

    @app.post("/api/v1/strategies/llm-filter/attach", dependencies=[Depends(require_api_key)])
    async def attach_llm_filter(
        exchange: str = Query("binance_usdm", min_length=1),
        symbol: str = Query("BTCUSDT", min_length=1),
        default_order_amount: float | None = Query(None, gt=0),
        min_confidence: float = Query(0.5, ge=0.0, le=1.0),
        state: AppState = Depends(get_state),
    ):
        """创建 LLM 信号过滤器并附加到引擎（B 方案）。

        过滤器会拦截所有策略信号，让 LLM 二次确认后才放行。
        """

        from app.engine.llm_filter import LLMSignalFilter
        from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalyzerConfig

        llm_config = LLMAnalyzerConfig(
            api_key=state.settings.llm_api_key,
            base_url=state.settings.llm_base_url,
            model=state.settings.llm_model,
            temperature=state.settings.llm_temperature,
            max_tokens=state.settings.llm_max_tokens,
            request_timeout=state.settings.llm_request_timeout,
            min_request_interval_seconds=state.settings.llm_min_request_interval_seconds,
            circuit_failure_threshold=state.settings.llm_circuit_failure_threshold,
            circuit_cooldown_seconds=state.settings.llm_circuit_cooldown_seconds,
            min_candles=state.settings.llm_min_candles,
            max_candles=state.settings.llm_max_candles,
        )
        analyzer = LLMAnalyzer(llm_config, on_decision=_on_llm_decision)
        amount = default_order_amount or state.settings.llm_default_order_amount

        filter_ = LLMSignalFilter(
            analyzer=analyzer,
            default_order_amount_usdt=amount,
            min_confidence=min_confidence,
        )
        state.engine.add_signal_filter(filter_)

        return {
            "status": "attached",
            "filter": "LLMSignalFilter",
            "default_order_amount_usdt": amount,
            "min_confidence": min_confidence,
        }

    @app.get("/api/v1/strategies/llm-filter/rejected")
    async def llm_filter_rejected(
        limit: int = Query(20, ge=1, le=100),
        state: AppState = Depends(get_state),
    ):
        """查看被 LLM 过滤器拒绝的信号列表。"""
        return {"rejected": state.engine.get_rejected_signals(limit=limit)}

    # ── 阶段 5：实盘同步 + 监控告警 API ─────────────────────────

    @app.get("/api/v1/monitor/status")
    async def monitor_status(state: AppState = Depends(get_state)):
        return state.engine.monitor.summary()

    @app.get("/api/v1/monitor/alerts")
    async def recent_alerts(
        level: str | None = Query(None, max_length=16),
        limit: int = Query(50, ge=1, le=200),
        state: AppState = Depends(get_state),
    ):
        alert_level = None
        if level:
            from app.engine.monitor import AlertLevel

            alert_level = AlertLevel(level.lower())
        return {"alerts": state.engine.monitor.recent_alerts(level=alert_level, limit=limit)}

    @app.get("/api/v1/monitor/last-error")
    async def last_alert_error(state: AppState = Depends(get_state)):
        error = state.engine.monitor.last_error()
        return {"error": error} if error else {"error": None}

    @app.get("/api/v1/sync/status")
    async def sync_status(state: AppState = Depends(get_state)):
        return {
            "order_sync": {
                "running": state.engine._running,
                "tracked_orders": state.engine.order_sync.tracked_count,
                "interval_seconds": state.engine.order_sync.interval_seconds,
            },
            "position_sync": {
                "running": state.engine._running,
                "interval_seconds": state.engine.position_sync.interval_seconds,
            },
        }

    @app.get("/api/v1/sources")
    async def list_sources(state: AppState = Depends(get_state)):
        return {
            "sources": [
                {"name": name, "base_url": src._base_url}
                for name, src in state.custom_sources.items()
            ]
            + [
                {"name": name, "base_url": "builtin"}
                for name in state.data_sources
                if name not in state.custom_sources
            ]
        }

    @app.post("/api/v1/sources", dependencies=[Depends(require_api_key)])
    async def register_source(request: CustomSourceRequest, state: AppState = Depends(get_state)):
        if request.name in state.custom_sources or request.name in state.data_sources:
            raise HTTPException(
                status_code=409, detail=f"Source already registered: {request.name}"
            )
        src = GenericHttpDataSource(
            name=request.name,
            base_url=request.base_url,
            ticker_path=request.ticker_path,
            klines_path=request.klines_path,
            trades_path=request.trades_path,
            klines_array_key=request.klines_array_key,
        )
        state.custom_sources[request.name] = src
        state.data_sources[request.name] = src
        return {"name": request.name, "registered": True}

    @app.delete("/api/v1/sources/{name}", dependencies=[Depends(require_api_key)])
    async def remove_source(name: str, state: AppState = Depends(get_state)):
        if name not in state.custom_sources:
            raise HTTPException(status_code=404, detail=f"Custom source not found: {name}")
        del state.custom_sources[name]
        # Also drop from data_sources (only if it was custom — builtins are kept).
        if name in state.data_sources and isinstance(
            state.data_sources.get(name), GenericHttpDataSource
        ):
            del state.data_sources[name]
        return {"name": name, "removed": True}

    @app.post("/api/v1/positions/close", dependencies=[Depends(require_api_key)])
    async def close_position_endpoint(
        request: ClosePositionRequest,
        state: AppState = Depends(get_state),
    ):
        """Close (or partially close) a position at market.

        This endpoint is a live-trading mutation, so it must pass the same
        live-trading and kill-switch gates as the normal order endpoints.
        ``position_size_pct`` is used when ``exit_quantity`` is omitted.
        """
        exchange_name = request.exchange.lower()
        if not state.settings.enable_live_trading:
            reject_live_disabled(
                action="close_position",
                detail="Live trading is disabled. Enable it before closing positions.",
                exchange=exchange_name,
                symbol=request.symbol,
                details={
                    "position_size_pct": request.position_size_pct,
                    "exit_quantity": request.exit_quantity,
                },
            )
        ensure_trading_not_killed(
            action="close_position",
            exchange=exchange_name,
            symbol=request.symbol,
            details={
                "position_size_pct": request.position_size_pct,
                "exit_quantity": request.exit_quantity,
            },
        )

        client = state.trading_exchanges.get(exchange_name)
        if client is None:
            raise HTTPException(
                status_code=400,
                detail=f"No trading exchange configured: {request.exchange}",
            )
        try:
            pos = await state.engine.position_manager.get_position(exchange_name, request.symbol)
        except Exception:
            pos = None

        position_quantity = abs(pos.quantity) if pos else 0.0
        if position_quantity <= 0:
            raise HTTPException(status_code=400, detail="No position to close")

        side = "sell" if pos.quantity > 0 else "buy"
        qty = (
            request.exit_quantity
            if request.exit_quantity is not None
            else position_quantity * request.position_size_pct
        )
        if qty <= 0:
            raise HTTPException(status_code=400, detail="No position to close")
        if pos is not None and qty > position_quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Close quantity {qty} exceeds position size {position_quantity}",
            )

        result = await call_exchange(
            lambda: client.place_order(
                symbol=request.symbol,
                side=side,
                order_type="market",
                quantity=qty,
                price=None,
            ),
            is_private=True,
        )

        # Audit event.
        try:
            state.engine._record_event(
                category="order",
                event_type="position_closed",
                level="info",
                exchange=exchange_name,
                symbol=request.symbol,
                message=f"Closed {qty} {request.symbol} via market order",
                details={
                    "order_id": str(result.get("order_id", "")),
                    "position_size_pct": request.position_size_pct,
                    "requested_exit_quantity": request.exit_quantity,
                },
            )
        except Exception:
            pass

        return {
            "closed_quantity": qty,
            "order": result,
        }

    @app.get("/api/v1/stream/events")
    async def stream_events(
        request: Request,
        state: AppState = Depends(get_state),
        max_events: int = 600,
        heartbeat_seconds: float = 10.0,
        poll_interval_seconds: float = 1.0,
    ):
        """SSE endpoint: status snapshot + alert/audit stream + heartbeats.

        Replaces 5s polling from the frontend. Each iteration reads
        from two sources:

          - ``state.engine.monitor.recent_alerts(50)`` — live
            in-memory alerts (drawdown, ping failure, kill switch …).
            These never persist to SQLite, so this is the only path
            to push them to the drawer.
          - ``state.store.recent_events(50)`` — historical events
            persisted by CompositeObserver (live orders, risk rejects).

        A per-connection cursor tracks the highest-seen timestamp;
        only events newer than the cursor are shipped, so a fresh
        connection does not replay the entire history.
        """
        import asyncio as _asyncio
        import json as _json

        async def gen():
            # Initial snapshot.
            try:
                risk = await state.engine.risk_manager.get_risk_status()
                snapshot = {
                    "kind": "snapshot",
                    "api_online": True,
                    "kill_switch_enabled": state.trading_guard.kill_switch_enabled,
                    "live_trading": state.settings.enable_live_trading,
                    "engine_running": state.engine._running,
                    "strategies": state.engine.list_strategies(),
                    "risk": risk,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                yield f"data: {_json.dumps(snapshot, ensure_ascii=False)}\n\n"
            except Exception as exc:  # noqa: BLE001
                yield f"data: {_json.dumps({'kind': 'error', 'message': str(exc)})}\n\n"

            cursor = datetime.utcnow().isoformat()
            since_last_heartbeat = 0.0

            def _emit(payload: dict) -> str:
                return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"

            for _ in range(max_events):
                if await request.is_disconnected():
                    return
                try:
                    # Live in-memory alerts from Monitor — these never
                    # land in SQLite (Monitor is a ring buffer), so
                    # SSE must read them directly.
                    for alert in state.engine.monitor.recent_alerts(limit=50):
                        ts = alert.get("timestamp") or ""
                        if ts and ts > cursor:
                            cursor = ts
                            yield _emit(
                                {
                                    "kind": "event",
                                    "category": alert.get("category"),
                                    "title": alert.get("title"),
                                    "message": alert.get("message"),
                                    "level": alert.get("level"),
                                    "timestamp": ts,
                                    "exchange": alert.get("exchange"),
                                    "symbol": alert.get("symbol"),
                                }
                            )
                    # Historical events from CompositeObserver.
                    for ev in state.store.recent_events(limit=50):
                        ts = ev.get("timestamp", "")
                        if ts and ts > cursor:
                            cursor = ts
                            yield _emit(
                                {
                                    "kind": "event",
                                    "category": ev.get("category"),
                                    "event_type": ev.get("event_type"),
                                    "title": ev.get("title"),
                                    "message": ev.get("message"),
                                    "level": ev.get("level"),
                                    "timestamp": ts,
                                    "exchange": ev.get("exchange"),
                                    "symbol": ev.get("symbol"),
                                }
                            )
                    since_last_heartbeat += poll_interval_seconds
                    if since_last_heartbeat >= heartbeat_seconds:
                        yield _emit(
                            {
                                "kind": "heartbeat",
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        )
                        since_last_heartbeat = 0.0
                except Exception as exc:  # noqa: BLE001
                    yield _emit({"kind": "error", "message": str(exc)})

                await _asyncio.sleep(poll_interval_seconds)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/api/v1/executions/pending", dependencies=[Depends(require_api_key)])
    async def list_pending_executions(
        exchange: str | None = None,
        state: AppState = Depends(get_state),
    ) -> dict[str, Any]:
        """List non-terminal execution intents requiring tracking or reconciliation."""

        intents = state.store.pending_execution_intents(exchange)
        return {"intents": intents, "count": len(intents)}

    @app.post("/api/v1/sync/orders/{exchange}", dependencies=[Depends(require_api_key)])
    async def sync_orders_manual(exchange: str, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        changed = await state.engine.order_sync.sync(client)
        intents = state.store.pending_execution_intents(exchange)
        return {
            "exchange": exchange,
            "orders_changed": changed,
            "tracked": state.engine.order_sync.tracked_count,
            "unresolved": sum(intent["status"] in {"submitting", "unknown"} for intent in intents),
        }

    @app.get("/api/v1/reconciliation/status", dependencies=[Depends(require_api_key)])
    async def reconciliation_status(
        exchange: str | None = None, state: AppState = Depends(get_state)
    ) -> dict[str, Any]:
        return {
            "guard": state.engine.account_reconciliation.status(exchange),
            "summary": state.store.reconciliation_summary(exchange),
        }

    @app.get("/api/v1/reconciliation/issues", dependencies=[Depends(require_api_key)])
    async def reconciliation_issues(
        exchange: str | None = None,
        status: str = Query("open", pattern="^(open|resolved)$"),
        state: AppState = Depends(get_state),
    ) -> dict[str, Any]:
        issues = state.store.reconciliation_issues(exchange, status)
        return {"issues": issues, "count": len(issues)}

    @app.post(
        "/api/v1/reconciliation/{exchange}/recover",
        dependencies=[Depends(require_api_key)],
    )
    async def recover_reconciliation(
        exchange: str,
        request: ReconciliationRecoveryRequest,
        state: AppState = Depends(get_state),
    ) -> dict[str, Any]:
        """Adopt a freshly verified exchange state, then explicitly release its block."""

        client = state.get_exchange(exchange)
        await state.engine.position_sync.sync(client, exchange)
        await state.engine.position_sync.sync(client, exchange)
        outcome = state.engine.position_sync.last_outcome(exchange)
        critical = [
            issue
            for issue in (outcome.issues if outcome else [])
            if issue.get("severity") == "critical"
        ]
        if critical:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "account_reconciliation_still_mismatched",
                    "message": "Exchange state is still changing; new exposure remains blocked.",
                    "issues": critical,
                },
            )
        resolved = state.store.resolve_reconciliation_issues(exchange, request.note)
        released = state.engine.account_reconciliation.release(exchange)
        record_event(
            category="risk",
            event_type="account_reconciliation_recovered",
            level="warning",
            exchange=exchange,
            message="Operator acknowledged exchange state and released reconciliation block",
            details={"note": request.note, "resolved_issues": resolved},
        )
        return {
            "exchange": exchange,
            "released": released,
            "resolved_issues": resolved,
            "guard": state.engine.account_reconciliation.status(exchange),
        }

    @app.post("/api/v1/sync/positions/{exchange}", dependencies=[Depends(require_api_key)])
    async def sync_positions_manual(
        exchange: str, symbol: str | None = None, state: AppState = Depends(get_state)
    ) -> dict[str, Any]:
        client = state.get_exchange(exchange)
        changed = await state.engine.position_sync.sync(client, exchange, symbol)
        outcome = state.engine.position_sync.last_outcome(exchange)
        return {
            "exchange": exchange,
            "items_updated": changed,
            "reconciliation": outcome.as_dict() if outcome else None,
            "guard": state.engine.account_reconciliation.status(exchange),
        }

    static_dir = Path(settings.frontend_static_dir)
    if static_dir.exists():
        # Docker 镜像会把 React 构建产物复制到 /app/static。
        # 这里最后挂载静态目录，确保 API 和 docs 路由优先于前端 SPA fallback。
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app
