# Web3 量化交易系统

一个基于 Python 的高性能量化交易系统，支持 OKX、Binance 等主流 Web3 交易所。

## 特性

- **模块化设计**: 清晰的包结构，类似 Go 语言的模块组织方式
- **异步高性能**: 全面使用 asyncio 和 httpx，支持高并发交易
- **统一接口**: 所有交易所使用统一的 API 接口
- **FastAPI 支持**: 提供完整的 REST API
- **风险控制**: 内置完善的风险管理模块
- **策略框架**: 易于扩展的策略开发框架

## 项目结构

```
/workspace
├── cmd/                    # 应用程序入口
│   └── api/               # API 服务入口
├── pkg/                    # 公共包 (类似 Go 的 pkg)
│   ├── exchanges/         # 交易所实现
│   │   ├── base.py       # 统一接口基类
│   │   ├── okx.py        # OKX 实现
│   │   ├── binance.py    # Binance 实现
│   │   └── factory.py    # 工厂类
│   ├── strategies/        # 交易策略
│   │   ├── base.py       # 策略基类
│   │   └── sma.py        # SMA 示例策略
│   ├── engine/           # 交易引擎
│   │   ├── trader.py     # 核心交易引擎
│   │   ├── risk_manager.py  # 风险管理
│   │   └── position_manager.py  # 持仓管理
│   ├── models/           # 数据模型
│   │   ├── order.py      # 订单模型
│   │   ├── position.py   # 持仓模型
│   │   ├── balance.py    # 余额模型
│   │   └── market.py     # 市场数据模型
│   └── api/              # FastAPI 路由
├── internal/             # 内部配置和服务
│   └── config/          # 配置管理
├── main.py              # 主入口
└── requirements.txt     # 依赖
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API 密钥
```

### 3. 运行

**API 服务模式:**
```bash
python main.py api
```

访问 http://localhost:8000/docs 查看 API 文档

**策略交易模式:**
```bash
python main.py trade
```

## API 使用示例

### 获取行情
```bash
curl http://localhost:8000/api/v1/ticker/okx/BTC-USDT
```

### 下单交易
```bash
curl -X POST http://localhost:8000/api/v1/order \
  -H "Content-Type: application/json" \
  -d '{
    "exchange": "okx",
    "symbol": "BTC-USDT",
    "side": "buy",
    "order_type": "market",
    "quantity": 0.001
  }'
```

## 自定义策略

继承 `StrategyBase` 类并实现抽象方法：

```python
from pkg.strategies.base import StrategyBase, Signal

class MyStrategy(StrategyBase):
    async def on_market_data(self, symbol: str, data: dict):
        # 处理行情数据
        pass
    
    async def generate_signals(self, symbol: str) -> Optional[Signal]:
        # 生成交易信号
        pass
```

## 性能优化

- 使用 `httpx` 异步 HTTP 客户端
- 使用 `orjson` 进行高速 JSON 序列化
- 使用 `asyncio.Semaphore` 控制并发
- 使用 `deque` 优化历史数据存储

## 注意事项

⚠️ **风险提示**: 本系统仅供学习研究使用，实盘交易请谨慎评估风险。

## License

MIT
