"""
交易所工厂类

用于创建和管理不同交易所的实例。
"""

from typing import Dict, Optional, Type
from app.exchanges.base import ExchangeBase


class ExchangeFactory:
    """交易所工厂类
    
    单例模式，集中管理所有交易所实例的创建和获取。
    """
    
    _instances: Dict[str, ExchangeBase] = {}
    _exchange_classes: Dict[str, Type[ExchangeBase]] = {}
    
    @classmethod
    def register_exchange(cls, name: str, exchange_class: Type[ExchangeBase]):
        """注册交易所实现类
        
        Args:
            name: 交易所名称 (如 'okx', 'binance')
            exchange_class: 交易所实现类
        """
        cls._exchange_classes[name.lower()] = exchange_class
    
    @classmethod
    def create_exchange(
        cls,
        exchange_name: str,
        api_key: str = '',
        secret_key: str = '',
        passphrase: str = '',
        use_testnet: bool = True,
        **kwargs
    ) -> ExchangeBase:
        """创建交易所实例
        
        Args:
            exchange_name: 交易所名称
            api_key: API 密钥
            secret_key: 密钥
            passphrase: 口令 (OKX 需要)
            use_testnet: 是否使用测试网
            **kwargs: 其他参数
            
        Returns:
            交易所实例
            
        Raises:
            ValueError: 不支持的交易所
        """
        name = exchange_name.lower()
        
        if name not in cls._exchange_classes:
            raise ValueError(f"不支持的交易所：{name}。支持的交易所：{list(cls._exchange_classes.keys())}")
        
        exchange_class = cls._exchange_classes[name]
        
        instance = exchange_class(
            api_key=api_key,
            secret_key=secret_key,
            passphrase=passphrase,
            use_testnet=use_testnet,
            **kwargs
        )
        
        return instance
    
    @classmethod
    def get_or_create(
        cls,
        exchange_name: str,
        api_key: str = '',
        secret_key: str = '',
        passphrase: str = '',
        use_testnet: bool = True,
        **kwargs
    ) -> ExchangeBase:
        """获取或创建交易所实例 (单例模式)
        
        Args:
            exchange_name: 交易所名称
            api_key: API 密钥
            secret_key: 密钥
            passphrase: 口令
            use_testnet: 是否使用测试网
            **kwargs: 其他参数
            
        Returns:
            交易所实例
        """
        name = exchange_name.lower()
        key = f"{name}_{api_key[:8]}"  # 使用 API 密钥前缀作为缓存键
        
        if key not in cls._instances:
            cls._instances[key] = cls.create_exchange(
                exchange_name=name,
                api_key=api_key,
                secret_key=secret_key,
                passphrase=passphrase,
                use_testnet=use_testnet,
                **kwargs
            )
        
        return cls._instances[key]
    
    @classmethod
    def get_instance(cls, exchange_name: str) -> Optional[ExchangeBase]:
        """获取已存在的交易所实例
        
        Args:
            exchange_name: 交易所名称
            
        Returns:
            交易所实例，不存在则返回 None
        """
        name = exchange_name.lower()
        for key, instance in cls._instances.items():
            if key.startswith(f"{name}_"):
                return instance
        return None
    
    @classmethod
    def remove_instance(cls, exchange_name: str, api_key_prefix: str = ''):
        """移除交易所实例
        
        Args:
            exchange_name: 交易所名称
            api_key_prefix: API 密钥前缀 (可选)
        """
        name = exchange_name.lower()
        keys_to_remove = []
        
        for key in cls._instances:
            if key.startswith(f"{name}_"):
                if not api_key_prefix or key.startswith(f"{name}_{api_key_prefix}"):
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del cls._instances[key]
    
    @classmethod
    def close_all(cls):
        """关闭所有交易所连接"""
        for instance in cls._instances.values():
            try:
                import asyncio
                asyncio.get_event_loop().run_until_complete(instance.close())
            except Exception:
                pass
        cls._instances.clear()
    
    @classmethod
    def list_supported_exchanges(cls) -> list:
        """列出所有支持的交易所"""
        return list(cls._exchange_classes.keys())


# 自动注册交易所实现
def _auto_register_exchanges():
    """自动注册所有可用的交易所实现"""
    try:
        from app.exchanges.okx import OKXExchange
        ExchangeFactory.register_exchange('okx', OKXExchange)
    except ImportError:
        pass
    
    try:
        from app.exchanges.binance import BinanceExchange
        ExchangeFactory.register_exchange('binance', BinanceExchange)
    except ImportError:
        pass


_auto_register_exchanges()
