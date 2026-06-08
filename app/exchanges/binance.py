"""
Binance 交易所异步实现

使用 httpx 进行异步 HTTP 请求，提高并发性能。
支持 REST API 和 WebSocket 订阅。
"""

import hashlib
import hmac
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
import orjson

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
            self._ws_url = "wss://testnet.binance.vision/ws"
        else:
            self._base_url = "https://api.binance.com"
            self._ws_url = "wss://stream.binance.com:9443/ws"
        
        self._client: Optional[httpx.AsyncClient] = None
        self._ws_connections: Dict[str, websockets.WebSocketClientProtocol] = {}
    
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
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _sign_params(self, params: Dict) -> Dict:
        """为请求参数添加签名"""
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
            if 'quote_order_qty' in kwargs:
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
            'status': 'pending',
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
        return {
            'order_id': str(data.get('orderId')),
            'status': self._normalize_order_status(data.get('status')),
            'filled_quantity': float(data.get('executedQty', 0)),
            'avg_price': float(data.get('avgPrice', 0)),
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
        # TODO: 实现 WebSocket 订阅
        pass
    
    async def unsubscribe_ticker(self, symbol: str):
        """取消订阅行情"""
        if symbol in self._ws_connections:
            await self._ws_connections[symbol].close()
            del self._ws_connections[symbol]
    
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
        
        for ws in self._ws_connections.values():
            await ws.close()
        self._ws_connections.clear()
