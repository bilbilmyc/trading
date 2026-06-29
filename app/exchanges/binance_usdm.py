"""
Binance USD-M U 本位合约适配器。
"""

from datetime import datetime
from typing import Any

from app.exchanges.binance import BinanceExchange
from app.exchanges.contract_base import ContractExchangeBase
from app.models.contract import ContractOrderRequest, FeeRate, MarginMode, PositionSide
from app.models.market import ContractMarket


class BinanceUSDMFuturesExchange(BinanceExchange, ContractExchangeBase):
    """Binance USD-M U 本位永续合约适配器实现。"""

    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        passphrase: str = "",
        use_testnet: bool = True,
    ):
        super().__init__(api_key, secret_key, passphrase, use_testnet)
        if use_testnet:
            self._base_url = "https://testnet.binancefuture.com"
            self._ws_url = "wss://stream.binancefuture.com/ws"
        else:
            self._base_url = "https://fapi.binance.com"
            self._ws_url = "wss://fstream.binance.com/ws"

    @property
    def name(self) -> str:
        return "binance_usdm"

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            "supports_hedge_mode": True,
            "supports_post_only": True,
            "requires_symbol_for_cancel_all": True,
            "supports_public_fee_lookup": False,
            "supports_private_fee_lookup": True,
        }

    def normalize_symbol(self, symbol: str) -> str:
        """标准化为 Binance 合约格式，例如 BTCUSDT。"""

        return symbol.upper().replace("-", "").replace("_", "").replace("PERP", "")

    async def get_contract_markets(self, quote_asset: str = "USDT") -> list[ContractMarket]:
        """从 exchangeInfo 列出 Binance USD-M 可交易合约。"""

        path = "/fapi/v1/exchangeInfo"

        client = await self._get_client()
        response = await client.get(path)
        response.raise_for_status()

        quote = quote_asset.upper()
        markets: list[ContractMarket] = []
        for item in response.json().get("symbols", []):
            if item.get("quoteAsset", "").upper() != quote:
                continue
            if item.get("contractType") != "PERPETUAL":
                continue

            filters = {entry.get("filterType"): entry for entry in item.get("filters", [])}
            price_filter = filters.get("PRICE_FILTER", {})
            lot_filter = filters.get("LOT_SIZE", {})
            markets.append(
                ContractMarket(
                    exchange=self.name,
                    symbol=item.get("symbol", ""),
                    base_asset=item.get("baseAsset", ""),
                    quote_asset=item.get("quoteAsset", ""),
                    status=item.get("status", "unknown"),
                    contract_type="perpetual",
                    price_tick=float(price_filter["tickSize"]) if price_filter.get("tickSize") else None,
                    quantity_step=float(lot_filter["stepSize"]) if lot_filter.get("stepSize") else None,
                    min_quantity=float(lot_filter["minQty"]) if lot_filter.get("minQty") else None,
                    raw={
                        "margin_asset": item.get("marginAsset"),
                        "underlying_type": item.get("underlyingType"),
                    },
                )
            )
        return markets

    async def get_account_balance(self) -> dict[str, float]:
        """获取 USD-M 合约钱包余额。"""

        path = "/fapi/v3/balance"
        params = self._sign_params({})

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        balances = {}
        for item in response.json():
            total = float(item.get("balance", 0))
            if total > 0:
                balances[item.get("asset")] = total
        return balances

    async def get_available_balances(self) -> dict[str, float]:
        """获取 USD-M 合约可用余额。"""

        path = "/fapi/v3/balance"
        params = self._sign_params({})

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        balances = {}
        for item in response.json():
            available = float(item.get("availableBalance", 0))
            if available > 0:
                balances[item.get("asset")] = available
        return balances

    async def get_fee_rate(self, symbol: str) -> FeeRate:
        """获取 Binance USD-M 合约 maker/taker 手续费率。"""

        path = "/fapi/v1/commissionRate"
        params = self._sign_params({"symbol": self.normalize_symbol(symbol)})

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        data = response.json()
        return FeeRate(
            exchange=self.name,
            symbol=self.normalize_symbol(symbol),
            maker=float(data.get("makerCommissionRate", 0)),
            taker=float(data.get("takerCommissionRate", 0)),
            raw=data,
        )

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: MarginMode = MarginMode.CROSS,
        position_side: PositionSide = PositionSide.NET,
    ) -> dict[str, Any]:
        """设置 Binance USD-M 合约杠杆。"""

        path = "/fapi/v1/leverage"
        params = self._sign_params(
            {
                "symbol": self.normalize_symbol(symbol),
                "leverage": leverage,
            }
        )

        client = await self._get_client()
        response = await client.post(path, data=params)
        response.raise_for_status()
        return {"success": True, "raw": response.json()}

    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        """撤销一笔 Binance USD-M 合约订单。"""

        path = "/fapi/v1/order"
        params = self._sign_params(
            {
                "symbol": self.normalize_symbol(symbol),
                "orderId": int(order_id),
            }
        )

        client = await self._get_client()
        response = await client.delete(path, params=params)
        response.raise_for_status()
        return {"success": True, "order_id": order_id, "raw": response.json()}

    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        """批量撤销 Binance USD-M 挂单；Binance 要求必须传 symbol。"""

        if symbol is None:
            raise ValueError("symbol is required when cancelling Binance futures orders")

        path = "/fapi/v1/allOpenOrders"
        params = self._sign_params({"symbol": self.normalize_symbol(symbol)})

        client = await self._get_client()
        response = await client.delete(path, params=params)
        response.raise_for_status()
        return 1

    async def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        """查询一笔 Binance USD-M 合约订单。"""

        path = "/fapi/v1/order"
        params = self._sign_params(
            {
                "symbol": self.normalize_symbol(symbol),
                "orderId": int(order_id),
            }
        )

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        data = response.json()
        return {
            "order_id": str(data.get("orderId")),
            "status": self._normalize_order_status(data.get("status")),
            "filled_quantity": float(data.get("executedQty", 0)),
            "avg_price": float(data.get("avgPrice", 0)),
            "raw": data,
        }

    async def get_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """获取 Binance USD-M 合约持仓。"""

        path = "/fapi/v2/positionRisk"
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = self.normalize_symbol(symbol)
        params = self._sign_params(params)

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        positions = []
        for pos in response.json():
            amt = float(pos.get("positionAmt", 0))
            if amt == 0:
                continue
            positions.append(
                {
                    "symbol": self.normalize_symbol(pos.get("symbol", "")),
                    "quantity": amt,
                    "avg_price": float(pos.get("entryPrice", 0)),
                    "current_price": float(pos.get("markPrice", 0)),
                    "leverage": float(pos.get("leverage", 0)),
                    "unrealized_pnl": float(pos.get("unRealizedProfit", 0)),
                    "margin": float(pos.get("isolatedMargin", 0)),
                    "margin_type": pos.get("marginType", "cross"),
                    "raw": pos,
                }
            )
        return positions

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """获取 Binance USD-M 当前挂单。"""

        path = "/fapi/v1/openOrders"
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = self.normalize_symbol(symbol)
        params = self._sign_params(params)

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """获取 Binance USD-M 24 小时行情。"""

        path = "/fapi/v1/ticker/24hr"
        params = {"symbol": self.normalize_symbol(symbol)}

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        data = response.json()
        return {
            "symbol": symbol,
            "exchange": self.name,
            "last_price": float(data.get("lastPrice", 0)),
            "bid_price": None,
            "ask_price": None,
            "high_24h": float(data.get("highPrice", 0)),
            "low_24h": float(data.get("lowPrice", 0)),
            "volume_24h": float(data.get("volume", 0)),
            "quote_volume_24h": float(data.get("quoteVolume", 0)),
            "price_change_24h": float(data.get("priceChange", 0)),
            "price_change_pct_24h": float(data.get("priceChangePercent", 0)),
            "timestamp": datetime.utcnow(),
        }

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取 Binance USD-M K 线。"""

        path = "/fapi/v1/klines"
        params: dict[str, Any] = {
            "symbol": self.normalize_symbol(symbol),
            "interval": interval,
            "limit": min(limit, 1500),
        }
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time:
            params["endTime"] = int(end_time.timestamp() * 1000)

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        klines = []
        for candle in response.json():
            klines.append(
                {
                    "symbol": symbol,
                    "exchange": self.name,
                    "interval": interval,
                    "open_time": datetime.fromtimestamp(candle[0] / 1000),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                    "quote_volume": float(candle[7]),
                    "trade_count": int(candle[8]),
                }
            )
        return klines

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        """获取 Binance USD-M 最近成交。"""

        path = "/fapi/v1/trades"
        params = {
            "symbol": self.normalize_symbol(symbol),
            "limit": min(limit, 1000),
        }

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        trades = []
        for trade in response.json():
            trades.append(
                {
                    "symbol": symbol,
                    "exchange": self.name,
                    "trade_id": str(trade.get("id")),
                    "price": float(trade.get("price")),
                    "quantity": float(trade.get("qty")),
                    "side": "sell" if trade.get("isBuyerMaker") else "buy",
                    "timestamp": datetime.fromtimestamp(trade.get("time") / 1000),
                }
            )
        return trades

    async def place_contract_order(self, request: ContractOrderRequest) -> dict[str, Any]:
        """把统一合约请求翻译成 Binance USD-M 下单请求。"""

        path = "/fapi/v1/order"
        side, inferred_pos_side, inferred_reduce_only = self.resolve_order_intent(request.intent)
        position_side = request.position_side if request.position_side != PositionSide.NET else inferred_pos_side
        reduce_only = inferred_reduce_only if request.reduce_only is None else request.reduce_only
        order_type = request.order_type.upper()

        params: dict[str, Any] = {
            "symbol": self.normalize_symbol(request.symbol),
            "side": side.upper(),
            "type": "LIMIT" if order_type == "POST_ONLY" else order_type,
            "quantity": request.quantity,
            "newOrderRespType": "RESULT",
        }

        if position_side == PositionSide.NET:
            params["positionSide"] = "BOTH"
            if reduce_only:
                params["reduceOnly"] = "true"
        else:
            params["positionSide"] = position_side.value.upper()

        if request.client_order_id:
            params["newClientOrderId"] = request.client_order_id

        if order_type in {"LIMIT", "POST_ONLY", "IOC", "FOK"}:
            if request.price is None:
                raise ValueError("price is required for Binance limit/post_only/ioc/fok orders")
            params["price"] = request.price
            params["timeInForce"] = "GTX" if order_type == "POST_ONLY" else order_type

        if request.leverage:
            await self.set_leverage(
                request.symbol,
                request.leverage,
                request.margin_mode,
                position_side,
            )

        params = self._sign_params(params)

        client = await self._get_client()
        response = await client.post(path, data=params)
        response.raise_for_status()

        data = response.json()
        return {
            "order_id": str(data.get("orderId")),
            "client_order_id": data.get("clientOrderId"),
            "status": self._normalize_order_status(data.get("status")),
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
        """兼容 ExchangeBase 的现货下单接口；USD-M 合约请使用 place_contract_order。"""

        raise NotImplementedError("Use place_contract_order for Binance USD-M futures trading")
