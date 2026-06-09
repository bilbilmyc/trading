import base64
import hashlib
import hmac
import json

import pytest

from app.exchanges.bitget_usdt_futures import BitgetUSDTFuturesExchange
from app.models.contract import ContractOrderIntent, ContractOrderRequest, MarginMode, PositionSide


class StubBitget(BitgetUSDTFuturesExchange):
    def __init__(self):
        super().__init__(api_key="key", secret_key="secret", passphrase="passphrase")
        self.public_calls = []
        self.signed_posts = []

    async def _public_get(self, path, params):
        self.public_calls.append((path, params))
        if path.endswith("/contracts"):
            return [
                {
                    "symbol": "YGGUSDT",
                    "baseCoin": "YGG",
                    "quoteCoin": "USDT",
                    "makerFeeRate": "0.0002",
                    "takerFeeRate": "0.0006",
                    "minTradeNum": "1",
                    "priceEndStep": "1",
                    "pricePlace": "4",
                    "sizeMultiplier": "1",
                    "symbolType": "perpetual",
                    "symbolStatus": "normal",
                    "maxLever": "75",
                },
                {
                    "symbol": "BTCUSDT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "makerFeeRate": "0.0002",
                    "takerFeeRate": "0.0006",
                    "minTradeNum": "0.0001",
                    "priceEndStep": "1",
                    "pricePlace": "1",
                    "sizeMultiplier": "0.0001",
                    "symbolType": "perpetual",
                    "symbolStatus": "normal",
                    "maxLever": "150",
                }
            ]
        if path.endswith("/ticker"):
            return [
                {
                    "symbol": "BTCUSDT",
                    "lastPr": "62500",
                    "open24h": "62000",
                    "bidPr": "62499.5",
                    "askPr": "62500.5",
                    "high24h": "63000",
                    "low24h": "61000",
                    "baseVolume": "100",
                    "quoteVolume": "6200000",
                    "ts": "1780967985438",
                }
            ]
        raise AssertionError(f"unexpected public path {path}")

    async def _signed_post(self, path, body):
        self.signed_posts.append((path, body))
        if path.endswith("/set-leverage"):
            return {"leverage": body["leverage"]}
        if path.endswith("/place-order"):
            return {"orderId": "123", "clientOid": body.get("clientOid")}
        raise AssertionError(f"unexpected signed post {path}")


@pytest.mark.asyncio
async def test_bitget_public_market_mapping():
    exchange = StubBitget()

    markets = await exchange.get_contract_markets()
    fee = await exchange.get_fee_rate("BTC-USDT")
    ticker = await exchange.get_ticker("BTC-USDT")

    assert markets[0].exchange == "bitget_usdt_futures"
    assert markets[0].symbol == "BTCUSDT"
    assert markets[0].price_tick == 0.1
    assert markets[0].quantity_step == 0.0001
    assert markets[0].min_quantity == 0.0001
    assert fee.maker == 0.0002
    assert fee.taker == 0.0006
    assert ticker["symbol"] == "BTCUSDT"
    assert ticker["last_price"] == 62500
    assert ticker["price_change_24h"] == 500
    assert ticker["price_change_pct_24h"] == pytest.approx(0.8064516129)


def test_bitget_signature_matches_v2_prehash():
    exchange = BitgetUSDTFuturesExchange(api_key="key", secret_key="secret", passphrase="passphrase")
    body = json.dumps({"symbol": "BTCUSDT"}, separators=(",", ":"), ensure_ascii=False)

    signature = exchange._sign("1700000000000", "POST", "/api/v2/mix/order/place-order", body=body)

    prehash = "1700000000000POST/api/v2/mix/order/place-order" + body
    expected = base64.b64encode(hmac.new(b"secret", prehash.encode(), hashlib.sha256).digest()).decode()
    assert signature == expected


@pytest.mark.asyncio
async def test_bitget_place_contract_order_payload_for_hedge_close():
    exchange = StubBitget()

    result = await exchange.place_contract_order(
        ContractOrderRequest(
            exchange="bitget_usdt_futures",
            symbol="BTC-USDT",
            intent=ContractOrderIntent.CLOSE_LONG,
            quantity=0.001,
            order_type="post_only",
            price=62500,
            margin_mode=MarginMode.CROSS,
            position_side=PositionSide.LONG,
            leverage=3,
            client_order_id="client-1",
        )
    )

    assert result["order_id"] == "123"
    leverage_path, leverage_body = exchange.signed_posts[0]
    order_path, order_body = exchange.signed_posts[1]
    assert leverage_path.endswith("/set-leverage")
    assert leverage_body["marginMode"] == "crossed"
    assert leverage_body["holdSide"] == "long"
    assert order_path.endswith("/place-order")
    assert order_body == {
        "symbol": "BTCUSDT",
        "productType": "USDT-FUTURES",
        "marginMode": "crossed",
        "marginCoin": "USDT",
        "size": "0.001",
        "orderType": "limit",
        "side": "buy",
        "tradeSide": "close",
        "clientOid": "client-1",
        "price": "62500.0",
        "force": "post_only",
    }
