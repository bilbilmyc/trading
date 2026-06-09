"""
OKX 永续合约适配器。

它和 OKX 现货适配器分开，是因为合约交易需要保证金模式、持仓方向、
reduce-only 和杠杆等额外参数。
"""

from typing import Any, Dict, List, Optional

import orjson

from app.exchanges.contract_base import ContractExchangeBase
from app.exchanges.okx import OKXExchange
from app.models.contract import ContractOrderRequest, FeeRate, MarginMode, PositionSide
from app.models.market import ContractMarket


class OKXSwapExchange(OKXExchange, ContractExchangeBase):
    """OKX USDT 保证金永续合约适配器实现。"""

    @property
    def name(self) -> str:
        return "okx_swap"

    def normalize_symbol(self, symbol: str) -> str:
        """标准化为 OKX 永续合约格式，例如 BTC-USDT-SWAP。"""

        normalized = super().normalize_symbol(symbol)
        if normalized.endswith("-SWAP"):
            return normalized
        return f"{normalized}-SWAP"

    def _inst_family(self, symbol: str) -> str:
        """把 BTC-USDT-SWAP 转成 BTC-USDT，用于 OKX 费率查询。"""

        normalized = self.normalize_symbol(symbol)
        return normalized.removesuffix("-SWAP")

    async def get_contract_markets(self, quote_asset: str = "USDT") -> List[ContractMarket]:
        """从公开 instruments 接口列出 OKX 永续合约。"""

        path = "/api/v5/public/instruments"
        params = {"instType": "SWAP"}

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != "0":
            raise Exception(f"OKX instruments query failed: {data.get('msg', 'Unknown error')}")

        quote = quote_asset.upper()
        markets: List[ContractMarket] = []
        for item in data.get("data", []):
            if item.get("settleCcy", "").upper() != quote:
                continue
            symbol = item.get("instId", "")
            parts = symbol.split("-")
            if len(parts) < 3:
                continue
            markets.append(
                ContractMarket(
                    exchange=self.name,
                    symbol=symbol,
                    base_asset=parts[0],
                    quote_asset=parts[1],
                    status=item.get("state", "unknown"),
                    contract_type="perpetual",
                    price_tick=float(item["tickSz"]) if item.get("tickSz") else None,
                    quantity_step=float(item["lotSz"]) if item.get("lotSz") else None,
                    min_quantity=float(item["minSz"]) if item.get("minSz") else None,
                    raw={
                        "alias": item.get("alias"),
                        "contract_value": item.get("ctVal"),
                        "contract_value_currency": item.get("ctValCcy"),
                    },
                )
            )
        return markets

    async def get_fee_rate(self, symbol: str) -> FeeRate:
        """获取 OKX 永续合约 maker/taker 手续费率。"""

        path = "/api/v5/account/trade-fee"
        params = {
            "instType": "SWAP",
            "instFamily": self._inst_family(symbol),
        }
        headers = await self._sign_request("GET", path, query=params)

        client = await self._get_client()
        response = await client.get(path, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != "0":
            raise Exception(f"OKX fee query failed: {data.get('msg', 'Unknown error')}")

        fee_data = data.get("data", [{}])[0]
        return FeeRate(
            exchange=self.name,
            symbol=self.normalize_symbol(symbol),
            maker=abs(float(fee_data.get("maker", 0))),
            taker=abs(float(fee_data.get("taker", 0))),
            raw=fee_data,
        )

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: MarginMode = MarginMode.CROSS,
        position_side: PositionSide = PositionSide.NET,
    ) -> Dict[str, Any]:
        """设置 OKX 永续合约杠杆。"""

        path = "/api/v5/account/set-leverage"
        params = {
            "instId": self.normalize_symbol(symbol),
            "lever": str(leverage),
            "mgnMode": margin_mode.value,
        }
        if position_side != PositionSide.NET:
            params["posSide"] = position_side.value

        body = orjson.dumps(params)
        headers = await self._sign_request("POST", path, body=params)

        client = await self._get_client()
        response = await client.post(path, content=body, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != "0":
            raise Exception(f"OKX set leverage failed: {data.get('msg', 'Unknown error')}")
        return {"success": True, "raw": data}

    async def place_contract_order(self, request: ContractOrderRequest) -> Dict[str, Any]:
        """把统一合约请求翻译成 OKX 永续下单请求。"""

        path = "/api/v5/trade/order"
        side, inferred_pos_side, inferred_reduce_only = self.resolve_order_intent(request.intent)
        position_side = request.position_side if request.position_side != PositionSide.NET else inferred_pos_side
        reduce_only = inferred_reduce_only if request.reduce_only is None else request.reduce_only
        order_type = request.order_type.lower()

        params: Dict[str, Any] = {
            "instId": self.normalize_symbol(request.symbol),
            "tdMode": request.margin_mode.value,
            "side": side,
            "ordType": order_type,
            "sz": str(request.quantity),
        }

        if position_side != PositionSide.NET:
            params["posSide"] = position_side.value
        if reduce_only:
            params["reduceOnly"] = "true"
        if request.client_order_id:
            params["clOrdId"] = request.client_order_id
        if order_type in {"limit", "post_only", "ioc", "fok"}:
            if request.price is None:
                raise ValueError("price is required for OKX limit/post_only/ioc/fok orders")
            params["px"] = str(request.price)

        if request.leverage:
            await self.set_leverage(
                request.symbol,
                request.leverage,
                request.margin_mode,
                position_side,
            )

        body = orjson.dumps(params)
        headers = await self._sign_request("POST", path, body=params)

        client = await self._get_client()
        response = await client.post(path, content=body, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != "0":
            raise Exception(f"OKX swap order failed: {data.get('msg', 'Unknown error')}")

        order_data = data.get("data", [{}])[0]
        return {
            "order_id": order_data.get("ordId"),
            "client_order_id": order_data.get("clOrdId"),
            "status": "pending",
            "exchange": self.name,
            "symbol": self.normalize_symbol(request.symbol),
            "raw": data,
        }

    async def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """从 positions API 获取 OKX 永续持仓。"""

        path = "/api/v5/account/positions"
        params: Dict[str, Any] = {"instType": "SWAP"}
        if symbol:
            params["instId"] = self.normalize_symbol(symbol)
        headers = await self._sign_request("GET", path, query=params)

        client = await self._get_client()
        response = await client.get(path, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != "0":
            raise Exception(f"OKX positions query failed: {data.get('msg', 'Unknown error')}")

        positions = []
        for pos in data.get("data", []):
            quantity = float(pos.get("pos", 0))
            if quantity == 0:
                continue
            pos_side = pos.get("posSide", "net")
            signed_qty = quantity if pos_side == "long" else -quantity
            positions.append(
                {
                    "symbol": pos.get("instId", ""),
                    "quantity": signed_qty,
                    "avg_price": float(pos.get("avgPx", 0)),
                    "current_price": float(pos.get("markPx", 0)),
                    "leverage": float(pos.get("lever", 0)),
                    "unrealized_pnl": float(pos.get("upl", 0)),
                    "margin": float(pos.get("margin", 0)),
                    "margin_type": pos.get("mgnMode", "cross"),
                    "raw": pos,
                }
            )
        return positions

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """兼容 ExchangeBase 的现货下单接口；OKX 永续请使用 place_contract_order。"""

        raise NotImplementedError("Use place_contract_order for OKX swap trading")
