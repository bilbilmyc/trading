"""
Binance 交易所异步实现

使用 httpx 进行异步 HTTP 请求，提高并发性能。
支持 REST API 和 WebSocket 订阅。
"""

import asyncio
import contextlib
import hashlib
import hmac
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
import orjson
from urllib.parse import urlencode

try:
    import httpx
    import websockets
except ImportError as e:
    raise ImportError("请安装依赖：pip install httpx websockets") from e

from app.exchanges.base import ExchangeBase


class BinanceExchange(ExchangeBase):
    """Binance 交易所异步实现"""
    
    def __init__(
        self,
        api_key: str = '',
        secret_key: str = '',
        passphrase: str = '',  # Binance 不需要，但保持接口一致
        use_testnet: bool = True
    ):
        super().__init__(api_key, secret_key, passphrase, use_testnet)
        
        if use_testnet:
            self._base_url = "https://testnet.binance.vision"
            self._ws_url = "wss://stream.testnet.binance.vision/ws"
        else:
            self._base_url = "https://api.binance.com"
            self._ws_url = "wss://stream.binance.com:9443/ws"
        
        self._client: Optional[httpx.AsyncClient] = None
        # WebSocket 连接对象和监听任务分开保存：
        # 连接对象用于关闭 socket，任务对象用于取消重连循环。
        self._ws_connections: Dict[str, websockets.WebSocketClientProtocol] = {}
        self._ws_tasks: Dict[str, asyncio.Task] = {}
    
    @property
    def name(self) -> str:
        return 'binance'
    
    @property
    def base_url(self) -> str:
        return self._base_url
    
    def normalize_symbol(self, symbol: str) -> str:
        """标准化交易对格式为 Binance 格式 (BTCUSDT)"""
        return symbol.upper().replace('-', '').replace('_', '')
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            # 每个交易所适配器复用一个 AsyncClient，保持连接池有效，避免每个请求都重连。
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    'Content-Type': 'application/json',
                    'X-MBX-APIKEY': self.api_key,
                },
                timeout=30.0,
            )
        return self._client
    
    def _generate_signature(self, params: Dict) -> str:
        """生成 Binance 请求签名"""
        # Binance 签名基于精确 URL 编码后的 query string。
        # 不要手写字符串拼接，编码细节会影响签名。
        query_string = urlencode(params)
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _sign_params(self, params: Dict) -> Dict:
        """为请求参数添加签名"""
        # Binance 私有 REST 接口要求参数里包含 timestamp 和 HMAC-SHA256 签名。
        params['timestamp'] = self.get_timestamp()
        signature = self._generate_signature(params)
        params['signature'] = signature
        return params
    
    async def get_account_balance(self) -> Dict[str, float]:
        """获取账户余额"""
        path = '/api/v3/account'
        params = self._sign_params({})
        
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        
        data = response.json()
        balances = {}
        for balance in data.get('balances', []):
            free = float(balance.get('free', 0))
            locked = float(balance.get('locked', 0))
            total = free + locked
            if total > 0:
                balances[balance.get('asset')] = total
        return balances
    
    async def get_available_balances(self) -> Dict[str, float]:
        """获取可用余额"""
        path = '/api/v3/account'
        params = self._sign_params({})
        
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        
        data = response.json()
        balances = {}
        for balance in data.get('balances', []):
            free = float(balance.get('free', 0))
            if free > 0:
                balances[balance.get('asset')] = free
        return balances
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """下单交易"""
        path = '/api/v3/order'
        params = {
            'symbol': self.normalize_symbol(symbol),
            'side': side.upper(),
            'type': order_type.upper(),
            'newOrderRespType': 'FULL',
        }
        
        if order_type.lower() == 'market':
            # Binance 市价买入既可以按基础币数量 quantity，也可以按计价币金额 quoteOrderQty。
            # 两条路径都保留，调用方可以选择“买 0.01 BTC”或“买 100 USDT 的 BTC”。
            if kwargs.get('quote_order_qty') is not None:
                params['quoteOrderQty'] = kwargs['quote_order_qty']
            else:
                params['quantity'] = quantity
        else:  # LIMIT
            params['quantity'] = quantity
            params['price'] = price
            params['timeInForce'] = 'GTC'
        
        params = self._sign_params(params)
        
        client = await self._get_client()
        response = await client.post(path, data=params)
        response.raise_for_status()
        
        data = response.json()
        return {
            'order_id': str(data.get('orderId')),
            'client_order_id': data.get('clientOrderId'),
            'status': self._normalize_order_status(data.get('status')),
            'raw': data,
        }
    
    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """撤销订单"""
        path = '/api/v3/order'
        params = {
            'symbol': self.normalize_symbol(symbol),
            'orderId': int(order_id),
        }
        params = self._sign_params(params)
        
        client = await self._get_client()
        response = await client.delete(path, params=params)
        response.raise_for_status()
        
        data = response.json()
        return {'success': True, 'order_id': order_id}
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """批量撤销订单"""
        if not symbol:
            # Binance 不支持撤销所有订单，需要逐个撤销
            open_orders = await self.get_open_orders()
            count = 0
            for order in open_orders:
                try:
                    await self.cancel_order(order['symbol'], str(order['orderId']))
                    count += 1
                except Exception:
                    pass
            return count
        else:
            # 撤销指定交易对的所有订单
            path = '/api/v3/openOrders'
            params = self._sign_params({'symbol': self.normalize_symbol(symbol)})
            
            client = await self._get_client()
            response = await client.delete(path, params=params)
            response.raise_for_status()
            
            return len(response.json())
    
    async def get_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """查询订单状态"""
        path = '/api/v3/order'
        params = {
            'symbol': self.normalize_symbol(symbol),
            'orderId': int(order_id),
        }
        params = self._sign_params(params)
        
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        
        data = response.json()
        # Binance 现货订单查询不直接返回 avgPrice。
        # 平均成交价用累计成交额 / 已成交基础币数量计算。
        executed_qty = float(data.get('executedQty', 0))
        quote_qty = float(data.get('cummulativeQuoteQty', 0))
        avg_price = quote_qty / executed_qty if executed_qty > 0 else 0.0
        return {
            'order_id': str(data.get('orderId')),
            'status': self._normalize_order_status(data.get('status')),
            'filled_quantity': executed_qty,
            'avg_price': avg_price,
            'raw': data,
        }
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取当前挂单"""
        path = '/api/v3/openOrders'
        params = {}
        if symbol:
            params['symbol'] = self.normalize_symbol(symbol)
        params = self._sign_params(params)
        
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        
        return response.json()
    
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """获取实时行情"""
        path = '/api/v3/ticker/24hr'
        params = {'symbol': self.normalize_symbol(symbol)}
        
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        
        data = response.json()
        return {
            'symbol': symbol,
            'exchange': 'binance',
            'last_price': float(data.get('lastPrice', 0)),
            'bid_price': None,  # Binance ticker 不包含买卖价
            'ask_price': None,
            'high_24h': float(data.get('highPrice', 0)),
            'low_24h': float(data.get('lowPrice', 0)),
            'volume_24h': float(data.get('volume', 0)),
            'quote_volume_24h': float(data.get('quoteVolume', 0)),
            'price_change_24h': float(data.get('priceChange', 0)),
            'price_change_pct_24h': float(data.get('priceChangePercent', 0)),
            'timestamp': datetime.utcnow(),
        }
    
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取 K 线数据"""
        path = '/api/v3/klines'
        params = {
            'symbol': self.normalize_symbol(symbol),
            'interval': interval,
            'limit': min(limit, 1000),
        }
        
        if start_time:
            params['startTime'] = int(start_time.timestamp() * 1000)
        if end_time:
            params['endTime'] = int(end_time.timestamp() * 1000)
        
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        
        klines = []
        for candle in response.json():
            klines.append({
                'symbol': symbol,
                'exchange': 'binance',
                'interval': interval,
                'open_time': datetime.fromtimestamp(candle[0] / 1000),
                'open': float(candle[1]),
                'high': float(candle[2]),
                'low': float(candle[3]),
                'close': float(candle[4]),
                'volume': float(candle[5]),
                'quote_volume': float(candle[7]),
                'trade_count': int(candle[8]),
            })
        return klines
    
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近成交记录"""
        path = '/api/v3/trades'
        params = {
            'symbol': self.normalize_symbol(symbol),
            'limit': min(limit, 1000),
        }
        
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        
        trades = []
        for trade in response.json():
            trades.append({
                'symbol': symbol,
                'exchange': 'binance',
                'trade_id': str(trade.get('id')),
                'price': float(trade.get('price')),
                'quantity': float(trade.get('qty')),
                'side': 'sell' if trade.get('isBuyerMaker') else 'buy',
                'timestamp': datetime.fromtimestamp(trade.get('time') / 1000),
            })
        return trades
    
    async def subscribe_ticker(self, symbol: str, callback: Callable):
        """订阅实时行情"""
        normalized = self.normalize_symbol(symbol)
        key = normalized.lower()
        # 每个 symbol 只保留一个 ticker 监听任务。
        await self.unsubscribe_ticker(normalized)

        async def _listen():
            url = f"{self._ws_url}/{key}@ticker"
            while True:
                try:
                    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                        self._ws_connections[normalized] = ws
                        async for message in ws:
                            data = orjson.loads(message)
                            # Binance ticker stream 使用短字段名，这里转换成引擎/API 统一结构。
                            ticker = {
                                'symbol': symbol,
                                'exchange': 'binance',
                                'last_price': float(data.get('c', 0)),
                                'bid_price': float(data.get('b', 0)),
                                'ask_price': float(data.get('a', 0)),
                                'high_24h': float(data.get('h', 0)),
                                'low_24h': float(data.get('l', 0)),
                                'volume_24h': float(data.get('v', 0)),
                                'quote_volume_24h': float(data.get('q', 0)),
                                'price_change_24h': float(data.get('p', 0)),
                                'price_change_pct_24h': float(data.get('P', 0)),
                                'timestamp': datetime.utcnow(),
                            }
                            result = callback(ticker)
                            if asyncio.iscoroutine(result):
                                await result
                except asyncio.CancelledError:
                    # 取消订阅或关闭连接时，任务取消是预期行为；继续抛出让任务立即结束。
                    raise
                except Exception:
                    # 短暂网络错误不应杀死订阅；短暂 sleep 防止重连死循环。
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
            # 等待已取消任务会抛 CancelledError；取消订阅是正常清理流程，这里吞掉即可。
            with contextlib.suppress(asyncio.CancelledError):
                await task

        if normalized in self._ws_connections:
            await self._ws_connections[normalized].close()
            del self._ws_connections[normalized]
    
    def _normalize_order_status(self, binance_status: str) -> str:
        """转换 Binance 订单状态到统一格式"""
        status_map = {
            'NEW': 'pending',
            'PARTIALLY_FILLED': 'partially_filled',
            'FILLED': 'filled',
            'CANCELED': 'cancelled',
            'REJECTED': 'rejected',
            'EXPIRED': 'expired',
        }
        return status_map.get(binance_status, 'pending')
    
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
