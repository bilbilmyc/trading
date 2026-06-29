"""
Bitget USDT-M futures adapter.

Implements the current Bitget V2 mix futures endpoints for USDT perpetuals.
Public market data works without credentials; account/order endpoints require
API key, secret, and passphrase.
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

try:
    import httpx
except ImportError as exc:
    raise ImportError("请安装依赖：pip install httpx") from exc

from app.exchanges.contract_base import ContractExchangeBase
from app.models.contract import (
    ContractOrderIntent,
    ContractOrderRequest,
    FeeRate,
    MarginMode,
    PositionSide,
)
from app.models.market import ContractMarket

BASE_ASSET_PRIORITY = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "DOGE",
    "ADA",
    "LINK",
    "AVAX",
    "TON",
]


class BitgetUSDTFuturesExchange(ContractExchangeBase):
    """Bitget USDT-M 永续合约适配器实现。"""

    PRODUCT_TYPE = "USDT-FUTURES"
    MARGIN_COIN = "USDT"

    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        passphrase: str = "",
        use_testnet: bool = True,
    ):
        super().__init__(api_key, secret_key, passphrase, use_testnet)
        # Bitget V2 公开接口和生产私有 REST 共用这个域名。
        # Demo 账户语义和普通账户不同，所以这里保持正常 REST 行为，
        # 是否允许真实下单交给应用层 ENABLE_LIVE_TRADING 控制。
        self._base_url = "https://api.bitget.com"
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "bitget_usdt_futures"

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_hedge_mode": True,
            "supports_post_only": True,
            "requires_symbol_for_cancel_all": False,
            "supports_public_fee_lookup": True,
            "supports_private_fee_lookup": False,
        }

    @property
    def base_url(self) -> str:
        return self._base_url

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Content-Type": "application/json", "locale": "en-US"},
                timeout=30.0,
            )
        return self._client

    def normalize_symbol(self, symbol: str) -> str:
        return symbol.upper().replace("-", "").replace("_", "").replace("PERP", "")

    def _require_credentials(self) -> None:
        if not self.api_key or not self.secret_key or not self.passphrase:
            raise ValueError("Bitget API key, secret key, and passphrase are required for private endpoints")

    def _sign(self, timestamp: str, method: str, path: str, query_string: str = "", body: str = "") -> str:
        prehash = f"{timestamp}{method.upper()}{path}"
        if query_string:
            prehash += f"?{query_string}"
        prehash += body
        digest = hmac.new(self.secret_key.encode(), prehash.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def _auth_headers(self, method: str, path: str, query_string: str = "", body: str = "") -> dict[str, str]:
        self._require_credentials()
        timestamp = str(self.get_timestamp())
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": self._sign(timestamp, method, path, query_string, body),
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }

    async def _public_get(self, path: str, params: dict[str, Any]) -> Any:
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "00000":
            raise ValueError(f"Bitget API error: {payload.get('msg', 'unknown error')}")
        return payload.get("data")

    async def _signed_get(self, path: str, params: dict[str, Any]) -> Any:
        query = urlencode(params)
        headers = self._auth_headers("GET", path, query_string=query)
        client = await self._get_client()
        response = await client.get(path, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "00000":
            raise ValueError(f"Bitget API error: {payload.get('msg', 'unknown error')}")
        return payload.get("data")

    async def _signed_post(self, path: str, body: dict[str, Any]) -> Any:
        body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        headers = self._auth_headers("POST", path, body=body_text)
        client = await self._get_client()
        response = await client.post(path, content=body_text, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "00000":
            raise ValueError(f"Bitget API error: {payload.get('msg', 'unknown error')}")
        return payload.get("data")

    async def get_contract_markets(self, quote_asset: str = "USDT") -> list[ContractMarket]:
        data = await self._public_get(
            "/api/v2/mix/market/contracts",
            {"productType": self.PRODUCT_TYPE},
        )
        quote = quote_asset.upper()
        markets: list[ContractMarket] = []
        for item in data or []:
            if str(item.get("quoteCoin", "")).upper() != quote:
                continue
            markets.append(
                ContractMarket(
                    exchange=self.name,
                    symbol=str(item.get("symbol", "")),
                    base_asset=str(item.get("baseCoin", "")),
                    quote_asset=str(item.get("quoteCoin", "")),
                    status=str(item.get("symbolStatus", "unknown")),
                    contract_type=str(item.get("symbolType", "perpetual")),
                    price_tick=self._price_tick(item),
                    quantity_step=self._safe_float(item.get("sizeMultiplier")),
                    min_quantity=self._safe_float(item.get("minTradeNum")),
                    raw={
                        "maker_fee_rate": item.get("makerFeeRate"),
                        "taker_fee_rate": item.get("takerFeeRate"),
                        "min_trade_usdt": item.get("minTradeUSDT"),
                        "max_leverage": item.get("maxLever"),
                    },
                )
            )
        return sorted(markets, key=self._market_sort_key)

    async def get_fee_rate(self, symbol: str) -> FeeRate:
        data = await self._public_get(
            "/api/v2/mix/market/contracts",
            {"productType": self.PRODUCT_TYPE, "symbol": self.normalize_symbol(symbol)},
        )
        item = (data or [{}])[0]
        return FeeRate(
            exchange=self.name,
            symbol=self.normalize_symbol(symbol),
            maker=float(item.get("makerFeeRate", 0)),
            taker=float(item.get("takerFeeRate", 0)),
            raw=item,
        )

    async def get_account_balance(self) -> dict[str, float]:
        data = await self._signed_get(
            "/api/v2/mix/account/accounts",
            {"productType": self.PRODUCT_TYPE},
        )
        balances: dict[str, float] = {}
        for item in data or []:
            coin = str(item.get("marginCoin", "")).upper()
            equity = self._safe_float(item.get("accountEquity"))
            if coin and equity > 0:
                balances[coin] = equity
        return balances

    async def get_available_balances(self) -> dict[str, float]:
        data = await self._signed_get(
            "/api/v2/mix/account/accounts",
            {"productType": self.PRODUCT_TYPE},
        )
        balances: dict[str, float] = {}
        for item in data or []:
            coin = str(item.get("marginCoin", "")).upper()
            available = self._safe_float(item.get("available"))
            if coin and available > 0:
                balances[coin] = available
        return balances

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        data = await self._public_get(
            "/api/v2/mix/market/ticker",
            {"productType": self.PRODUCT_TYPE, "symbol": self.normalize_symbol(symbol)},
        )
        item = (data or [{}])[0]
        last_price = self._safe_float(item.get("lastPr"))
        open_24h = self._safe_float(item.get("open24h"))
        change = last_price - open_24h if open_24h > 0 else self._safe_float(item.get("change24h"))
        change_pct = (change / open_24h * 100) if open_24h > 0 else self._safe_float(item.get("change24h")) * 100
        return {
            "symbol": self.normalize_symbol(symbol),
            "exchange": self.name,
            "last_price": last_price,
            "bid_price": self._safe_float(item.get("bidPr")),
            "ask_price": self._safe_float(item.get("askPr")),
            "high_24h": self._safe_float(item.get("high24h")),
            "low_24h": self._safe_float(item.get("low24h")),
            "volume_24h": self._safe_float(item.get("baseVolume")),
            "quote_volume_24h": self._safe_float(item.get("quoteVolume") or item.get("usdtVolume")),
            "price_change_24h": change,
            "price_change_pct_24h": change_pct,
            "timestamp": datetime.fromtimestamp(self._safe_float(item.get("ts")) / 1000)
            if self._safe_float(item.get("ts")) > 0
            else datetime.utcnow(),
        }

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "symbol": self.normalize_symbol(symbol),
            "productType": self.PRODUCT_TYPE,
            "granularity": interval,
            "limit": min(limit, 1000),
        }
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time:
            params["endTime"] = int(end_time.timestamp() * 1000)
        data = await self._public_get("/api/v2/mix/market/candles", params)

        klines = []
        for candle in data or []:
            klines.append(
                {
                    "symbol": self.normalize_symbol(symbol),
                    "exchange": self.name,
                    "interval": interval,
                    "open_time": datetime.fromtimestamp(float(candle[0]) / 1000),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                    "quote_volume": float(candle[6]) if len(candle) > 6 else 0.0,
                    "trade_count": 0,
                }
            )
        return klines

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        data = await self._public_get(
            "/api/v2/mix/market/fills",
            {
                "symbol": self.normalize_symbol(symbol),
                "productType": self.PRODUCT_TYPE,
                "limit": min(limit, 1000),
            },
        )
        trades = []
        for trade in data or []:
            ts = self._safe_float(trade.get("ts"))
            trades.append(
                {
                    "symbol": self.normalize_symbol(symbol),
                    "exchange": self.name,
                    "trade_id": str(trade.get("tradeId") or trade.get("id")),
                    "price": self._safe_float(trade.get("price")),
                    "quantity": self._safe_float(trade.get("size") or trade.get("quantity")),
                    "side": str(trade.get("side", "")).lower(),
                    "timestamp": datetime.fromtimestamp(ts / 1000) if ts > 0 else datetime.utcnow(),
                }
            )
        return trades

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"productType": self.PRODUCT_TYPE}
        if symbol:
            params["symbol"] = self.normalize_symbol(symbol)
        data = await self._signed_get("/api/v2/mix/order/orders-pending", params)
        return list((data or {}).get("entrustedList", []))

    async def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        data = await self._signed_get(
            "/api/v2/mix/order/detail",
            {
                "symbol": self.normalize_symbol(symbol),
                "productType": self.PRODUCT_TYPE,
                "orderId": order_id,
            },
        )
        item = data or {}
        return {
            "order_id": str(item.get("orderId", order_id)),
            "status": self._normalize_order_status(str(item.get("status", "live"))),
            "filled_quantity": self._safe_float(item.get("baseVolume")),
            "avg_price": self._safe_float(item.get("priceAvg")),
            "raw": item,
        }

    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        data = await self._signed_post(
            "/api/v2/mix/order/cancel-order",
            {
                "symbol": self.normalize_symbol(symbol),
                "productType": self.PRODUCT_TYPE,
                "orderId": order_id,
                "marginCoin": self.MARGIN_COIN,
            },
        )
        return {"success": True, "order_id": order_id, "raw": data}

    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        body: dict[str, Any] = {"productType": self.PRODUCT_TYPE, "marginCoin": self.MARGIN_COIN}
        if symbol:
            body["symbol"] = self.normalize_symbol(symbol)
        data = await self._signed_post("/api/v2/mix/order/cancel-all-orders", body)
        if isinstance(data, dict) and isinstance(data.get("successList"), list):
            return len(data["successList"])
        return 0

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: MarginMode = MarginMode.CROSS,
        position_side: PositionSide = PositionSide.NET,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "symbol": self.normalize_symbol(symbol),
            "productType": self.PRODUCT_TYPE,
            "marginCoin": self.MARGIN_COIN,
            "leverage": str(leverage),
            "marginMode": self._margin_mode(margin_mode),
        }
        if position_side in {PositionSide.LONG, PositionSide.SHORT}:
            body["holdSide"] = position_side.value
        data = await self._signed_post("/api/v2/mix/account/set-leverage", body)
        return {"success": True, "raw": data}

    async def get_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"productType": self.PRODUCT_TYPE, "marginCoin": self.MARGIN_COIN}
        data = await self._signed_get("/api/v2/mix/position/all-position", params)
        positions = []
        normalized_symbol = self.normalize_symbol(symbol) if symbol else None
        for pos in data or []:
            pos_symbol = self.normalize_symbol(str(pos.get("symbol", "")))
            if normalized_symbol and pos_symbol != normalized_symbol:
                continue
            qty = self._safe_float(pos.get("total") or pos.get("available"))
            hold_side = str(pos.get("holdSide", "")).lower()
            signed_qty = -qty if hold_side == "short" else qty
            if signed_qty == 0:
                continue
            positions.append(
                {
                    "symbol": pos_symbol,
                    "quantity": signed_qty,
                    "avg_price": self._safe_float(pos.get("openPriceAvg") or pos.get("averageOpenPrice")),
                    "current_price": self._safe_float(pos.get("markPrice")),
                    "leverage": self._safe_float(pos.get("leverage")),
                    "unrealized_pnl": self._safe_float(pos.get("unrealizedPL")),
                    "margin": self._safe_float(pos.get("marginSize")),
                    "margin_type": pos.get("marginMode"),
                    "raw": pos,
                }
            )
        return positions

    async def place_contract_order(self, request: ContractOrderRequest) -> dict[str, Any]:
        order_type = request.order_type.lower()
        body: dict[str, Any] = {
            "symbol": self.normalize_symbol(request.symbol),
            "productType": self.PRODUCT_TYPE,
            "marginMode": self._margin_mode(request.margin_mode),
            "marginCoin": self.MARGIN_COIN,
            "size": str(request.quantity),
            "orderType": "market" if order_type == "market" else "limit",
            "side": self._bitget_side(request.intent, request.position_side),
        }

        if request.position_side != PositionSide.NET:
            body["tradeSide"] = "close" if self._is_close_intent(request.intent) else "open"
        elif request.reduce_only is not None:
            body["reduceOnly"] = "YES" if request.reduce_only else "NO"

        if request.client_order_id:
            body["clientOid"] = request.client_order_id

        if order_type != "market":
            if request.price is None:
                raise ValueError("price is required for Bitget limit/post_only/ioc/fok orders")
            body["price"] = str(request.price)
            body["force"] = "post_only" if order_type == "post_only" else order_type if order_type in {"ioc", "fok"} else "gtc"

        if request.leverage:
            await self.set_leverage(request.symbol, request.leverage, request.margin_mode, request.position_side)

        data = await self._signed_post("/api/v2/mix/order/place-order", body)
        return {
            "order_id": str((data or {}).get("orderId", "")),
            "client_order_id": (data or {}).get("clientOid"),
            "status": "pending",
            "exchange": self.name,
            "symbol": self.normalize_symbol(request.symbol),
            "raw": data,
        }

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        raise NotImplementedError("Use place_contract_order for Bitget USDT-M futures trading")

    async def subscribe_ticker(self, symbol: str, callback: Callable):
        raise NotImplementedError("Bitget WebSocket ticker subscription is not implemented yet")

    async def unsubscribe_ticker(self, symbol: str):
        return None

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _price_tick(self, item: dict[str, Any]) -> float | None:
        price_place = int(self._safe_float(item.get("pricePlace")))
        price_end_step = self._safe_float(item.get("priceEndStep"))
        if price_place < 0:
            return None
        return price_end_step * (10 ** -price_place)

    def _market_sort_key(self, market: ContractMarket) -> tuple[int, int, str]:
        status_rank = 0 if market.status.lower() in {"normal", "trading"} else 1
        try:
            asset_rank = BASE_ASSET_PRIORITY.index(market.base_asset.upper())
        except ValueError:
            asset_rank = len(BASE_ASSET_PRIORITY)
        return status_rank, asset_rank, market.symbol

    def _margin_mode(self, margin_mode: MarginMode) -> str:
        return "crossed" if margin_mode == MarginMode.CROSS else "isolated"

    def _is_close_intent(self, intent: ContractOrderIntent) -> bool:
        return intent in {ContractOrderIntent.CLOSE_LONG, ContractOrderIntent.CLOSE_SHORT}

    def _bitget_side(self, intent: ContractOrderIntent, position_side: PositionSide) -> str:
        if position_side == PositionSide.LONG:
            return "buy"
        if position_side == PositionSide.SHORT:
            return "sell"
        side, _, _ = self.resolve_order_intent(intent)
        return side

    def _normalize_order_status(self, status: str) -> str:
        mapping = {
            "live": "pending",
            "partially_filled": "partially_filled",
            "filled": "filled",
            "cancelled": "cancelled",
            "canceled": "cancelled",
        }
        return mapping.get(status.lower(), "pending")

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
