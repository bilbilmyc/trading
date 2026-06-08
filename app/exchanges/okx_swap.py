"""
OKX perpetual swap adapter.

This adapter is separated from the spot OKX adapter because contract trading
requires margin mode, position side, reduce-only handling, and leverage.
"""

from typing import Any, Dict, Optional

import orjson

from app.exchanges.contract_base import ContractExchangeBase
from app.exchanges.okx import OKXExchange
from app.models.contract import ContractOrderRequest, FeeRate, MarginMode, PositionSide


class OKXSwapExchange(OKXExchange, ContractExchangeBase):
    """OKX USDT-margined swap implementation."""

    @property
    def name(self) -> str:
        return "okx_swap"

    def normalize_symbol(self, symbol: str) -> str:
        """Normalize to OKX swap instrument format, e.g. BTC-USDT-SWAP."""

        normalized = super().normalize_symbol(symbol)
        if normalized.endswith("-SWAP"):
            return normalized
        return f"{normalized}-SWAP"

    def _inst_family(self, symbol: str) -> str:
        """Convert BTC-USDT-SWAP to BTC-USDT for OKX fee queries."""

        normalized = self.normalize_symbol(symbol)
        return normalized.removesuffix("-SWAP")

    async def get_fee_rate(self, symbol: str) -> FeeRate:
        """Get OKX swap maker/taker fee rates."""

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
        """Set leverage for an OKX swap instrument."""

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
        """Place an OKX swap order from the unified request."""

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

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Compatibility wrapper for the base exchange interface."""

        raise NotImplementedError("Use place_contract_order for OKX swap trading")
