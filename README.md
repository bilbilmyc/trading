# Web3 量化交易系统

一个基于 Python/asyncio 的 Web3 量化交易系统，以 Binance 为主、Bitget 为辅、OKX 备用，支持统一 **现货 + 永续合约**接口，
内置 SMA 策略、**大模型 AI 分析**、风控、订单/持仓同步和监控告警。

![架构图](docs/architecture.svg)

> ⚠️ **风险提示**：默认关闭真实下单。只有显式设置 `ENABLE_LIVE_TRADING=true` 后 API 才允许下单和撤单。
> 实盘前务必在 **testnet** 验证完整流程。

---

## 功能一览

| 模块 | 功能 |
|------|------|
| **交易所接入** | Binance 现货/USD-M Futures + Bitget USDT Futures + OKX 现货/永续，统一抽象接口 |
| **交易引擎** | 多交易所、多策略并行、并发控制、生命周期管理 |
| **策略** | SMA 双均线 (内置) + **LLMAnalyzer 大模型分析 (新增)** |
| **风控** | 仓位/金额/频率/每日亏损/回撤限制 |
| **订单同步** | 定时从交易所拉取订单状态，更新本地记录 |
| **持仓同步** | 定时同步余额和合约持仓到 PositionManager |
| **监控告警** | 引擎健康、网络断开、风控触发 → 结构化 Alert |
| **模拟盘** | 内存 USDT 模拟账户，支持信号模拟执行 |
| **审计持久化** | SQLite 保存策略、信号、模拟盘状态、订单/风控事件 |
| **AI 分析** | 接入 OpenAI/Claude/DeepSeek/Ollama 分析市场，辅助决策 |
| **WebSocket** | Ticker 订阅/取消订阅/断线重连 |
| **REST API** | FastAPI 服务，查询行情/K 线/余额/挂单/下单/撤单/合约操作/引擎状态 |
| **前端** | React + Vite + TypeScript 合约交易工作台 |

---

## 目录

- [快速开始](#快速开始)
- [运行](#运行)
- [阶段 5：实盘自动交易](#阶段-5实盘自动交易)
- [AI 大模型分析](#ai-大模型分析)
- [LLM 策略：D→B→A 三层架构](#llm-策略db-a-三层架构)
- [前端工作台](#前端工作台)
- [Docker](#docker)
- [开发、构建与发布](#开发构建与发布)
- [API 参考](#api-参考)
- [项目结构](#项目结构)
- [后续开发](#后续开发) · [文档索引](#文档索引)
- [常见问题](#常见问题)

---

## 快速开始

> ⚠️ **不要提交 `.env`。** 默认 `ENABLE_LIVE_TRADING=false`；请先使用 testnet 和模拟盘完成验证。

### 方式一：Docker Compose（推荐）

前置条件：已安装并启动 Docker Desktop / Docker Engine。

```bash
# 1. 创建本地配置（交易所/LLM key 均可先留空）
cp .env.example .env

# 2. 构建并在后台启动：FastAPI API + 已打包的前端都在 :8000
# Windows PowerShell 可将 cp 替换为 Copy-Item
make docker-up
# 或：docker compose up --build -d

# 3. 验证与访问
curl http://127.0.0.1:8000/health
# 浏览器打开：http://127.0.0.1:8000

# 4. 查看日志 / 停止（SQLite named volume 会保留）
docker compose logs -f api
docker compose down
```

### 方式二：本地开发（前后端热更新）

前置条件：Python 3.13、[uv](https://docs.astral.sh/uv/)、Node.js 22。

```bash
# 一次性安装锁定版本的依赖
uv sync --all-extras --dev
cd frontend && npm ci && cd ..
cp .env.example .env

# 终端 1：API
uv run python main.py api --host 127.0.0.1 --port 8000

# 终端 2：Vite 前端（固定端口 :5180）
cd frontend && npm run dev
```

访问前端：<http://127.0.0.1:5180>；API 文档：<http://127.0.0.1:8000/docs>。
前端会自动将开发期请求发往 `http://127.0.0.1:8000`。需要远程 API 时，在 `frontend/.env.local` 设置 `VITE_API_BASE_URL`。

### 常用一键命令（macOS / Linux / WSL / Git Bash）

```bash
make install       # 安装 uv + npm 锁定依赖
make dev           # API :8000 + Vite :5180
make ci            # 与 CI 对齐的本地质量门禁
make docker-build  # 构建生产镜像
make docker-up     # 后台启动生产 Compose 栈
make docker-down   # 停止生产 Compose 栈，保留数据卷
```

Windows PowerShell 用户可直接使用上方的 `uv`、`npm`、`docker compose` 命令；`make` 目标需在 WSL 或 Git Bash 中运行。

---

## 运行

### 调试模式启动

开发调试时建议开启 DEBUG 日志，方便排查交易所请求和策略执行细节：

```bash
# API 服务（调试模式）
LOG_LEVEL=DEBUG uv run python main.py api --host 0.0.0.0 --port 8000

# 策略循环（调试模式）
LOG_LEVEL=DEBUG uv run python main.py trade

# 查看所有交易所健康状态
curl http://127.0.0.1:8000/api/v1/health/venues
```

### 查看状态

```bash
uv run python main.py status
```

### 启动 API 服务

```bash
uv run python main.py api --host 0.0.0.0 --port 8000
# 多 worker：
uv run python main.py api --host 0.0.0.0 --port 8000 --workers 4
```

### 运行策略循环

```bash
uv run python main.py trade
```

### API 文档

启动后访问：

```text
http://127.0.0.1:8000/docs
```

### FastAPI 调用关系速读

后端 HTTP 层主要在 `app/api/server.py`。先按这条链看，代码会清楚很多：

```text
main.py api
  -> uvicorn 启动
  -> create_app()
  -> AppState(settings)
  -> @app.get/post/delete 路由函数
  -> Depends(get_state) 注入同一个 AppState
  -> state.get_exchange() / state.engine / state.store
  -> 交易所适配器、交易引擎、SQLite
```

几个关键点：

- `create_app()`：装配整个 FastAPI 应用，创建运行时对象、注册中间件和路由。
- `AppState`：一个 API worker 里的共享上下文，放配置、SQLite、交易引擎和交易所客户端缓存。
- `Depends(get_state)`：FastAPI 的依赖注入。请求进来时自动把 `AppState` 传给路由函数。
- `call_exchange(...)`：统一包住交易所网络调用，把交易所错误转成稳定的 HTTP 响应。
- `reject_live_disabled(...)`：实盘关闭时拦截下单/撤单/改杠杆，同时写入审计事件。
- `POST /api/v1/contracts/order/preview`：真实下单前的预览入口，生成 `client_order_id`，估算名义价值、保证金、手续费和强平风险提示。

---

## 阶段 5：实盘自动交易

阶段 5 打通了从策略信号到实盘执行的完整链路，同时保护你不会意外全仓。

### 架构

```text
┌─────────┐  信号   ┌────────────┐  风控通过   ┌────────────┐
│ 策略     │───────→│ TradingEngine │─────────→│ Exchange   │
│ SMA/LLM  │        │ _execute_signal │         │ place_order│
└─────────┘        └────────────┘         └────────────┘
                           │
                    ┌──────┼──────┐
                    │      │      │
               OrderSync PositionSync Monitor
               (拉取订单) (拉取持仓) (健康告警)
```

### 6 个子系统

| # | 子系统 | 说明 | 启用方式 |
|---|--------|------|---------|
| 1 | **策略信号** | 策略产生 Signal(buy/sell/hold) | `POST /api/v1/strategies/{name}/start` |
| 2 | **风控检查** | RiskManager 拦截超限订单 | 默认启用 |
| 3 | **执行引擎** | TradingEngine 调用 exchange.place_order | `ENABLE_LIVE_TRADING=true` |
| 4 | **订单同步** | OrderSync 定时拉取交易所订单状态 | 引擎 start() 自动启动 |
| 5 | **持仓同步** | PositionSync 定时同步余额+合约持仓 | 引擎 start() 自动启动 |
| 6 | **监控告警** | Monitor 检查引擎+风控+网络健康 | 引擎 start() 自动启动 |

### 防全仓保护

实盘模式仍受风控限制保护：

```ini
# .env
MAX_POSITION_VALUE=1000        # 单笔最大金额 (USDT)
MAX_DAILY_LOSS=100             # 每日最大亏损
MAX_ORDERS_PER_MINUTE=5        # 每分钟最大订单数
STOP_LOSS_PCT=0.05             # 默认止损 5%
```

所有 API 下单端点（`/api/v1/order`、`/api/v1/contracts/order`）在 `ENABLE_LIVE_TRADING=false` 时返回 **403**。

### 监控与告警

```bash
# 监控面板
curl http://127.0.0.1:8000/api/v1/monitor/status
curl http://127.0.0.1:8000/api/v1/monitor/alerts
curl http://127.0.0.1:8000/api/v1/monitor/last-error

# 同步器状态
curl http://127.0.0.1:8000/api/v1/sync/status

# 手动触发同步
curl -X POST http://127.0.0.1:8000/api/v1/sync/orders/binance_usdm
curl -X POST http://127.0.0.1:8000/api/v1/sync/positions/binance_usdm
```

---

## AI 大模型分析

系统内置 LLMAnalyzer 模块，支持将市场数据发送给大模型分析，返回结构化交易建议。

### 支持的 LLM

| 提供方 | `LLM_BASE_URL` | 推荐模型 |
|--------|----------------|---------|
| **OpenAI** | `https://api.openai.com/v1` | `gpt-4o-mini`（成本低） |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-v4-flash` |
| **Ollama (本地)** | `http://localhost:11434/v1` | `llama3` |
| **vLLM (本地)** | `http://localhost:8000/v1` | 任意部署模型 |

### 配置

```ini
# .env
LLM_API_KEY=sk-your-key-here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_TEMPERATURE=0.3
LLM_DEFAULT_ORDER_AMOUNT=50    # 单笔默认金额 USDT
```

### 手动分析

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ai/analyze \
  -H 'Content-Type: application/json' \
  -d '{"exchange":"binance_usdm","symbol":"BTCUSDT","interval":"1h","limit":30}'
```

返回示例：

```json
{
  "decision": "buy",
  "confidence": 0.78,
  "reason": "BTC 突破 68500 阻力位后放量站稳，均线多头排列...",
  "suggested_action": "open_long",
  "suggested_quantity": 0.000727,
  "suggested_price": 68750,
  "stop_loss": 67200,
  "take_profit": 71000,
  "risk_level": "medium",
  "risk_note": "上方 70000 整数关口有压力"
}
```

---

## LLM 策略：D→B→A 三层架构

![LLM 三层架构](docs/llm-architecture.svg)

从**观察 → 辅助过滤 → 全自动**，逐步升级，每个阶段都受默认金额保护。

### D 方案：信号顾问（观察）

```bash
# 创建 LLM 策略 (mode=signal)
curl -X POST http://127.0.0.1:8000/api/v1/strategies/llm \
  -H 'Content-Type: application/json' \
  -d '{"exchange":"binance_usdm","symbol":"BTCUSDT",
       "interval":"1h","default_order_amount":50,
       "mode":"signal","enabled":true}'

# 启动信号运行器
curl -X POST http://127.0.0.1:8000/api/v1/runner/start \
  -H 'Content-Type: application/json' \
  -d '{"poll_seconds":300,"candle_limit":80}'

# 查看 LLM 信号
curl http://127.0.0.1:8000/api/v1/signals/recent?limit=5
```

- LLMStrategy 在 `generate_signals()` 中调用 LLM
- `mode=signal`：引擎不执行，信号仅展示在面板
- 每笔 `quantity = default_order_amount / current_price`

### B 方案：混合过滤（SMA + LLM 二次确认）

```bash
# 附加 LLM 过滤器
curl -X POST 'http://127.0.0.1:8000/api/v1/strategies/llm-filter/attach?\
exchange=binance_usdm&symbol=BTCUSDT&default_order_amount=50&min_confidence=0.5'

# 启动 SMA 策略
curl -X POST http://127.0.0.1:8000/api/v1/strategies/sma_5_20_btcusdt/start

# 查看被 LLM 拒绝的信号
curl 'http://127.0.0.1:8000/api/v1/strategies/llm-filter/rejected?limit=10'
```

- SMA 出信号 → `LLMSignalFilter.check()` → LLM 二次确认 → 放行/拒绝
- 方向不一致或置信度不足时拒绝
- 过滤器异常时默认放行，不阻塞交易

### A 方案：全自动执行

```bash
# 切换为 live 模式
curl -X POST http://127.0.0.1:8000/api/v1/strategies/llm_btcusdt_1h/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"live"}'

# 启动策略
curl -X POST http://127.0.0.1:8000/api/v1/strategies/llm_btcusdt_1h/start
```

- LLMStrategy `mode=live`：引擎自动执行信号
- 仍经过风控检查 + 过滤器链
- 单笔金额受 `default_order_amount` 限制

---

## 前端工作台

前端是 React + Vite + TypeScript。

```bash
# 先启动后端
uv run python main.py api --host 0.0.0.0 --port 8000

# 再启动前端
cd frontend
npm ci
npm run dev
```

访问 `http://127.0.0.1:5180`

功能：

- API/LIVE 状态栏
- Binance USD-M / Bitget USDT Futures / OKX Swap 切换
- 合约 symbol 搜索、数量、价格、杠杆、保证金模式
- 开多/平多/开空/平空方向选择
- Maker/Taker 手续费查询 + 成本估算
- 策略信号面板
- 风控 / 持仓状态展示
- 模拟盘

---

## Docker

生产镜像是一个单体服务：Docker 多阶段构建会生成 React 静态文件，并由 FastAPI 在 **:8000** 同时提供 Web UI 和 API。SQLite 保存于 `quant-trader-data` named volume，`docker compose down` 不会删除它。

### 生产 / 演示

```bash
cp .env.example .env
docker compose up --build -d
curl http://127.0.0.1:8000/health
docker compose logs -f api
```

访问 <http://127.0.0.1:8000>。停止服务但保留数据：`docker compose down`；如需同时清除 SQLite 数据卷：`docker compose down -v`（不可恢复）。

也可直接运行 CI 发布的镜像：

```bash
docker run --rm --name quant-trader -p 8000:8000 --env-file .env ghcr.io/bilbilmyc/trading:latest
```

### 开发 Compose（热更新）

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up --build
```

该模式启动 API reload（<http://127.0.0.1:8000>）和 Vite HMR（<http://127.0.0.1:5180>）。浏览器中的 Vite 前端通过 `VITE_API_BASE_URL=http://localhost:8000` 访问 API；不要把这个开发 Compose 用于生产。

停止开发栈：

```bash
docker compose -f docker-compose.dev.yml down
```

### 构建约定

- `Dockerfile` 先按 `uv.lock` 和 `frontend/package-lock.json` 安装锁定依赖，再复制源代码，便于复用构建缓存。
- `.dockerignore` 排除本地数据库、日志、虚拟环境和前端构建产物，避免把运行状态带进镜像。
- CI 会在每个面向 `main` 的 PR 构建镜像；仅 `main` 的 push（或 main 上手动触发）会登录 GHCR 并发布 `latest` 与 `sha-<commit>` 标签。

---

## 开发、构建与发布

本地质量门禁与 GitHub Actions 使用同一套锁定依赖和命令：

```bash
# 后端：ruff、pytest 覆盖率、API import smoke test
# 前端：TypeScript、Vitest、Vite production build
make ci
```

GitHub Actions 分为两条工作流：

| 工作流 | 触发 | 行为 |
|---|---|---|
| `CI` | `main` push、面向 `main` 的 PR、手动触发 | 后端 lint / 测试 / smoke，以及前端 typecheck / 测试 / build |
| `Build and Publish Docker Image` | 同上 | PR 只构建验证镜像；`main` push 才发布到 GHCR |

完整流程、排障与发布行为见 [docs/ci-cd.md](docs/ci-cd.md)。

---

## API 参考

### 系统与健康

```bash
GET  /health
GET  /api/v1/health/venues          # 各交易所公开/私有 API、时钟偏差、凭证状态
GET  /api/v1/config
GET  /api/v1/exchanges
GET  /api/v1/risk/kill-switch
POST /api/v1/risk/kill-switch       # {"enabled": true, "reason": "manual"}
```

### 行情数据

```bash
GET  /api/v1/ticker/{exchange}/{symbol}
GET  /api/v1/klines/{exchange}/{symbol}?interval=1m&limit=100
GET  /api/v1/trades/{exchange}/{symbol}?limit=50
```

### 账户与订单

```bash
GET  /api/v1/balances/{exchange}
GET  /api/v1/balances/{exchange}/available
GET  /api/v1/order/{exchange}/{symbol}/{order_id}
GET  /api/v1/orders/{exchange}/open?symbol=BTCUSDT
POST /api/v1/order                          # 需 ENABLE_LIVE_TRADING
POST /api/v1/contracts/order/preview        # 下单前预览，不会真实提交
POST /api/v1/contracts/order                # 合约专用，需 ENABLE_LIVE_TRADING
DELETE /api/v1/order/{exchange}/{symbol}/{order_id}
DELETE /api/v1/orders/{exchange}/open
```

### 合约

```bash
GET  /api/v1/contracts/{exchange}?search=BTC&limit=200
GET  /api/v1/contracts/{exchange}/{symbol}/fee-rate
GET  /api/v1/contracts/{exchange}/{symbol}/cost-estimate?quantity=1&price=100000&liquidity=maker
POST /api/v1/contracts/{exchange}/{symbol}/leverage?leverage=3&margin_mode=cross
```

### 引擎与策略

```bash
GET   /api/v1/engine/status
GET   /api/v1/strategies
POST  /api/v1/strategies/sma                          # 创建 SMA 策略
POST  /api/v1/strategies/llm                          # 创建 LLM 策略
POST  /api/v1/strategies/{name}/start
POST  /api/v1/strategies/{name}/stop
POST  /api/v1/strategies/{name}/mode                  # signal|paper|live
DELETE /api/v1/strategies/{name}
```

### 信号运行器

```bash
GET   /api/v1/runner/status
POST  /api/v1/runner/start     {"poll_seconds":60, "candle_limit":80}
POST  /api/v1/runner/stop
POST  /api/v1/runner/run-once
GET   /api/v1/signals/recent?limit=20
POST  /api/v1/signals/evaluate?exchange=binance_usdm&symbol=BTCUSDT
GET   /api/v1/events/recent?category=risk&limit=30
```

### 模拟盘

```bash
GET  /api/v1/paper
POST /api/v1/paper/reset   {"initial_cash": 10000}
```

### AI 分析

```bash
POST /api/v1/ai/analyze
  {"exchange":"binance_usdm","symbol":"BTCUSDT","interval":"1h","limit":30}
```

### LLM 策略管理

```bash
POST  /api/v1/strategies/llm                 # 创建 LLM 策略
POST  /api/v1/strategies/llm-filter/attach    # 附加 LLM 过滤器
GET   /api/v1/strategies/llm-filter/rejected  # 被拒信号列表
```

### 监控与同步

```bash
GET   /api/v1/monitor/status
GET   /api/v1/monitor/alerts?level=error&limit=50
GET   /api/v1/monitor/last-error
GET   /api/v1/sync/status
POST  /api/v1/sync/orders/{exchange}
POST  /api/v1/sync/positions/{exchange}
```

---

## 项目结构

```text
.
├── main.py                     # CLI 入口
├── config/
│   ├── __init__.py
│   └── settings.py             # 全部配置（风控/AI/监控/同步）
├── app/
│   ├── api/server.py           # FastAPI 路由
│   ├── core/                   # 日志、并发
│   ├── engine/
│   │   ├── trader.py           # 核心引擎
│   │   ├── risk_manager.py     # 风控
│   │   ├── position_manager.py # 持仓
│   │   ├── paper_trading.py    # 模拟盘
│   │   ├── order_sync.py       # 订单同步
│   │   ├── position_sync.py    # 持仓同步
│   │   ├── monitor.py          # 监控告警
│   │   └── llm_filter.py       # LLM 信号过滤器 (B)
│   ├── exchanges/              # 交易所适配器
│   │   ├── base.py             # ExchangeBase 抽象
│   │   ├── contract_base.py    # 合约抽象
│   │   ├── factory.py          # 工厂/单例
│   │   ├── binance.py / binance_usdm.py
│   │   ├── bitget_usdt_futures.py
│   │   └── okx.py / okx_swap.py
│   ├── models/                 # 数据模型
│   │   ├── order.py / position.py / balance.py
│   │   ├── market.py           # Ticker / Candlestick / Trade
│   │   └── contract.py         # 合约请求/费率/估算
│   └── strategies/
│       ├── base.py             # StrategyBase + Signal
│       ├── sma.py              # SMA 双均线
│       ├── llm_analyzer.py     # LLM 调用/ Prompt/ 解析
│       └── llm_strategy.py     # LLMStrategy (D/A)
├── frontend/                   # React 工作台
│   ├── src/App.tsx / api.ts / styles.css
│   └── package.json
├── docs/
│   ├── architecture.svg        # 架构图
│   └── llm-architecture.svg    # LLM 三层架构图
├── Dockerfile
├── .env.example
└── pyproject.toml
```

## 后续开发

详细规划与项目状态见 [`docs/STATUS.md`](docs/STATUS.md)（2026-06-29 审计，约 82% 完成度）。
近期完成 / 进行中：[`CHANGELOG.md`](CHANGELOG.md)。

## 文档索引

- [`docs/STATUS.md`](docs/STATUS.md) — 项目完成度 5 维度审计报告
- [`docs/architecture.svg`](docs/architecture.svg) — 系统架构图
- [`docs/llm-architecture.svg`](docs/llm-architecture.svg) — LLM D→B→A 三层架构图
- [`docs/api.md`](docs/api.md) — HTTP API 参考 + 鉴权说明
- [`docs/deployment.md`](docs/deployment.md) — 部署指南（开发/生产/Docker）
- [`docs/security.md`](docs/security.md) — 安全指南与 5 重 LLM 风控闸门
- [`docs/alerts.md`](docs/alerts.md) — 告警外发（飞书/钉钉/企微）配置
- [`docs/observability.md`](docs/observability.md) — Prometheus /metrics 端点与 Grafana 仪表盘建议
- [`CHANGELOG.md`](CHANGELOG.md) — 版本变更日志
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 贡献指南
- [`SECURITY.md`](SECURITY.md) — 漏洞报告策略

---

## 常见问题

### uv 找不到

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### API 不能下单

```bash
# 检查 .env
ENABLE_LIVE_TRADING=true
```

确认 API key 配置正确。实盘前先用 testnet。

### LLM 分析返回 "未配置 API Key"

```bash
# 在 .env 中配置
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
```

未配置时端点依然可用，返回 `hold` + 提示。

### Docker 拉取私有镜像

```bash
echo <GITHUB_TOKEN> | docker login ghcr.io -u <USER> --password-stdin
```

---

## 后续路线

详见 [`docs/STATUS.md`](docs/STATUS.md) §3 与 [`CHANGELOG.md`](CHANGELOG.md) v0.2.0 段。

### v0.2.0 已完成（13 个 commit）
- [x] API 鉴权中间件 — `a856a36`
- [x] LLM Prompt 风险 + few-shot + 数据接入 — `8b28b41` `91a019c`
- [x] LLM symbol 白名单 — `73f333d`
- [x] paper_trading / llm_analyzer 单测 — `e334f41` `a8d11c6`
- [x] ruff + mypy + pre-commit — `cbcdf5f`
- [x] 修 set_strategy_mode live 矛盾 — `9d5b206`
- [x] server.py 抽 schemas + helpers — `6917863`
- [x] 前端 api.ts 拆 9 个 domain（560 → 66 行）— `62f4850` 系列
- [x] 告警外发飞书/钉钉/企微 — `7d4eee1`
- [x] Prometheus /metrics 端点 — `0963ff3`
- [x] CI 移除 `--ignore=` 死配置 — `4e007e2`

### v0.3 候选（按 ROI 排，不承诺时间）
- 4 个 metrics 埋点深度接入（见 `docs/observability.md`）
- 前端 Settings 加"测试告警"按钮
- 钉钉加签 / 飞书签名校验（生产安全加固）
- server.py 路由分组（需 APIRouter 重构）

### P2（长期 / 不阻塞）
- [ ] 私有 WebSocket：订单成交推送
- [ ] 完整 OMS 状态机（PostgreSQL + Alembic）
- [ ] 多用户认证（JWT + RBAC）
- [ ] 策略回测框架可视化
- [ ] Prometheus / OTel metrics 端点

近期不再添加的项（明确不投入）：
- 自动化测试覆盖率门槛（P1-2 已剔除）—— 代码健康看 reviewer，不靠门槛
- 公网部署方案 —— 项目定位是个人 localhost 使用
