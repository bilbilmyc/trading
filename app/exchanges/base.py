"""
交易所统一接口基类

定义所有交易所必须实现的抽象方法。
使用异步编程提高并发性能。
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class ExchangeBase(ABC):
    """交易所统一接口基类
    
    所有交易所实现必须继承此类并实现所有抽象方法。
    使用异步方法提高 IO 密集型操作的效率。
    """

    def __init__(self, api_key: str = '', secret_key: str = '',
                 passphrase: str = '', use_testnet: bool = True):
        """初始化交易所连接
        
        Args:
            api_key: API 密钥
            secret_key: 密钥
            passphrase: 口令 (OKX 需要)
            use_testnet: 是否使用测试网
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.use_testnet = use_testnet
        self._initialized_at = datetime.utcnow()

    @property
    @abstractmethod
    def name(self) -> str:
        """交易所名称"""
        pass

    @property
    @abstractmethod
    def base_url(self) -> str:
        """API 基础 URL"""
        pass

    @property
    def capabilities(self) -> dict[str, Any]:
        """交易所能力标志。

        每个适配器可以覆盖这个 property，声明自己支持哪些功能。
        API 层和前端可以根据这些标志动态调整 UI 和行为。

        标准键：
        - supports_hedge_mode: 支持多空双向持仓模式
        - supports_post_only: 支持只挂单 (GTX / Post-Only)
        - requires_symbol_for_cancel_all: 批量撤单必须传 symbol
        - supports_public_fee_lookup: 手续费率可通过公开接口查询
        - supports_private_fee_lookup: 手续费率需要已签名的私有接口
        """

        return {
            "supports_hedge_mode": False,
            "supports_post_only": False,
            "requires_symbol_for_cancel_all": False,
            "supports_public_fee_lookup": False,
            "supports_private_fee_lookup": False,
        }

    # ========== 账户相关 ==========

    @abstractmethod
    async def get_account_balance(self) -> dict[str, float]:
        """获取账户余额
        
        Returns:
            币种到余额的映射，如 {'BTC': 1.5, 'USDT': 10000}
        """
        pass

    @abstractmethod
    async def get_available_balances(self) -> dict[str, float]:
        """获取可用余额
        
        Returns:
            币种到可用余额的映射
        """
        pass

    # ========== 订单相关 ==========

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """下单交易
        
        Args:
            symbol: 交易对
            side: 买卖方向 ('buy'/'sell' 或 'BUY'/'SELL')
            order_type: 订单类型 ('market'/'limit')
            quantity: 交易数量
            price: 委托价格 (限价单必需)
            **kwargs: 其他参数
            
        Returns:
            订单结果，包含订单 ID 等信息
        """
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        """撤销订单
        
        Args:
            symbol: 交易对
            order_id: 订单 ID
            
        Returns:
            撤单结果
        """
        pass

    @abstractmethod
    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        """批量撤销订单
        
        Args:
            symbol: 交易对 (可选，不传则撤销所有)
            
        Returns:
            成功撤销的订单数量
        """
        pass

    @abstractmethod
    async def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        """查询订单状态
        
        Args:
            symbol: 交易对
            order_id: 订单 ID
            
        Returns:
            订单详细信息
        """
        pass

    @abstractmethod
    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """获取当前挂单
        
        Args:
            symbol: 交易对 (可选，不传则获取所有)
            
        Returns:
            挂单列表
        """
        pass

    # ========== 行情相关 ==========

    @abstractmethod
    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """获取实时行情
        
        Args:
            symbol: 交易对
            
        Returns:
            行情数据
        """
        pass

    @abstractmethod
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100
    ) -> list[dict[str, Any]]:
        """获取 K 线数据
        
        Args:
            symbol: 交易对
            interval: K 线周期
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回数量限制
            
        Returns:
            K 线数据列表
        """
        pass

    @abstractmethod
    async def get_recent_trades(self, symbol: str, limit: int = 100) -> list[dict[str, Any]]:
        """获取最近成交记录
        
        Args:
            symbol: 交易对
            limit: 返回数量限制
            
        Returns:
            成交记录列表
        """
        pass

    # ========== WebSocket 相关 ==========

    @abstractmethod
    async def subscribe_ticker(self, symbol: str, callback):
        """订阅实时行情
        
        Args:
            symbol: 交易对
            callback: 回调函数
        """
        pass

    @abstractmethod
    async def unsubscribe_ticker(self, symbol: str):
        """取消订阅行情"""
        pass

    # ========== 工具方法 ==========

    def normalize_symbol(self, symbol: str) -> str:
        """标准化交易对格式
        
        子类可根据需要重写此方法
        
        Args:
            symbol: 原始交易对
            
        Returns:
            标准化后的交易对
        """
        return symbol.upper().replace('-', '').replace('_', '')

    def get_timestamp(self) -> int:
        """获取当前时间戳 (毫秒)"""
        return int(datetime.utcnow().timestamp() * 1000)

    async def ping(self) -> bool:
        """检查连接状态"""
        try:
            await self.get_ticker('BTCUSDT')
            return True
        except Exception:
            return False

    async def close(self):
        """关闭连接，释放资源"""
        pass
