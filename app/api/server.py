"""
FastAPI server for trading operations.
"""

from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.engine.risk_manager import RiskConfig
from app.engine.trader import TradingEngine
from app.exchanges.base import ExchangeBase
from app.exchanges.contract_base import ContractExchangeBase
from app.exchanges.factory import ExchangeFactory
from app.models.contract import ContractOrderRequest, LiquidityType
from app.strategies.sma import SMAStrategy
from app.core.logging import setup_logger
from config import Settings, load_settings


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


class AppState:
    """Runtime objects shared by all API handlers in one worker process."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = TradingEngine(
            risk_config=RiskConfig(**settings.risk.model_dump()),
            max_concurrent_orders=5,
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

    def get_state() -> AppState:
        return state

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"status": "ok", "env": settings.app_env}

    @app.get("/api/v1/exchanges")
    async def list_exchanges() -> Dict[str, Any]:
        return {"exchanges": ExchangeFactory.list_supported_exchanges()}

    @app.get("/api/v1/ticker/{exchange}/{symbol}")
    async def get_ticker(exchange: str, symbol: str, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        return await client.get_ticker(symbol)

    @app.get("/api/v1/klines/{exchange}/{symbol}")
    async def get_klines(
        exchange: str,
        symbol: str,
        interval: str = Query("1m"),
        limit: int = Query(100, ge=1, le=1000),
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        return await client.get_klines(symbol, interval=interval, limit=limit)

    @app.get("/api/v1/balances/{exchange}")
    async def get_balances(exchange: str, state: AppState = Depends(get_state)):
        client = state.get_exchange(exchange)
        return await client.get_account_balance()

    @app.get("/api/v1/orders/{exchange}/open")
    async def get_open_orders(
        exchange: str,
        symbol: Optional[str] = None,
        state: AppState = Depends(get_state),
    ):
        client = state.get_exchange(exchange)
        return await client.get_open_orders(symbol)

    @app.get("/api/v1/contracts/{exchange}/{symbol}/fee-rate")
    async def get_contract_fee_rate(
        exchange: str,
        symbol: str,
        state: AppState = Depends(get_state),
    ):
        client = state.get_contract_exchange(exchange)
        return await client.get_fee_rate(symbol)

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
        return await client.estimate_order_cost(symbol, quantity, price, liquidity)

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
        return await client.place_order(
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            quote_order_qty=request.quote_order_qty,
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
        return await client.place_contract_order(request)

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
        return await client.cancel_order(symbol, order_id)

    @app.get("/api/v1/engine/status")
    async def engine_status(state: AppState = Depends(get_state)):
        return await state.engine.get_status()

    @app.post("/api/v1/engine/strategy/sma")
    async def add_sma_strategy(
        short_window: int = Query(5, ge=1),
        long_window: int = Query(20, ge=2),
        state: AppState = Depends(get_state),
    ):
        strategy = SMAStrategy(short_window=short_window, long_window=long_window)
        state.engine.add_strategy(strategy.name, strategy)
        return {"strategy": strategy.name}

    return app
