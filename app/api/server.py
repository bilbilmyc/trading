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

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import secrets
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core.sqlite_store import SQLiteStore
from app.engine.risk_manager import RiskConfig
from app.engine.trader import TradingEngine
from app.engine.live_trading_guard import LiveTradingGuard
from app.exchanges.base import ExchangeBase
from app.exchanges.contract_base import ContractExchangeBase
from app.exchanges.factory import ExchangeFactory
from app.data_sources.generic_http import GenericHttpDataSource
from app.models.contract import ContractOrderRequest, LiquidityType, MarginMode, PositionSide
from app.strategies.sma import SMAStrategy
from app.core.logging import setup_logger
from config import Settings, load_settings

T = TypeVar("T")


class OrderRequest(BaseModel):
    """现货下单请求体。

    FastAPI 会根据这个 Pydantic 模型校验前端传入的 JSON。
    校验通过后，路由函数里拿到的 request 就是一个 OrderRequest 对象。
    """

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., pattern="^(buy|sell|BUY|SELL)$")
    order_type: str = Field("market", pattern="^(market|limit|MARKET|LIMIT)$")
    quantity: float = Field(..., gt=0)
    price: Optional[float] = Field(None, gt=0)
    quote_order_qty: Optional[float] = Field(None, gt=0)


class SMAStrategyRequest(BaseModel):
    """创建 SMA 策略时前端传入的请求体。"""

    name: Optional[str] = Field(None, min_length=1, max_length=64)
    exchange: str = Field("binance_usdm", min_length=1)
    symbol: str = Field("BTCUSDT", min_length=1)
    interval: str = Field("1m", min_length=1, max_length=16)
    short_window: int = Field(5, ge=1)
    long_window: int = Field(20, ge=2)
    min_data_points: Optional[int] = Field(None, ge=2)
    enabled: bool = False
    mode: str = Field("signal", pattern="^(signal|paper)$")


class SignalRunnerRequest(BaseModel):
    """启动或手动运行信号运行器的请求体。"""

    poll_seconds: int = Field(60, ge=5, le=3600)
    candle_limit: int = Field(80, ge=20, le=500)


class PaperResetRequest(BaseModel):
    """重置模拟盘账户的请求体。"""

    initial_cash: Optional[float] = Field(None, gt=0)


class StrategyModeRequest(BaseModel):
    """切换策略运行模式的请求体。"""

    mode: str = Field(..., pattern="^(signal|paper)$")


class KillSwitchRequest(BaseModel):
    """全局 Kill Switch 切换请求体。

    enabled=true 表示立即熔断全部真实交易；enabled=false 表示恢复交易权限。
    reason 会写入 SQLite 审计事件，方便复盘是谁因为什么原因切换了风控状态。
    """

    enabled: bool
    reason: str = Field("manual", min_length=1, max_length=200)


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
        self.trading_guard = LiveTradingGuard(live_trading_enabled=settings.enable_live_trading)
        self.engine = TradingEngine(
            risk_config=RiskConfig(**settings.risk.model_dump()),
            trading_guard=self.trading_guard,
            max_concurrent_orders=5,
            store=self.store,
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
        # Two-layer exchange registry (ADR-0003):
        # - data_sources: public market data only, no auth required.
        # - trading_exchanges: private + order operations, require keys + flag.
        # ExchangeBase already implements the DataSource surface, so existing
        # adapters serve both roles once registered.
        self.exchanges: Dict[str, ExchangeBase] = {}
        self.data_sources: Dict[str, ExchangeBase] = {}
        self.trading_exchanges: Dict[str, ExchangeBase] = {}
        # User-registered custom data sources (any HTTP API via GenericHttpDataSource).
        self.custom_sources: Dict[str, Any] = {}
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
        self.store.close()


def get_settings() -> Settings:
    return load_settings()


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """创建 FastAPI 应用实例。

    这是整个 HTTP 服务的装配点：配置日志、创建 AppState、注册中间件、
    定义路由，然后把 app 返回给 uvicorn。
    """

    settings = settings or load_settings()
    setup_logger(settings.log_level)
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # lifespan 是 FastAPI 的启动/关闭钩子。
        # 启动时把 state 挂到 app.state，便于调试；关闭时统一释放资源。
        app.state.trading = state
        yield
        await state.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    # 前端开发时 Vite 跑在 5173，浏览器会跨端口调用 8000 的 API。
    # CORS 只放开本地前端地址，不把 API 暴露给任意网站。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
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
            raise HTTPException(status_code=400, detail={
                "message": str(exc),
                "error_category": category,
            }) from exc
        except httpx.HTTPStatusError as exc:
            detail: Any
            try:
                detail = exc.response.json()
            except ValueError:
                detail = exc.response.text or exc.response.reason_phrase
            body: Dict[str, Any] = {
                "message": "Exchange returned an error response",
                "error_category": category,
                "status_code": exc.response.status_code,
                "exchange_detail": detail,
            }
            if is_private and exc.response.status_code in (401, 403):
                body["hint"] = "请检查 .env 中对应交易所的 API Key / Secret 是否正确配置，以及账户权限是否足够。"
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
            raise HTTPException(status_code=502, detail={
                "message": str(exc),
                "error_category": category,
            }) from exc

    def extract_order_id(result: Any) -> Optional[str]:
        """尽量从不同交易所返回里取订单号。

        Binance、OKX、Bitget 的字段名不完全一样，所以这里做一层兼容。
        后续引入正式 OMS 后，订单号抽取应该下沉到各交易所适配器。
        """

        if not isinstance(result, dict):
            return None
        for key in ("order_id", "orderId", "ordId", "clientOid", "clOrdId"):
            value = result.get(key)
            if value:
                return str(value)
        raw = result.get("raw")
        if isinstance(raw, dict):
            return extract_order_id(raw)
        return None

    def generate_client_order_id() -> str:
        """生成交易所可接受的客户端订单号。

        这个 ID 会写入交易所订单请求，也会进入 SQLite 审计事件。
        前端先调用 preview 拿到这个 ID，再用同一个 ID 提交订单，方便排查和重试。
        """

        return f"qt{datetime.utcnow():%y%m%d%H%M%S}{secrets.token_hex(5)}"

    def ensure_contract_client_order_id(request: ContractOrderRequest) -> ContractOrderRequest:
        """保证合约订单一定带 client_order_id。"""

        if request.client_order_id:
            return request
        return request.model_copy(update={"client_order_id": generate_client_order_id()})

    def infer_liquidity(order_type: str) -> LiquidityType:
        """按订单类型推断预估手续费用 maker 还是 taker 费率。"""

        normalized = order_type.lower()
        if normalized in {"market", "ioc", "fok"}:
            return LiquidityType.TAKER
        return LiquidityType.MAKER

    async def build_contract_order_preview(request: ContractOrderRequest) -> Dict[str, Any]:
        """构建合约下单预览，不产生任何交易所状态变更。"""

        preview_request = ensure_contract_client_order_id(request)
        client = state.get_contract_exchange(preview_request.exchange)
        side, inferred_position_side, inferred_reduce_only = client.resolve_order_intent(preview_request.intent)
        position_side = (
            preview_request.position_side
            if preview_request.position_side != PositionSide.NET
            else inferred_position_side
        )
        reduce_only = inferred_reduce_only if preview_request.reduce_only is None else preview_request.reduce_only
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
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        strategy: Optional[str] = None,
        order_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
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

    def reject_live_disabled(
        *,
        action: str,
        detail: str,
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        order_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
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
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        order_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
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
        exchange: Optional[str] = None,
        symbol: Optional[str] = None,
        order_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
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

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "env": settings.app_env}

    @app.get("/api/v1/health/venues")
    async def venue_health(state: AppState = Depends(get_state)) -> Dict[str, Any]:
        """检查每个已启用交易所的健康状态。

        对每个 venue 执行：
        - 公开 API 可达性 (ping ticker)
        - 私有 API 可达性 (如果配置了 API Key，尝试余额查询)
        - 时钟偏差 (本地 vs 交易所服务器时间)
        - 凭证存在性
        - 频率限制状态 (取决于交易所是否返回 rate-limit 头)
        """

        venues: Dict[str, Any] = {}
        for name in ExchangeFactory.list_supported_exchanges():
            exchange_settings = settings.exchange(name)
            if exchange_settings is None or not exchange_settings.enabled:
                continue

            has_keys = bool(exchange_settings.api_key)
            result: Dict[str, Any] = {
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
    async def get_config() -> Dict[str, Any]:
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

    @app.get("/api/v1/exchanges")
    async def list_exchanges() -> Dict[str, Any]:
        supported = ExchangeFactory.list_supported_exchanges()
        enabled = [
            name
            for name in supported
            if (exchange_settings := settings.exchange(name)) is not None and exchange_settings.enabled
        ]
        return {"exchanges": supported, "enabled": enabled}

    @app.get("/api/v1/risk/kill-switch")
    async def get_kill_switch_status(state: AppState = Depends(get_state)) -> Dict[str, Any]:
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

    @app.post("/api/v1/risk/kill-switch")
    async def set_kill_switch(
        request: KillSwitchRequest,
        state: AppState = Depends(get_state),
    ) -> Dict[str, Any]:
        """切换全局 Kill Switch。

        enabled=true 会调用 RiskManager.disable_trading()；策略实盘执行和手动下单都会被同一状态拦截。
        """

        if request.enabled:
            state.engine.risk_manager.disable_trading()
            event_type = "kill_switch_enabled"
            level = "critical"
            message = "Global kill switch enabled"
        else:
            state.engine.risk_manager.enable_trading()
            event_type = "kill_switch_disabled"
            level = "info"
            message = "Global kill switch disabled"

        record_event(
            category="risk",
            event_type=event_type,
            level=level,
            message=message,
            details={"reason": request.reason, "enabled": request.enabled},
        )
        risk = await state.engine.risk_manager.get_risk_status()
        trading_enabled = bool(risk["trading_enabled"])
        return {
            "enabled": not trading_enabled,
            "trading_enabled": trading_enabled,
            "risk": risk,
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
        return await call_exchange(lambda: client.get_klines(symbol, interval=interval, limit=limit))

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
        symbol: Optional[str] = None,
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
        return await call_exchange(lambda: client.estimate_order_cost(symbol, quantity, price, liquidity))

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

    @app.post("/api/v1/contracts/{exchange}/{symbol}/leverage")
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
        result = await call_exchange(lambda: client.set_leverage(symbol, leverage, margin_mode, position_side), is_private=True)
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

    @app.post("/api/v1/order")
    async def place_order(request: OrderRequest, state: AppState = Depends(get_state)):
        # 默认只允许读操作；真实下单必须在 .env 里显式开启 ENABLE_LIVE_TRADING。
        if not state.settings.enable_live_trading:
            reject_live_disabled(
                action="place_order",
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to place orders.",
                exchange=request.exchange,
                symbol=request.symbol,
                details=request.model_dump(),
            )
        ensure_trading_not_killed(
            action="place_order",
            exchange=request.exchange,
            symbol=request.symbol,
            details=request.model_dump(),
        )

        client = state.get_exchange(request.exchange)
        result = await call_exchange(
            lambda: client.place_order(
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                price=request.price,
                quote_order_qty=request.quote_order_qty,
            ),
            is_private=True,
        )
        record_event(
            category="order",
            event_type="spot_order_submitted",
            exchange=request.exchange,
            symbol=request.symbol,
            order_id=extract_order_id(result),
            message=f"Spot order submitted: {request.side.upper()} {request.quantity} {request.symbol}",
            details={"request": request.model_dump(), "response": result},
        )
        return result

    @app.post("/api/v1/contracts/order")
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

        client = state.get_contract_exchange(request.exchange)
        result = await call_exchange(lambda: client.place_contract_order(request), is_private=True)
        record_event(
            category="order",
            event_type="contract_order_submitted",
            exchange=request.exchange,
            symbol=request.symbol,
            order_id=extract_order_id(result),
            message=f"Contract order submitted: {request.intent.value} {request.quantity} {request.symbol}",
            details={"request": request.model_dump(mode="json"), "response": result},
        )
        return result

    @app.delete("/api/v1/order/{exchange}/{symbol}/{order_id}")
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

    @app.delete("/api/v1/orders/{exchange}/open")
    async def cancel_all_orders(
        exchange: str,
        symbol: Optional[str] = None,
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
        return await state.engine.get_status()

    @app.get("/api/v1/runner/status")
    async def signal_runner_status(state: AppState = Depends(get_state)):
        return state.engine.get_signal_runner_status()

    @app.post("/api/v1/runner/start")
    async def start_signal_runner(
        request: SignalRunnerRequest,
        state: AppState = Depends(get_state),
    ):
        state.ensure_strategy_exchanges()
        return await state.engine.start_signal_runner(
            poll_seconds=request.poll_seconds,
            candle_limit=request.candle_limit,
        )

    @app.post("/api/v1/runner/stop")
    async def stop_signal_runner(state: AppState = Depends(get_state)):
        return await state.engine.stop_signal_runner()

    @app.post("/api/v1/runner/run-once")
    async def run_signal_cycle(
        request: SignalRunnerRequest,
        state: AppState = Depends(get_state),
    ):
        state.ensure_strategy_exchanges()
        return await state.engine.run_signal_cycle(candle_limit=request.candle_limit)

    @app.get("/api/v1/paper")
    async def paper_summary(state: AppState = Depends(get_state)):
        return state.engine.get_paper_summary()

    @app.post("/api/v1/paper/reset")
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

    @app.post("/api/v1/strategies/sma")
    async def create_sma_strategy(
        request: SMAStrategyRequest,
        state: AppState = Depends(get_state),
    ):
        if request.short_window >= request.long_window:
            raise HTTPException(status_code=400, detail="short_window must be smaller than long_window")

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
        return {"strategy": next(item for item in state.engine.list_strategies() if item["name"] == strategy_name)}

    @app.post("/api/v1/strategies/{name}/start")
    async def start_strategy(name: str, state: AppState = Depends(get_state)):
        try:
            state.engine.set_strategy_enabled(name, True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}") from exc
        return {"strategy": next(item for item in state.engine.list_strategies() if item["name"] == name)}

    @app.post("/api/v1/strategies/{name}/stop")
    async def stop_strategy(name: str, state: AppState = Depends(get_state)):
        try:
            state.engine.set_strategy_enabled(name, False)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Strategy not found: {name}") from exc
        return {"strategy": next(item for item in state.engine.list_strategies() if item["name"] == name)}

    @app.post("/api/v1/strategies/{name}/mode")
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
        return {"strategy": next(item for item in state.engine.list_strategies() if item["name"] == name)}

    @app.delete("/api/v1/strategies/{name}")
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
        category: Optional[str] = Query(None, min_length=1, max_length=32),
        event_type: Optional[str] = Query(None, min_length=1, max_length=64),
        limit: int = Query(30, ge=1, le=200),
        state: AppState = Depends(get_state),
    ):
        return {
            "events": state.store.recent_events(
                category=category,
                event_type=event_type,
                limit=limit,
            )
        }

    @app.post("/api/v1/signals/evaluate")
    async def evaluate_strategy_signals(
        exchange: str = Query(..., min_length=1),
        symbol: str = Query(..., min_length=1),
        interval: str = Query("1m", min_length=1),
        limit: int = Query(80, ge=20, le=500),
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        klines = await call_exchange(lambda: client.get_klines(symbol, interval=interval, limit=limit))
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

    @app.post("/api/v1/engine/strategy/sma")
    async def add_sma_strategy(
        short_window: int = Query(5, ge=1),
        long_window: int = Query(20, ge=2),
        state: AppState = Depends(get_state),
    ):
        strategy = SMAStrategy(short_window=short_window, long_window=long_window)
        state.engine.add_strategy(strategy.name, strategy)
        return {"strategy": strategy.name}

    # ── AI 大模型分析 API ──────────────────────────────────────

    class AIAnalyzeRequest(BaseModel):
        """AI 市场分析请求体。"""

        exchange: str = Field("binance_usdm", min_length=1)
        symbol: str = Field("BTCUSDT", min_length=1)
        interval: str = Field("1h", min_length=1, max_length=8)
        limit: int = Field(30, ge=10, le=100)

    class SizingRequest(BaseModel):
        account_equity: float = Field(..., gt=0)
        entry_price: float = Field(..., gt=0)
        stop_loss_price: float = Field(..., gt=0)
        take_profit_price: Optional[float] = Field(None, gt=0)
        leverage: float = Field(1.0, gt=0)
        risk_pct: float = Field(0.02, gt=0, lt=1)
        contract_size: float = Field(1.0, gt=0)
        min_quantity: float = Field(0.001, gt=0)

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
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "quantity": r.quantity,
            "notional": r.notional,
            "margin": r.margin,
            "risk_amount": r.risk_amount,
            "risk_pct": r.risk_pct,
            "risk_reward_ratio": r.risk_reward_ratio,
        }

    class BacktestRequest(BaseModel):
        klines: List[Dict[str, Any]] = Field(..., min_length=1)
        short_window: int = Field(5, gt=0)
        long_window: int = Field(20, gt=0)
        initial_capital: float = Field(10_000.0, gt=0)
        position_size_pct: float = Field(1.0, gt=0, le=1.0)


    class SuggestRequest(BaseModel):
        klines: List[Dict[str, Any]] = Field(..., min_length=1)
        prefer: Optional[str] = None


    class ClosePositionRequest(BaseModel):
        symbol: str
        exchange: str
        exit_quantity: Optional[float] = None
        position_size_pct: float = Field(1.0, gt=0, le=1.0)


    @app.post("/api/v1/backtest")
    async def backtest_endpoint(request: BacktestRequest):
        """Run SMA crossover backtest on supplied klines (no exchange call)."""
        from app.engine.backtest import run_sma_backtest

        if request.short_window >= request.long_window:
            raise HTTPException(
                status_code=400,
                detail="short_window must be smaller than long_window",
            )
        try:
            r = run_sma_backtest(
                candles=request.klines,
                short_window=request.short_window,
                long_window=request.long_window,
                initial_capital=request.initial_capital,
                position_size_pct=request.position_size_pct,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid kline data: {exc}")

        def _serialize_kline(k: dict) -> dict:
            out = {}
            for key, val in k.items():
                if isinstance(val, datetime):
                    out[key] = val.isoformat()
                else:
                    out[key] = val
            return out

        return {
            "initial_capital": r.initial_capital,
            "final_equity": r.final_equity,
            "total_pnl": r.total_pnl,
            "trades": r.trades,
            "win_rate": r.win_rate,
            "max_drawdown": r.max_drawdown,
            "equity_curve": r.equity_curve,
            "klines_used": [_serialize_kline(k) for k in request.klines],
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
        from app.engine.leaderboard import build_leaderboard

        # Use a fresh tracker from in-memory equity (no real persistence).
        # In production, this would aggregate from store-recorded outcomes.
        return {"strategies": [], "note": "live leaderboard requires trade history"}


    @app.get("/api/v1/portfolio/metrics")
    async def portfolio_metrics(state: AppState = Depends(get_state)):
        """Compute Sharpe / Sortino / max DD from running equity curve."""
        # Without persistent trade history, return empty metrics.
        from app.engine.portfolio_metrics import compute_metrics
        return compute_metrics([]).__dict__


    @app.post("/api/v1/atr-sizing")
    async def atr_sizing_endpoint(request: AIAnalyzeRequest):
        """ATR-based volatility-adjusted position sizing."""
        from app.engine.atr_sizing import atr_position_size, compute_atr
        from datetime import datetime as _dt

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
                entry_price=request.entry_price if hasattr(request, "entry_price") else closes[-1] if closes else 100.0,
                atr=atr,
                risk_pct=0.02,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return r.__dict__


    @app.get("/api/v1/prices")
    async def prices_snapshot(state: AppState = Depends(get_state)):
        """Latest price feed snapshot — sourced from registered exchanges."""
        from app.engine.realtime_feed import PriceFeed

        # Singleton: attached to app.state for shared access.
        feed: PriceFeed = getattr(app.state, "price_feed", None) or PriceFeed()
        return feed.latest_dict()


    @app.post("/api/v1/ai/analyze")
    async def ai_analyze(
        request: AIAnalyzeRequest,
        state: AppState = Depends(get_state),
    ):
        """调用大模型分析市场并返回开单建议（不自动下单）。"""

        from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalyzerConfig

        llm_config = LLMAnalyzerConfig(
            api_key=state.settings.llm_api_key,
            base_url=state.settings.llm_base_url,
            model=state.settings.llm_model,
            temperature=state.settings.llm_temperature,
            max_tokens=state.settings.llm_max_tokens,
            request_timeout=state.settings.llm_request_timeout,
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

        analyzer = LLMAnalyzer(llm_config)
        try:
            result = await analyzer.analyze(
                exchange=client,
                symbol=request.symbol,
                interval=request.interval,
                limit=request.limit,
                position_context=position_ctx,
            )
            return result.to_dict()
        finally:
            await analyzer.close()

    # ── LLM 策略（D / B / A）管理 API ─────────────────────────

    class LLMStrategyCreateRequest(BaseModel):
        """创建 LLM 策略实例的请求体。"""

        name: Optional[str] = Field(None, min_length=1, max_length=64)
        exchange: str = Field("binance_usdm", min_length=1)
        symbol: str = Field("BTCUSDT", min_length=1)
        interval: str = Field("1h", min_length=1, max_length=16)
        default_order_amount: Optional[float] = Field(None, gt=0)
        min_confidence: float = Field(0.5, ge=0.0, le=1.0)
        enabled: bool = False
        mode: str = Field("signal", pattern="^(signal|paper|live)$")

    @app.post("/api/v1/strategies/llm")
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

        from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalyzerConfig
        from app.strategies.llm_strategy import LLMStrategy

        llm_config = LLMAnalyzerConfig(
            api_key=state.settings.llm_api_key,
            base_url=state.settings.llm_base_url,
            model=state.settings.llm_model,
            temperature=state.settings.llm_temperature,
            max_tokens=state.settings.llm_max_tokens,
            request_timeout=state.settings.llm_request_timeout,
            min_candles=state.settings.llm_min_candles,
            max_candles=state.settings.llm_max_candles,
        )
        analyzer = LLMAnalyzer(llm_config)

        amount = request.default_order_amount or state.settings.llm_default_order_amount
        strategy_name = request.name or f"llm_{request.symbol.lower()}_{request.interval}"

        strategy = LLMStrategy(
            analyzer=analyzer,
            name=strategy_name,
            default_order_amount_usdt=amount,
            min_confidence=request.min_confidence,
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
        return {"strategy": next(
            item for item in state.engine.list_strategies() if item["name"] == strategy_name
        )}

    @app.post("/api/v1/strategies/llm-filter/attach")
    async def attach_llm_filter(
        exchange: str = Query("binance_usdm", min_length=1),
        symbol: str = Query("BTCUSDT", min_length=1),
        default_order_amount: Optional[float] = Query(None, gt=0),
        min_confidence: float = Query(0.5, ge=0.0, le=1.0),
        state: AppState = Depends(get_state),
    ):
        """创建 LLM 信号过滤器并附加到引擎（B 方案）。

        过滤器会拦截所有策略信号，让 LLM 二次确认后才放行。
        """

        from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalyzerConfig
        from app.engine.llm_filter import LLMSignalFilter

        llm_config = LLMAnalyzerConfig(
            api_key=state.settings.llm_api_key,
            base_url=state.settings.llm_base_url,
            model=state.settings.llm_model,
            temperature=state.settings.llm_temperature,
            max_tokens=state.settings.llm_max_tokens,
            request_timeout=state.settings.llm_request_timeout,
            min_candles=state.settings.llm_min_candles,
            max_candles=state.settings.llm_max_candles,
        )
        analyzer = LLMAnalyzer(llm_config)
        amount = default_order_amount or state.settings.llm_default_order_amount

        filter_ = LLMSignalFilter(
            analyzer=analyzer,
            default_order_amount_usdt=amount,
            min_confidence=min_confidence,
        )
        state.engine.add_signal_filter(filter_.check)

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
        level: Optional[str] = Query(None, max_length=16),
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

    class CustomSourceRequest(BaseModel):
        name: str = Field(..., min_length=1, max_length=64)
        base_url: str = Field(..., min_length=1)
        ticker_path: str = "/ticker/{symbol}"
        klines_path: str = "/klines"
        trades_path: str = "/trades"
        klines_array_key: Optional[str] = None

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

    @app.post("/api/v1/sources")
    async def register_source(request: CustomSourceRequest, state: AppState = Depends(get_state)):
        if request.name in state.custom_sources or request.name in state.data_sources:
            raise HTTPException(status_code=409, detail=f"Source already registered: {request.name}")
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

    @app.delete("/api/v1/sources/{name}")
    async def remove_source(name: str, state: AppState = Depends(get_state)):
        if name not in state.custom_sources:
            raise HTTPException(status_code=404, detail=f"Custom source not found: {name}")
        del state.custom_sources[name]
        # Also drop from data_sources (only if it was custom — builtins are kept).
        if name in state.data_sources and isinstance(state.data_sources.get(name), GenericHttpDataSource):
            del state.data_sources[name]
        return {"name": name, "removed": True}

    @app.post("/api/v1/positions/close")
    async def close_position_endpoint(
        request: ClosePositionRequest,
        state: AppState = Depends(get_state),
    ):
        """Close (or partially close) a position at market.

        Sends a closing order to the configured trading exchange.
        For a partial close, `exit_quantity` controls how much to close.
        """
        client = state.trading_exchanges.get(request.exchange.lower())
        if client is None:
            raise HTTPException(
                status_code=400,
                detail=f"No trading exchange configured: {request.exchange}",
            )
        try:
            pos = await state.engine.position_manager.get_position(
                request.exchange, request.symbol
            )
        except Exception:
            pos = None

        side = "sell" if (pos and pos.quantity > 0) else "buy"
        order_type = "market"
        qty = request.exit_quantity if request.exit_quantity is not None else (
            abs(pos.quantity) if pos else 0.0
        )
        if qty <= 0:
            raise HTTPException(status_code=400, detail="No position to close")

        try:
            result = await client.place_order(
                symbol=request.symbol,
                side=side,
                order_type=order_type,
                quantity=qty,
                price=None,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Exchange error: {exc}")

        # Audit event.
        try:
            state.engine._record_event(
                category="order",
                event_type="position_closed",
                level="info",
                exchange=request.exchange,
                symbol=request.symbol,
                message=f"Closed {qty} {request.symbol} via market order",
                details={"order_id": str(result.get("order_id", ""))},
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
        max_events: int = 360,
        heartbeat_seconds: float = 10.0,
    ):
        """SSE endpoint: status snapshot + heartbeats.

        Replaces 5s polling from the frontend. First event is a snapshot;
        subsequent events are heartbeats. When audit-event push is wired
        in, audit events will arrive between heartbeats.
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

            # Heartbeat loop — exit cleanly when client disconnects.
            for _ in range(max_events):
                if await request.is_disconnected():
                    return
                await _asyncio.sleep(heartbeat_seconds)
                yield f"data: {_json.dumps({'kind': 'heartbeat', 'timestamp': datetime.utcnow().isoformat()})}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable nginx buffering
                "Connection": "keep-alive",
            },
        )

    @app.post("/api/v1/sync/orders/{exchange}")
    async def sync_orders_manual(exchange: str, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        changed = await state.engine.order_sync.sync(client)
        return {"exchange": exchange, "orders_changed": changed, "tracked": state.engine.order_sync.tracked_count}

    @app.post("/api/v1/sync/positions/{exchange}")
    async def sync_positions_manual(exchange: str, symbol: Optional[str] = None, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        changed = await state.engine.position_sync.sync(client, exchange, symbol)
        return {"exchange": exchange, "items_updated": changed}

    static_dir = Path(settings.frontend_static_dir)
    if static_dir.exists():
        # Docker 镜像会把 React 构建产物复制到 /app/static。
        # 这里最后挂载静态目录，确保 API 和 docs 路由优先于前端 SPA fallback。
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app
