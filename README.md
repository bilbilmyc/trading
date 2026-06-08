# Web3 量化交易系统

一个基于 Python/asyncio 的 Web3 交易系统骨架，当前支持 OKX、Binance 的统一 REST 接口，并提供 FastAPI 服务入口、SMA 示例策略、风险控制和持仓管理模块。

> 风险提示：默认关闭真实下单。只有显式设置 `ENABLE_LIVE_TRADING=true` 后，API 才允许下单和撤单。

## 功能

- 统一交易所接口：OKX、Binance 使用同一套抽象方法
- 异步实现：REST 请求、交易引擎、策略处理均使用 async/await
- REST API：查询行情、K 线、余额、挂单、下单、撤单、引擎状态
- Uvicorn 并发：支持 async IO 和多 worker 进程
- 合约底座：OKX 永续和 Binance USD-M Futures 独立适配器
- WebSocket 行情：ticker 订阅、取消订阅、断线重连
- 风控模块：订单金额、频率、每日亏损、回撤限制
- 策略框架：内置 SMA 双均线示例策略
- 配置管理：支持 `.env` 和环境变量

## 项目结构

```text
.
├── .python-version
├── .env.example
├── pyproject.toml
├── uv.lock
├── main.py
├── config/
│   ├── __init__.py
│   └── settings.py
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   └── server.py
│   ├── core/
│   ├── engine/
│   ├── exchanges/
│   ├── models/
│   └── strategies/
├── frontend/
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
└── requirements.txt
```

## 环境准备

本项目推荐只用 `uv` 管理 Python 和虚拟环境。当前项目默认 Python 版本写在 `.python-version`：

```text
3.13
```

检查 `uv`：

```bash
uv --version
```

如果终端找不到 `uv`，确认 `~/.local/bin` 在 `PATH` 中：

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

建议把这行放进 `~/.zshrc`：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## 安装 Python

用 `uv` 安装常用 Python 版本：

```bash
uv python install 3.12 3.13 3.14
```

查看已安装和可下载版本：

```bash
uv python list
```

只看已安装版本：

```bash
uv python list --only-installed
```

`/usr/bin/python3` 是 macOS/Command Line Tools 自带 Python，可能会显示为 3.9.x，不建议删除。项目环境请用 `uv venv --managed-python`，这样会优先使用 uv 管理的 Python。

## 创建项目环境

进入项目目录：

```bash
cd trading
```

按 `.python-version` 创建虚拟环境：

```bash
uv venv --managed-python
```

如果想指定版本：

```bash
uv venv --python 3.13 --managed-python
```

激活环境：

```bash
source .venv/bin/activate
```

安装依赖：

```bash
uv sync
```

`uv sync` 会读取 `pyproject.toml` 和 `uv.lock`，创建/更新 `.venv` 并安装锁定版本。

如果只想兼容旧的 requirements 流程，也可以：

```bash
uv pip install -r requirements.txt
```

检查项目 Python：

```bash
python --version
python -c "import sys; print(sys.executable); print(sys.base_prefix)"
```

预期应看到 Python 3.13.x，并且解释器来自 `.venv` 或 uv 管理目录。

## 配置

复制环境变量模板：

```bash
cp .env.example .env
```

常用配置：

```bash
DEFAULT_EXCHANGE=okx
DEFAULT_SYMBOL=BTC-USDT
ENABLE_LIVE_TRADING=false

OKX_ENABLED=true
OKX_SWAP_ENABLED=true
OKX_USE_TESTNET=true
OKX_API_KEY=
OKX_SECRET_KEY=
OKX_PASSPHRASE=

BINANCE_ENABLED=true
BINANCE_USDM_ENABLED=true
BINANCE_USE_TESTNET=true
BINANCE_API_KEY=
BINANCE_SECRET_KEY=

MAX_POSITION_VALUE=1000
MAX_ORDERS_PER_MINUTE=5
```

`ENABLE_LIVE_TRADING=false` 时，查询类接口可用，但下单/撤单会返回 403。

## 交易所名称

现货和合约适配器是分开的，避免把合约单误发到现货接口：

```text
okx             OKX 现货
binance         Binance 现货
okx_swap        OKX USDT 永续合约
binance_usdm    Binance USD-M Futures
```

常用 symbol：

```text
OKX 永续：BTC-USDT-SWAP
Binance USD-M：BTCUSDT
```

代码会做基础标准化，例如 OKX 传 `BTC-USDT` 会补成 `BTC-USDT-SWAP`，Binance 传 `BTC-USDT` 会转成 `BTCUSDT`。

## 运行

查看项目状态：

```bash
uv run python main.py status
```

启动 API：

```bash
uv run python main.py api
```

指定地址和端口：

```bash
uv run python main.py api --host 127.0.0.1 --port 8000
```

多 worker 并发启动：

```bash
uv run python main.py api --workers 4
```

也可以直接使用 uvicorn：

```bash
uvicorn app.api.server:create_app --factory --host 0.0.0.0 --port 8000 --workers 4
```

访问 API 文档：

```text
http://127.0.0.1:8000/docs
```

运行示例策略循环：

```bash
uv run python main.py trade
```

## 前端工作台

前端是 React + Vite + TypeScript，默认调用后端：

```text
http://127.0.0.1:8000
```

先启动后端：

```bash
uv run python main.py api --host 0.0.0.0 --port 8000 --workers 4
```

再启动前端：

```bash
cd frontend
npm install
npm run dev
```

访问：

```text
http://127.0.0.1:5173
```

如果后端地址不同，新建 `frontend/.env`：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000
```

前端第一版包含：

- API/LIVE 状态栏
- OKX Swap / Binance USD-M 切换
- 合约 symbol、数量、价格、杠杆和保证金模式
- 开多、平多、开空、平空
- maker/taker 手续费查询
- 合约成本估算
- 风控和本地持仓状态展示

## Docker 镜像

镜像会把后端 API 和前端页面打在一起：

- FastAPI 监听 `8000`
- React 静态页面由 FastAPI 托管
- `/api/v1/*` 仍然是后端接口
- `/docs` 仍然是 FastAPI 文档

本地构建：

```bash
docker build -t web3-trading:local .
```

本地运行：

```bash
docker run --rm \
  --name web3-trading \
  -p 8000:8000 \
  --env-file .env \
  web3-trading:local
```

访问：

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/docs
```

如果只是查看页面和状态，可以不传真实 API key，但真实下单前必须确认 `.env`：

```bash
ENABLE_LIVE_TRADING=false
```

## GitHub Actions 镜像推送

仓库包含 GitHub Actions workflow：

```text
.github/workflows/docker.yml
```

推送到 `main` 后会自动构建并推送镜像到 GHCR：

```text
ghcr.io/bilbilmyc/trading:latest
ghcr.io/bilbilmyc/trading:sha-<commit>
```

GitHub Packages 使用仓库自带的 `GITHUB_TOKEN`，不需要额外配置 Docker registry secret。仓库改成 private 后，GHCR 镜像通常也会跟随权限，需要登录后拉取：

```bash
echo <GITHUB_TOKEN> | docker login ghcr.io -u <GITHUB_USER> --password-stdin
docker pull ghcr.io/bilbilmyc/trading:latest
```

## 验证

编译检查：

```bash
uv run python -m compileall app config main.py
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

交易所列表：

```bash
curl http://127.0.0.1:8000/api/v1/exchanges
```

引擎状态：

```bash
curl http://127.0.0.1:8000/api/v1/engine/status
```

查询合约手续费率：

```bash
curl http://127.0.0.1:8000/api/v1/contracts/okx_swap/BTC-USDT-SWAP/fee-rate
curl http://127.0.0.1:8000/api/v1/contracts/binance_usdm/BTCUSDT/fee-rate
```

估算合约订单手续费：

```bash
curl "http://127.0.0.1:8000/api/v1/contracts/okx_swap/BTC-USDT-SWAP/cost-estimate?quantity=1&price=100000&liquidity=maker"
```

这个估算只计算 `notional * maker/taker fee rate`，不包含滑点、价差、资金费率和强平风险。

## API 示例

获取行情：

```bash
curl http://127.0.0.1:8000/api/v1/ticker/okx/BTC-USDT
```

获取 K 线：

```bash
curl "http://127.0.0.1:8000/api/v1/klines/okx/BTC-USDT?interval=1m&limit=100"
```

下单：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/order \
  -H "Content-Type: application/json" \
  -d '{
    "exchange": "okx",
    "symbol": "BTC-USDT",
    "side": "buy",
    "order_type": "market",
    "quantity": 0.001
  }'
```

如果 `ENABLE_LIVE_TRADING=false`，下单接口会返回 403。

## 合约下单示例

合约下单接口：

```text
POST /api/v1/contracts/order
```

OKX maker 开多：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/contracts/order \
  -H "Content-Type: application/json" \
  -d '{
    "exchange": "okx_swap",
    "symbol": "BTC-USDT-SWAP",
    "intent": "open_long",
    "quantity": 1,
    "order_type": "post_only",
    "price": 100000,
    "margin_mode": "cross",
    "position_side": "long",
    "leverage": 3
  }'
```

OKX 平多：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/contracts/order \
  -H "Content-Type: application/json" \
  -d '{
    "exchange": "okx_swap",
    "symbol": "BTC-USDT-SWAP",
    "intent": "close_long",
    "quantity": 1,
    "order_type": "post_only",
    "price": 100500,
    "margin_mode": "cross",
    "position_side": "long",
    "reduce_only": true
  }'
```

Binance USD-M maker 开空：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/contracts/order \
  -H "Content-Type: application/json" \
  -d '{
    "exchange": "binance_usdm",
    "symbol": "BTCUSDT",
    "intent": "open_short",
    "quantity": 0.001,
    "order_type": "post_only",
    "price": 100000,
    "position_side": "short",
    "leverage": 3
  }'
```

合约开平仓建议：

- 优先用 `post_only` 拿 maker 费率
- 止损或快速离场用 taker，不要为了手续费扩大风险
- 平仓要显式 `reduce_only=true`
- 下单前先查手续费和估算成本
- 实盘前必须在测试网/模拟盘验证 symbol、数量单位、仓位模式和杠杆

## 常见问题

### uv 找不到

先确认路径：

```bash
which uv
```

如果为空，把 `~/.local/bin` 加入 PATH：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 项目 Python 不是 3.13

重建虚拟环境：

```bash
uv venv --python 3.13 --managed-python --clear
uv sync
```

### 看到 /usr/bin/python3 3.9

这是系统 Python。不要删除它。项目只要用 `.venv/bin/python` 或激活 `.venv` 后的 `python` 即可。

### API 起来了但不能下单

检查 `.env`：

```bash
ENABLE_LIVE_TRADING=true
```

确认 API key、secret、passphrase 配置正确。实盘前先用测试网或模拟盘验证。

## 后续建议

- 加测试：交易所签名、symbol 标准化、风控拦截、API 禁止实盘下单
- 加订单持久化：SQLite/PostgreSQL 存储订单、成交、策略信号
- 加私有 WebSocket：订单成交和余额变化用交易所推送同步
- 加 dry-run/paper trading：在不触发交易所下单的情况下完整演练策略
