# Web3 量化交易系统

<p align="center">
  <strong>一个面向个人研究与本地部署的 Web3 量化交易工作台</strong><br />
  <sub>行情 · 策略 · AI 分析 · 风控 · 模拟盘 · 订单同步 · 可观测性</sub>
</p>

<p align="center">
  <a href="https://github.com/bilbilmyc/trading/actions/workflows/ci.yml"><img src="https://github.com/bilbilmyc/trading/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <img src="https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white" alt="Python 3.13+" />
  <img src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111827" alt="React 19" />
  <img src="https://img.shields.io/badge/pnpm-11-F69220?logo=pnpm&logoColor=white" alt="pnpm 11" />
  <a href="LICENSE"><img src="https://img.shields.io/github/license/bilbilmyc/trading" alt="License" /></a>
</p>

<p align="center">
  <a href="#快速开始">快速开始</a> ·
  <a href="#核心能力">核心能力</a> ·
  <a href="#安全边界">安全边界</a> ·
  <a href="#文档地图">文档地图</a>
</p>

> **项目定位**：这是一个用于个人研究、策略验证和本地运行的交易系统，不是面向公众的托管交易平台。默认不允许真实下单，所有实盘相关能力都需要显式开启并经过 testnet 验证。

![系统架构图](docs/architecture.svg)

## 目录

- [为什么做这个项目](#为什么做这个项目)
- [核心能力](#核心能力)
- [快速开始](#快速开始)
- [开发工作流](#开发工作流)
- [安全边界](#安全边界)
- [前端工作台](#前端工作台)
- [系统架构](#系统架构)
- [配置说明](#配置说明)
- [API 与可观测性](#api-与可观测性)
- [项目结构](#项目结构)
- [文档地图](#文档地图)
- [常见问题](#常见问题)
- [路线图](#路线图)

## 为什么做这个项目

很多量化脚本能“拉行情、发订单”，但从研究策略到安全执行，中间还缺少一整套可观察、可回溯、可逐步放量的工程能力。本项目把这些能力收敛到一个本地工作台中：

- 用统一接口接入多个交易所，减少策略与交易所 SDK 的耦合。
- 用信号模式、模拟盘和 testnet 把策略验证拆成可控阶段。
- 用风控闸门、Kill Switch、审计事件和同步器降低误操作风险。
- 用 React 工作台查看行情、策略、组合、风险、审计和运行事件。
- 用 OpenAI-compatible 接口接入不同 LLM，辅助分析而不是绕过风控。

## 核心能力

| 领域 | 能力 |
| --- | --- |
| **交易所** | Binance Spot / USDⓈ-M、Bitget USDT Futures、OKX Spot / Swap；统一现货与合约抽象 |
| **行情** | Ticker、K 线、成交、订单簿、资金费率、价格比较、WebSocket ticker 订阅 |
| **策略** | SMA 双均线、LLMAnalyzer（趋势 / 动量 / 成交量 / 波动率交叉验证）、LLM 策略三层模式（观察 / 过滤 / 执行） |
| **交易引擎** | 策略生命周期、信号处理、并发控制、订单执行、订单同步、持仓同步 |
| **风控** | 仓位与名义价值、下单频率、每日亏损、最大回撤、止损止盈、逐品种限制、Kill Switch |
| **验证** | 模拟盘、回测、下单预览、testnet 开关、策略信号与决策审计 |
| **监控** | 健康检查、结构化告警、SSE 事件流、Prometheus `/metrics`、Telegram 监控 Bot |
| **前端** | React 19 + Vite + TypeScript 交易终端；市场、交易、组合、策略、风控、审计等页面 |
| **持久化** | SQLite（WAL）保存策略、信号、交易、模拟账户、持仓和审计事件 |

## 快速开始

### 方案 A：Docker Compose（推荐）

适合第一次运行、演示和单机部署。只需要 Docker，不需要在宿主机安装 Python 或 Node.js。

```bash
# 1. 获取代码
git clone https://github.com/bilbilmyc/trading.git
cd trading

# 2. 创建本地配置（不要提交 .env）
cp .env.example .env

# 3. 默认构建并启动 API + 前端
docker compose up --build -d

# 4. 验证服务
curl http://127.0.0.1:8000/health
```

打开以下地址：

- Web 工作台：<http://127.0.0.1:8000>
- Swagger UI：<http://127.0.0.1:8000/docs>
- OpenAPI JSON：<http://127.0.0.1:8000/openapi.json>

常用命令：

```bash
docker compose logs -f api   # 查看日志
docker compose ps             # 查看服务状态
docker compose down           # 停止服务，保留 SQLite 数据卷
docker compose up --build -d  # 依赖或代码更新后重新构建
```

> Docker Compose 使用 named volume 保存 SQLite 数据。`docker compose down -v` 会同时删除数据卷，请确认不再需要历史数据后再执行。

### 方案 B：本地开发（前后端热更新）

前置条件：

- Python `3.13+`（`3.13 <= version < 3.15`）
- [uv](https://docs.astral.sh/uv/)
- Node.js `22`
- pnpm `11`（推荐通过 Corepack 启用）

本项目及后续前端项目统一使用 pnpm。仓库通过 `frontend/pnpm-workspace.yaml` 将 pnpm store 固定到 `~/.pnpm-store`，多个项目共享同一份依赖缓存。

```bash
# 1. 启用 pnpm
corepack enable

# 2. 安装后端与前端锁定依赖
uv sync --all-extras --dev --frozen
cd frontend && pnpm install --frozen-lockfile && cd ..

# 3. 创建配置
cp .env.example .env
```

然后分别启动后端和前端：

```bash
# 终端 1：FastAPI API
uv run python main.py api --host 127.0.0.1 --port 8000

# 终端 2：Vite dev server
cd frontend && pnpm dev
```

访问 <http://127.0.0.1:5180>。开发期前端会把 API 请求发往 `http://127.0.0.1:8000`；如需连接远程 API，在 `frontend/.env.local` 中设置 `VITE_API_BASE_URL`。

### 常用命令

| 命令 | 用途 |
| --- | --- |
| `make install` | 安装 uv 与 pnpm 锁定依赖 |
| `make dev` | 同时启动 API（`:8000`）和前端（`:5180`） |
| `make ci` | 执行本地完整质量门禁 |
| `make test` | 运行后端测试 |
| `make test-frontend` | 运行前端 Vitest |
| `make typecheck` | 运行 TypeScript 类型检查 |
| `make build` | 构建生产前端 |
| `make docker-up` | 构建并后台启动生产 Compose |
| `make docker-dev` | 启动 Docker 热更新开发栈 |

Windows 用户可以直接使用上面的 `uv`、`pnpm` 和 `docker compose` 命令；`make` 请在 WSL 或 Git Bash 中运行。

## 开发工作流

推荐按下面的顺序验证新策略或新交易功能：

```text
行情 / 历史数据
      ↓
策略信号（signal）
      ↓
下单预览 / 风控检查
      ↓
模拟盘（paper）
      ↓
testnet
      ↓
人工确认后再开启 live trading
```

后端入口：

```bash
uv run python main.py status                         # 查看已配置交易所
uv run python main.py api --host 0.0.0.0 --port 8000 # 启动 API
uv run python main.py trade                          # 运行示例策略循环
uv run python main.py bot                            # 启动 Telegram 监控 Bot（需配置）
```

调试时可以临时提高日志级别：

```bash
LOG_LEVEL=DEBUG uv run python main.py api --host 0.0.0.0 --port 8000
```

### 质量门禁

提交前建议运行与 CI 对齐的检查：

```bash
make ci
```

它会依次执行后端 ruff、pytest（含覆盖率门槛）、前端 typecheck、Vitest、生产构建和 API import smoke test。CI 配置见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。

## 安全边界

### 默认安全状态

- `ENABLE_LIVE_TRADING=false`：默认禁止真实下单、撤单和部分高风险操作。
- 所有交易所默认启用 testnet 配置；请先验证 API key、品种、数量精度和风险参数。
- `AUTH_API_KEY` 为空时适合 localhost 个人使用；部署到非本机环境前请配置 Bearer token。
- `.env`、交易所密钥、LLM 密钥和数据库文件不应提交到 Git。

### 开启实盘前的最低检查清单

- [ ] 已在 testnet 完整跑通行情、信号、下单预览、下单、撤单和持仓同步。
- [ ] 已确认 `MAX_POSITION_VALUE`、`MAX_DAILY_LOSS`、`MAX_DRAWDOWN_PCT` 等限制。
- [ ] 已验证 Kill Switch 和 API 鉴权。
- [ ] 已确认只开放需要的交易所、交易品种和 LLM 白名单。
- [ ] 已准备可观测性和异常恢复方案。

> **不要把本项目当作投资建议。** 交易可能导致本金损失；真实资金请自行评估风险并承担后果。安全说明见 [`docs/security.md`](docs/security.md) 和 [`SECURITY.md`](SECURITY.md)。

## 前端工作台

前端位于 [`frontend/`](frontend/)，使用 React 19、Vite、TypeScript、Wouter 和 pnpm。页面按功能拆分并通过 lazy loading 加载：

| 路由 | 页面 |
| --- | --- |
| `/markets` | 市场总览 |
| `/data` | 行情与数据 |
| `/watchlist` | 自选列表 |
| `/trade` | 交易面板 |
| `/portfolio` | 投资组合 |
| `/trade-history` | 成交历史 |
| `/strategies` | 策略管理 |
| `/risk` | 风控面板 |
| `/audit` | 决策与交易审计 |
| `/events` | 运行事件时间线 |
| `/bot` | Telegram Bot 监控 |
| `/settings` | 系统设置 |

前端脚本：

```bash
cd frontend
pnpm dev       # :5180
pnpm typecheck
pnpm test:run
pnpm build
pnpm preview   # :4173
```

## 系统架构

```text
┌──────────────────────────────────────────────────────────────┐
│ React 工作台：行情 · 交易 · 策略 · 风控 · 审计 · 监控         │
└──────────────────────────────┬───────────────────────────────┘
                               │ REST / SSE
┌──────────────────────────────▼───────────────────────────────┐
│ FastAPI API                                                   │
│ auth · validation · routing · AppState                        │
└───────────┬──────────────────┬──────────────────┬────────────┘
            │                  │                  │
     TradingEngine       Data Sources       SQLite Store
     策略 / 信号 / 风控     行情 / WebSocket     WAL / 审计 / 状态
            │
     Exchange adapters
     Binance · Bitget · OKX
```

核心调用链：

```text
main.py api
  → create_app()
  → AppState
  → FastAPI route
  → TradingEngine / SQLiteStore / ExchangeFactory
  → strategy / risk / exchange adapter
```

设计原则：

- **薄路由**：API 层负责校验和编排，业务逻辑集中在 engine、strategy 和 exchange 层。
- **统一抽象**：策略依赖 `StrategyBase`，交易所依赖 `ExchangeBase` / `ContractExchangeBase`。
- **先观察再执行**：signal、paper、testnet、live 是逐级放量，而不是一键切换。
- **可审计**：策略信号、LLM 决策、风控拒绝、Kill Switch 和同步事件写入 SQLite。

## 配置说明

从示例开始：

```bash
cp .env.example .env
```

最常用配置如下：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | 运行环境 |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | API 监听地址 |
| `SQLITE_PATH` | `data/trading.sqlite3` | 本地 SQLite 路径 |
| `DEFAULT_EXCHANGE` | `binance_usdm` | 默认交易所 |
| `DEFAULT_SYMBOL` | `BTCUSDT` | 默认品种 |
| `ENABLE_LIVE_TRADING` | `false` | 实盘总开关，务必谨慎 |
| `AUTH_API_KEY` | 空 | 可选 Bearer 鉴权 |
| `LLM_API_KEY` | 空 | OpenAI-compatible API key |
| `LLM_BASE_URL` | OpenAI v1 | LLM API 地址 |
| `LLM_MODEL` | `gpt-4o-mini` | LLM 模型名 |
| `LLM_ALLOWED_SYMBOLS` | 空 | LLM 可决策品种白名单 |
| `ALERT_*` | 空 | 飞书 / 钉钉 / 企微告警 |
| `BOT_*` | 关闭 | Telegram 监控 Bot |

完整配置和每个参数的注释见 [`.env.example`](.env.example)。

### LLM 接入

系统使用 OpenAI-compatible HTTP API，默认支持以下类型：

| 类型 | 示例 `LLM_BASE_URL` |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Ollama | `http://localhost:11434/v1` |
| vLLM | `http://localhost:8000/v1` |

LLM 只负责分析和生成结构化建议，最终是否执行仍要经过策略模式、风控检查、实盘开关和交易所适配器。启用 LLM 信号过滤器后，实盘流水线会在过滤前从当前交易所刷新 ticker 和策略周期 K 线；行情获取失败、LLM 调用失败或返回无效结果时均采用 fail-closed，直接拒绝信号。

## API 与可观测性

启动服务后优先使用自动生成的 API 文档：

- [Swagger UI](http://127.0.0.1:8000/docs)
- [OpenAPI JSON](http://127.0.0.1:8000/openapi.json)
- [API 路由说明](docs/api.md)

常用健康检查：

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/health/venues
curl http://127.0.0.1:8000/api/v1/monitor/status
curl http://127.0.0.1:8000/metrics
```

设置 `AUTH_API_KEY` 后，状态变更和危险端点使用：

```bash
curl \
  -H "Authorization: Bearer $AUTH_API_KEY" \
  http://127.0.0.1:8000/api/v1/engine/status
```

## 项目结构

```text
.
├── app/
│   ├── api/              # FastAPI 路由、鉴权、schema、SSE
│   ├── bot/              # Telegram 监控 Bot
│   ├── core/             # 日志、SQLite、缓存、基础设施
│   ├── data_sources/     # 公共行情数据源
│   ├── engine/           # 交易引擎、风控、同步、监控、模拟盘
│   ├── exchanges/        # Binance / Bitget / OKX 适配器
│   ├── models/           # 行情、订单、持仓、合约模型
│   └── strategies/       # SMA、LLMAnalyzer、LLMStrategy
├── frontend/
│   ├── src/pages/        # 工作台页面
│   ├── src/components/   # UI 组件
│   ├── src/api/          # 按领域拆分的 API client
│   ├── package.json      # pnpm scripts
│   └── pnpm-workspace.yaml # 共享 ~/.pnpm-store
├── tests/                # 后端测试
├── docs/                 # 架构、API、部署、安全与运维文档
├── main.py               # CLI：api / trade / status / bot
├── .env.example          # 配置模板
├── Dockerfile            # 生产镜像
├── docker-compose.yaml   # 生产栈
└── Makefile              # 常用开发命令
```

## 文档地图

| 文档 | 内容 |
| --- | --- |
| [文档总览](docs/README.md) | 按使用场景查找所有文档 |
| [部署指南](docs/deployment.md) | Docker、本地开发、升级和排障 |
| [HTTP API](docs/api.md) | 路由分组、鉴权和错误响应 |
| [安全指南](docs/security.md) | 实盘保护、LLM 风险闸门和密钥管理 |
| [告警配置](docs/alerts.md) | 飞书、钉钉、企业微信告警 |
| [Telegram Bot](docs/bot.md) | 监控 Bot 配置和运行方式 |
| [可观测性](docs/observability.md) | Prometheus、事件流和监控建议 |
| [系统状态](docs/STATUS.md) | 当前完成度、已知问题和路线图 |
| [贡献指南](CONTRIBUTING.md) | 分支、测试、代码风格和 PR 约定 |
| [变更日志](CHANGELOG.md) | 功能与版本变更记录 |
| [安全漏洞报告](SECURITY.md) | 私下报告安全问题 |

## 常见问题

### pnpm 如何共享依赖缓存？

仓库已固定 `frontend/pnpm-workspace.yaml`：

```yaml
storeDir: ~/.pnpm-store
```

首次使用可以检查：

```bash
corepack enable
pnpm store path
```

后续新建前端项目时，默认也使用 pnpm；除非明确指定 bun。不要为每个项目单独配置 npm cache，也不要把 `node_modules` 提交到仓库。

### API 启动了，但前端请求失败

确认后端在 `:8000`、前端在 `:5180`，并检查 `frontend/.env.local` 是否配置了错误的 `VITE_API_BASE_URL`。本地开发时 FastAPI CORS 只允许本地 Vite 来源。

### API 返回 403，不能下单

这是默认安全保护。确认你已经在 testnet 验证完整流程后，才考虑设置：

```ini
ENABLE_LIVE_TRADING=true
```

同时检查交易所 API key、账户权限和风控参数。相关端点还可能要求 `AUTH_API_KEY`。

### LLM 分析提示未配置 API Key

```ini
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

未配置时系统仍可运行，但 AI 分析会返回 `hold` 或未配置提示。

### 端口被占用

```bash
# 检查端口
lsof -i :8000
lsof -i :5180
```

调整端口时要同时更新 API 地址和 CORS allowlist，不要只修改 Vite 端口。

## 路线图

当前优先级以 [`docs/STATUS.md`](docs/STATUS.md) 为准。方向包括：

- 完善 metrics 深度埋点与 Grafana 仪表盘。
- 加强告警 provider 的签名校验和测试按钮。
- 继续拆分 API router，降低单文件复杂度。
- 增强策略回测、WebSocket 成交推送和 OMS 状态管理。
- 在保持“个人 localhost 优先”定位的前提下，逐步补齐多用户能力。

## 参与贡献

欢迎提交 Issue、改进文档或发起 Pull Request：

1. 先阅读 [贡献指南](CONTRIBUTING.md)。
2. 从 `main` 创建主题分支。
3. 保持一个 PR 一个主题，并在描述中写清动机、改动和验证方式。
4. 提交前运行 `make ci`。

如果这个项目对你有帮助，欢迎点一个 ⭐，这会帮助项目获得更多反馈。
