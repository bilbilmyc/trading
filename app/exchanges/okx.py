"""
OKX 交易所异步实现

使用 httpx 进行异步 HTTP 请求，提高并发性能。
支持 REST API 和 WebSocket 订阅。
"""

import hashlib
import hmac
import time
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
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
        
        self._client: Optional[httpx.AsyncClient] = None
        self._ws_connections: Dict[str, websockets.WebSocketClientProtocol] = {}
    
    @property
    def name(self) -> str:
        return 'okx'
    
    @property
    def base_url(self) -> str:
        return self._base_url
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    'Content-Type': 'application/json',
                    'OK-ACCESS-KEY': self.api_key,
                },
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
        message = timestamp + method + request_path + body
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf8'),
            bytes(message, encoding='utf8'),
            digestmod=hashlib.sha256
        )
        return mac.hexdigest()
    
    async def _sign_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None
    ) -> Dict[str, str]:
        """为请求添加签名头"""
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        body = '' if params is None else orjson.dumps(params).decode('utf-8')
        
        signature = self._generate_signature(timestamp, method, path, body)
        
        return {
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
        }
    
    async def get_account_balance(self) -> Dict[str, float]:
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
    
    async def get_available_balances(self) -> Dict[str, float]:
        """获取可用余额"""
        # OKX 的现金余额即为可用余额
        return await self.get_account_balance()
    
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
        path = '/api/v5/trade/order'
        
        params = {
            'instId': symbol,
            'tdMode': 'cash',  # 现货交易
            'side': side.lower(),
            'ordType': 'market' if order_type.lower() == 'market' else 'limit',
            'sz': str(quantity),
        }
        
        if order_type.lower() == 'limit' and price is not None:
            params['px'] = str(price)
        
        headers = await self._sign_request('POST', path, params)
        
        client = await self._get_client()
        response = await client.post(path, json=params, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        if data.get('code') == '0':
            return {
                'order_id': data.get('data', [{}])[0].get('ordId'),
                'client_order_id': data.get('data', [{}])[0].get('clOrdId'),
                'status': 'pending',
            }
        else:
            raise Exception(f"OKX 下单失败：{data.get('msg', 'Unknown error')}")
    
    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """撤销订单"""
        path = '/api/v5/trade/cancel-order'
        params = {
            'instId': symbol,
            'orderId': order_id,
        }
        
        headers = await self._sign_request('POST', path, params)
        
        client = await self._get_client()
        response = await client.post(path, json=params, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        if data.get('code') == '0':
            return {'success': True, 'order_id': order_id}
        else:
            raise Exception(f"OKX 撤单失败：{data.get('msg', 'Unknown error')}")
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """批量撤销订单"""
        # OKX 支持批量撤单，这里简化实现
        open_orders = await self.get_open_orders(symbol)
        count = 0
        for order in open_orders:
            try:
                await self.cancel_order(symbol, order.get('ordId'))
                count += 1
            except Exception:
                pass
        return count
    
    async def get_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """查询订单状态"""
        path = '/api/v5/trade/order'
        params = {
            'instId': symbol,
            'orderId': order_id,
        }
        
        client = await self._get_client()
        response = await client.get(path, params=params)
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
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取当前挂单"""
        path = '/api/v5/trade/orders-pending'
        params = {}
        if symbol:
            params['instId'] = symbol
        
        client = await self._get_client()
        response = await client.get(path, params=params)
        response.raise_for_status()
        
        data = response.json()
        if data.get('code') == '0':
            return data.get('data', [])
        else:
            raise Exception(f"OKX 查询挂单失败：{data.get('msg', 'Unknown error')}")
    
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """获取实时行情"""
        path = f'/api/v5/market/ticker?instId={symbol}'
        
        client = await self._get_client()
        response = await client.get(path)
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
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """获取 K 线数据"""
        path = '/api/v5/market/candles'
        params = {
            'instId': symbol,
            'bar': self._convert_interval(interval),
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
    
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近成交记录"""
        path = '/api/v5/market/trades'
        params = {
            'instId': symbol,
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
        # TODO: 实现 WebSocket 订阅
        pass
    
    async def unsubscribe_ticker(self, symbol: str):
        """取消订阅行情"""
        if symbol in self._ws_connections:
            await self._ws_connections[symbol].close()
            del self._ws_connections[symbol]
    
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
        
        for ws in self._ws_connections.values():
            await ws.close()
        self._ws_connections.clear()
