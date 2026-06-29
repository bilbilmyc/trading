"""
OKX 交易所异步实现

使用 httpx 进行异步 HTTP 请求，提高并发性能。
支持 REST API 和 WebSocket 订阅。
"""

import asyncio
import base64
import contextlib
import hashlib
import hmac
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import orjson

try:
    import httpx
    import websockets
except ImportError as e:
    raise ImportError("请安装依赖：pip install httpx websockets") from e

from app.exchanges.base import ExchangeBase


class OKXExchange(ExchangeBase):
    """OKX 交易所异步实现"""

    def __init__(
        self,
        api_key: str = '',
        secret_key: str = '',
        passphrase: str = '',
        use_testnet: bool = True
    ):
        super().__init__(api_key, secret_key, passphrase, use_testnet)

        if use_testnet:
            self._base_url = "https://www.okx.com"
            self._ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        else:
            self._base_url = "https://www.okx.com"
            self._ws_url = "wss://ws.okx.com:8443/ws/v5/public"

        self._client: httpx.AsyncClient | None = None
        # socket 和监听任务分开保存，取消订阅时才能同时停止重连循环并关闭当前连接。
        self._ws_connections: dict[str, websockets.WebSocketClientProtocol] = {}
        self._ws_tasks: dict[str, asyncio.Task] = {}

    @property
    def name(self) -> str:
        return 'okx'

    @property
    def base_url(self) -> str:
        return self._base_url

    def normalize_symbol(self, symbol: str) -> str:
        """标准化交易对格式为 OKX 现货格式 (BTC-USDT)。"""
        normalized = symbol.upper().replace('_', '-')
        if '-' in normalized:
            return normalized

        # 很多调用方会自然传 BTCUSDT；OKX 现货接口要求 BTC-USDT。
        # 如果没有分隔符，就按常见计价币拆分。
        quote_assets = ('USDT', 'USDC', 'USD', 'BTC', 'ETH')
        for quote in quote_assets:
            if normalized.endswith(quote) and len(normalized) > len(quote):
                return f"{normalized[:-len(quote)]}-{quote}"
        return normalized

    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            headers = {
                'Content-Type': 'application/json',
                'OK-ACCESS-KEY': self.api_key,
            }
            if self.use_testnet:
                # OKX 模拟盘和生产环境使用同一个域名，但私有请求必须带这个请求头。
                headers['x-simulated-trading'] = '1'

            # 每个适配器复用一个 AsyncClient，让连接池保持热状态。
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    def _generate_signature(
        self,
        timestamp: str,
        method: str,
        request_path: str,
        body: str = ''
    ) -> str:
        """生成 OKX 请求签名"""
        # OKX 签名串：timestamp + 大写 method + 带 query 的 path + body。
        # HMAC 结果必须做 base64 编码，不能用十六进制。
        message = timestamp + method + request_path + body
        digest = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            digestmod=hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode('utf-8')

    async def _sign_request(
        self,
        method: str,
        path: str,
        query: dict | None = None,
        body: dict | None = None,
    ) -> dict[str, str]:
        """为请求添加签名头"""
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        request_path = path
        if query:
            # GET 签名必须包含最终请求路径上的完整 query string。
            request_path = f"{path}?{urlencode(query)}"
        body_text = '' if body is None else orjson.dumps(body).decode('utf-8')

        signature = self._generate_signature(timestamp, method.upper(), request_path, body_text)

        headers = {
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
        }
        if self.use_testnet:
            # 私有签名接口在模拟盘模式下必须保留这个头。
            headers['x-simulated-trading'] = '1'
        return headers

    async def get_account_balance(self) -> dict[str, float]:
        """获取账户余额"""
        path = '/api/v5/account/balance'
        headers = await self._sign_request('GET', path)

        client = await self._get_client()
        response = await client.get(path, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get('code') == '0':
            balances = {}
            for detail in data.get('data', [{}])[0].get('details', []):
                currency = detail.get('ccy')
                cash_bal = float(detail.get('cashBal', 0))
                if cash_bal > 0:
                    balances[currency] = cash_bal
            return balances
        else:
            raise Exception(f"OKX API 错误：{data.get('msg', 'Unknown error')}")

    async def get_available_balances(self) -> dict[str, float]:
        """获取可用余额"""
        # OKX 的现金余额即为可用余额
        return await self.get_account_balance()

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """下单交易"""
        path = '/api/v5/trade/order'

        params = {
            'instId': self.normalize_symbol(symbol),
            # 这个适配器目前只负责现货 cash 模式。
            # 杠杆/永续模式应单独实现，不要塞进这条现货路径。
            'tdMode': 'cash',  # 现货交易
            'side': side.lower(),
            'ordType': 'market' if order_type.lower() == 'market' else 'limit',
            'sz': str(quantity),
        }

        if order_type.lower() == 'limit' and price is not None:
            params['px'] = str(price)

        # 签名计算必须和实际发送的 JSON body 保持同一份字节表示。
        body = orjson.dumps(params)
        headers = await self._sign_request('POST', path, body=params)

        client = await self._get_client()
        response = await client.post(path, content=body, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get('code') == '0':
            return {
                'order_id': data.get('data', [{}])[0].get('ordId'),
                'client_order_id': data.get('data', [{}])[0].get('clOrdId'),
                'status': 'pending',
                'raw': data,
            }
        else:
            raise Exception(f"OKX 下单失败：{data.get('msg', 'Unknown error')}")

    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        """撤销订单"""
        path = '/api/v5/trade/cancel-order'
        params = {
            'instId': self.normalize_symbol(symbol),
            # OKX REST 订单操作使用 ordId，不是 orderId。
            'ordId': order_id,
        }

        body = orjson.dumps(params)
        headers = await self._sign_request('POST', path, body=params)

        client = await self._get_client()
        response = await client.post(path, content=body, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get('code') == '0':
            return {'success': True, 'order_id': order_id}
        else:
            raise Exception(f"OKX 撤单失败：{data.get('msg', 'Unknown error')}")

    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        """批量撤销订单"""
        # OKX 支持批量撤单，这里简化实现
        open_orders = await self.get_open_orders(symbol)
        count = 0
        for order in open_orders:
            try:
                await self.cancel_order(order.get('instId', symbol), order.get('ordId'))
                count += 1
            except Exception:
                pass
        return count

    async def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        """查询订单状态"""
        path = '/api/v5/trade/order'
        params = {
            'instId': self.normalize_symbol(symbol),
            # OKX 私有查询接口同样使用 ordId。
            'ordId': order_id,
        }

        headers = await self._sign_request('GET', path, query=params)
        client = await self._get_client()
        response = await client.get(path, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get('code') == '0':
            order_data = data.get('data', [{}])[0]
            return {
                'order_id': order_data.get('ordId'),
                'status': self._normalize_order_status(order_data.get('state')),
                'filled_quantity': float(order_data.get('accFillSz', 0)),
                'avg_price': float(order_data.get('avgPx', 0)),
                'raw': order_data,
            }
        else:
            raise Exception(f"OKX 查询订单失败：{data.get('msg', 'Unknown error')}")

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """获取当前挂单"""
        path = '/api/v5/trade/orders-pending'
        params = {}
        if symbol:
            params['instId'] = self.normalize_symbol(symbol)

        headers = await self._sign_request('GET', path, query=params)
        client = await self._get_client()
        response = await client.get(path, params=params, headers=headers)
        response.raise_for_status()

        data = response.json()
        if data.get('code') == '0':
            return data.get('data', [])
        else:
            raise Exception(f"OKX 查询挂单失败：{data.get('msg', 'Unknown error')}")

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """获取实时行情"""
        path = '/api/v5/market/ticker'
        params = {'instId': self.normalize_symbol(symbol)}

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        data = response.json()
        if data.get('code') == '0':
            ticker_data = data.get('data', [{}])[0]
            return {
                'symbol': symbol,
                'exchange': 'okx',
                'last_price': float(ticker_data.get('last', 0)),
                'bid_price': float(ticker_data.get('bidPx', 0)),
                'ask_price': float(ticker_data.get('askPx', 0)),
                'high_24h': float(ticker_data.get('high24h', 0)),
                'low_24h': float(ticker_data.get('low24h', 0)),
                'volume_24h': float(ticker_data.get('vol24h', 0)),
                'quote_volume_24h': float(ticker_data.get('volCcy24h', 0)),
                'timestamp': datetime.utcnow(),
            }
        else:
            raise Exception(f"OKX 获取行情失败：{data.get('msg', 'Unknown error')}")

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """获取 K 线数据"""
        path = '/api/v5/market/candles'
        params = {
            'instId': self.normalize_symbol(symbol),
            'bar': self._convert_interval(interval),
            # OKX 公开 K 线接口现货单次最多返回 300 条。
            'limit': min(limit, 300),
        }

        if start_time:
            params['before'] = int(start_time.timestamp() * 1000)
        if end_time:
            params['after'] = int(end_time.timestamp() * 1000)

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        data = response.json()
        if data.get('code') == '0':
            klines = []
            for candle in data.get('data', []):
                klines.append({
                    'symbol': symbol,
                    'exchange': 'okx',
                    'interval': interval,
                    'open_time': datetime.fromtimestamp(int(candle[0]) / 1000),
                    'open': float(candle[1]),
                    'high': float(candle[2]),
                    'low': float(candle[3]),
                    'close': float(candle[4]),
                    'volume': float(candle[5]),
                    'quote_volume': float(candle[6]),
                })
            return klines
        else:
            raise Exception(f"OKX 获取 K 线失败：{data.get('msg', 'Unknown error')}")

    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        """获取最近成交记录"""
        path = '/api/v5/market/trades'
        params = {
            'instId': self.normalize_symbol(symbol),
            'limit': min(limit, 500),
        }

        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()

        data = response.json()
        if data.get('code') == '0':
            trades = []
            for trade in data.get('data', []):
                trades.append({
                    'symbol': symbol,
                    'exchange': 'okx',
                    'trade_id': trade.get('tradeId'),
                    'price': float(trade.get('px')),
                    'quantity': float(trade.get('sz')),
                    'side': trade.get('side'),
                    'timestamp': datetime.fromtimestamp(int(trade.get('ts', 0)) / 1000),
                })
            return trades
        else:
            raise Exception(f"OKX 获取成交记录失败：{data.get('msg', 'Unknown error')}")

    async def subscribe_ticker(self, symbol: str, callback: Callable):
        """订阅实时行情"""
        normalized = self.normalize_symbol(symbol)
        # 每个 symbol 只保留一个 ticker 监听任务。
        await self.unsubscribe_ticker(normalized)

        async def _listen():
            subscribe_msg = {
                'op': 'subscribe',
                'args': [{'channel': 'tickers', 'instId': normalized}],
            }
            while True:
                try:
                    async with websockets.connect(self._ws_url, ping_interval=20, ping_timeout=20) as ws:
                        self._ws_connections[normalized] = ws
                        await ws.send(orjson.dumps(subscribe_msg).decode('utf-8'))
                        async for message in ws:
                            data = orjson.loads(message)
                            if data.get('event'):
                                # 订阅确认和心跳事件不包含 ticker 数据。
                                continue
                            for item in data.get('data', []):
                                # 把 OKX 字段名转换成系统统一的 ticker 结构。
                                ticker = {
                                    'symbol': symbol,
                                    'exchange': 'okx',
                                    'last_price': float(item.get('last', 0)),
                                    'bid_price': float(item.get('bidPx', 0)),
                                    'ask_price': float(item.get('askPx', 0)),
                                    'high_24h': float(item.get('high24h', 0)),
                                    'low_24h': float(item.get('low24h', 0)),
                                    'volume_24h': float(item.get('vol24h', 0)),
                                    'quote_volume_24h': float(item.get('volCcy24h', 0)),
                                    'timestamp': datetime.utcnow(),
                                }
                                result = callback(ticker)
                                if asyncio.iscoroutine(result):
                                    await result
                except asyncio.CancelledError:
                    # 取消订阅或关闭连接时，任务取消是预期行为。
                    raise
                except Exception:
                    # 短暂断线时保持订阅循环，自动重连。
                    await asyncio.sleep(3)
                finally:
                    self._ws_connections.pop(normalized, None)

        self._ws_tasks[normalized] = asyncio.create_task(_listen())

    async def unsubscribe_ticker(self, symbol: str):
        """取消订阅行情"""
        normalized = self.normalize_symbol(symbol)
        task = self._ws_tasks.pop(normalized, None)
        if task:
            task.cancel()
            # 等待已取消任务会抛 CancelledError；取消订阅属于正常清理流程，这里吞掉即可。
            with contextlib.suppress(asyncio.CancelledError):
                await task

        if normalized in self._ws_connections:
            await self._ws_connections[normalized].close()
            del self._ws_connections[normalized]

    def _normalize_order_status(self, okx_status: str) -> str:
        """转换 OKX 订单状态到统一格式"""
        status_map = {
            'live': 'pending',
            'partially_filled': 'partially_filled',
            'filled': 'filled',
            'canceled': 'cancelled',
            'mmp_canceled': 'cancelled',
        }
        return status_map.get(okx_status, 'pending')

    def _convert_interval(self, interval: str) -> str:
        """转换 K 线周期到 OKX 格式"""
        interval_map = {
            '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m',
            '30m': '30m', '1H': '1H', '2H': '2H', '4H': '4H',
            '6H': '6H', '12H': '12H', '1D': '1D', '1W': '1W', '1M': '1M',
        }
        return interval_map.get(interval, interval)

    async def close(self):
        """关闭连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

        # 关闭 socket 前先停止监听任务，否则关闭过程中监听任务可能再次重连。
        for task in self._ws_tasks.values():
            task.cancel()
        for task in self._ws_tasks.values():
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._ws_tasks.clear()

        for ws in self._ws_connections.values():
            await ws.close()
        self._ws_connections.clear()
