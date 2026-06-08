"""
FastAPI server for trading operations.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.engine.risk_manager import RiskConfig
from app.engine.trader import TradingEngine
from app.exchanges.base import ExchangeBase
from app.exchanges.contract_base import ContractExchangeBase
from app.exchanges.factory import ExchangeFactory
from app.models.contract import ContractOrderRequest, LiquidityType, MarginMode, PositionSide
from app.strategies.sma import SMAStrategy
from app.core.logging import setup_logger
from config import Settings, load_settings

T = TypeVar("T")


class OrderRequest(BaseModel):
    """Validated payload for order creation.

    The API accepts a unified shape and lets each exchange adapter translate it
    into its native fields.
    """

    exchange: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., pattern="^(buy|sell|BUY|SELL)$")
    order_type: str = Field("market", pattern="^(market|limit|MARKET|LIMIT)$")
    quantity: float = Field(..., gt=0)
    price: Optional[float] = Field(None, gt=0)
    quote_order_qty: Optional[float] = Field(None, gt=0)


class SMAStrategyRequest(BaseModel):
    """Create one configured SMA strategy instance."""

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
    """Start or run the signal-only strategy runner."""

    poll_seconds: int = Field(60, ge=5, le=3600)
    candle_limit: int = Field(80, ge=20, le=500)


class PaperResetRequest(BaseModel):
    """Reset paper trading account."""

    initial_cash: Optional[float] = Field(None, gt=0)


class StrategyModeRequest(BaseModel):
    """Update strategy execution mode."""

    mode: str = Field(..., pattern="^(signal|paper)$")


class AppState:
    """Runtime objects shared by all API handlers in one worker process."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = TradingEngine(
            risk_config=RiskConfig(**settings.risk.model_dump()),
            max_concurrent_orders=5,
        )
        self.engine.add_strategy(
            "sma_5_20_btcusdt",
            SMAStrategy(short_window=5, long_window=20),
            exchange="binance_usdm",
            symbol="BTCUSDT",
            interval="1m",
            enabled=False,
            mode="signal",
        )
        self.exchanges: Dict[str, ExchangeBase] = {}

    def get_exchange(self, name: str) -> ExchangeBase:
        """Create exchange clients lazily and reuse them for later requests."""

        exchange_name = name.lower()
        if exchange_name in self.exchanges:
            return self.exchanges[exchange_name]

        exchange_settings = self.settings.exchange(exchange_name)
        if exchange_settings is None or not exchange_settings.enabled:
            raise HTTPException(status_code=404, detail=f"Exchange is not enabled: {name}")

        # ExchangeFactory owns adapter construction and keeps one instance per
        # exchange/API-key pair, so handlers do not recreate HTTP clients.
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
        """Return a contract-capable exchange or reject the request clearly."""

        exchange = self.get_exchange(name)
        if not isinstance(exchange, ContractExchangeBase):
            raise HTTPException(status_code=400, detail=f"Exchange is not contract-capable: {name}")
        return exchange

    def ensure_strategy_exchanges(self) -> None:
        """Create exchange clients required by configured strategy instances."""

        for strategy in self.engine.list_strategies():
            exchange_name = strategy.get("exchange")
            if exchange_name:
                self.get_exchange(str(exchange_name))

    async def close(self) -> None:
        """Close HTTP/WebSocket connections when the API worker shuts down."""

        for exchange in self.exchanges.values():
            await exchange.close()
        self.exchanges.clear()


def get_settings() -> Settings:
    return load_settings()


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create the FastAPI app.

    Uvicorn workers import this function independently, so each worker gets its
    own AppState and exchange clients.
    """

    settings = settings or load_settings()
    setup_logger(settings.log_level)
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Store the runtime state on app.state for debugging or future routes.
        app.state.trading = state
        yield
        await state.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    # Frontend development runs on Vite's local port. Keep CORS explicit so a
    # browser dashboard can call the API without opening the service to every
    # origin by default.
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
        return state

    async def call_exchange(operation: Callable[[], Awaitable[T]]) -> T:
        """Convert adapter/network failures into predictable API responses."""

        try:
            return await operation()
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            detail: Any
            try:
                detail = exc.response.json()
            except ValueError:
                detail = exc.response.text or exc.response.reason_phrase
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Exchange returned an error response",
                    "status_code": exc.response.status_code,
                    "exchange_detail": detail,
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Exchange network error: {exc.__class__.__name__}",
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "env": settings.app_env}

    @app.get("/api/v1/config")
    async def get_config() -> Dict[str, Any]:
        configured = {}
        for name in ExchangeFactory.list_supported_exchanges():
            exchange_settings = settings.exchange(name)
            configured[name] = {
                "enabled": bool(exchange_settings and exchange_settings.enabled),
                "use_testnet": bool(exchange_settings and exchange_settings.use_testnet),
                "has_api_key": bool(exchange_settings and exchange_settings.api_key),
            }

        return {
            "app_name": settings.app_name,
            "app_env": settings.app_env,
            "default_exchange": settings.default_exchange,
            "default_symbol": settings.default_symbol,
            "live_trading_enabled": settings.enable_live_trading,
            "frontend_static_dir": settings.frontend_static_dir,
            "exchanges": configured,
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
        return await call_exchange(client.get_account_balance)

    @app.get("/api/v1/balances/{exchange}/available")
    async def get_available_balances(exchange: str, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        return await call_exchange(client.get_available_balances)

    @app.get("/api/v1/order/{exchange}/{symbol}/{order_id}")
    async def get_order(
        exchange: str,
        symbol: str,
        order_id: str,
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        return await call_exchange(lambda: client.get_order(symbol, order_id))

    @app.get("/api/v1/orders/{exchange}/open")
    async def get_open_orders(
        exchange: str,
        symbol: Optional[str] = None,
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        return await call_exchange(lambda: client.get_open_orders(symbol))

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
        return await call_exchange(lambda: client.get_fee_rate(symbol))

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
            raise HTTPException(
                status_code=403,
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to change leverage.",
            )
        client = state.get_contract_exchange(exchange)
        return await call_exchange(lambda: client.set_leverage(symbol, leverage, margin_mode, position_side))

    @app.post("/api/v1/order")
    async def place_order(request: OrderRequest, state: AppState = Depends(get_state)):
        # This guard makes the API safe by default: read-only endpoints work,
        # while real order placement must be enabled explicitly in .env.
        if not state.settings.enable_live_trading:
            raise HTTPException(
                status_code=403,
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to place orders.",
            )

        client = state.get_exchange(request.exchange)
        return await call_exchange(
            lambda: client.place_order(
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                quantity=request.quantity,
                price=request.price,
                quote_order_qty=request.quote_order_qty,
            )
        )

    @app.post("/api/v1/contracts/order")
    async def place_contract_order(
        request: ContractOrderRequest,
        state: AppState = Depends(get_state),
    ):
        # Contract orders can open leveraged exposure. Keep them behind the
        # same explicit live-trading switch as spot orders.
        if not state.settings.enable_live_trading:
            raise HTTPException(
                status_code=403,
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to place contract orders.",
            )

        client = state.get_contract_exchange(request.exchange)
        return await call_exchange(lambda: client.place_contract_order(request))

    @app.delete("/api/v1/order/{exchange}/{symbol}/{order_id}")
    async def cancel_order(
        exchange: str,
        symbol: str,
        order_id: str,
        state: AppState = Depends(get_state),
    ):
        # Keep cancel behind the same live-trading flag because cancelling a
        # real order still changes exchange state.
        if not state.settings.enable_live_trading:
            raise HTTPException(
                status_code=403,
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to cancel orders.",
            )
        client = state.get_exchange(exchange)
        return await call_exchange(lambda: client.cancel_order(symbol, order_id))

    @app.delete("/api/v1/orders/{exchange}/open")
    async def cancel_all_orders(
        exchange: str,
        symbol: Optional[str] = None,
        state: AppState = Depends(get_state),
    ):
        if not state.settings.enable_live_trading:
            raise HTTPException(
                status_code=403,
                detail="Live trading is disabled. Set ENABLE_LIVE_TRADING=true to cancel orders.",
            )
        client = state.get_exchange(exchange)
        cancelled = await call_exchange(lambda: client.cancel_all_orders(symbol))
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
        state.engine.paper_account.reset(initial_cash=request.initial_cash)
        return state.engine.get_paper_summary()

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
                "running": state.engine.order_sync._running,
                "tracked_orders": state.engine.order_sync.tracked_count,
                "interval_seconds": state.engine.order_sync.interval_seconds,
            },
            "position_sync": {
                "running": state.engine.position_sync.is_running,
                "interval_seconds": state.engine.position_sync.interval_seconds,
            },
        }

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
        # The Docker image copies the React build into /app/static. Mount it
        # last so API and docs routes continue to win over the SPA fallback.
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app
