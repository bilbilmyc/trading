# 部署指南

## 前置要求

- Python 3.13（CI 锁 3.13；项目支持 3.13–3.14）
- Node 22（前端）
- uv（包管理）
- Docker 24+（可选，容器化部署）
- 可选：交易所 testnet API key + LLM API key

## 开发模式（前后端分离）

适合日常开发，热重载：

```bash
# 一次性
git clone <repo>
cd trading
uv sync --all-extras --dev
cd frontend && npm install && cd ..

# 启动后端（:8000）
uv run main.py api

# 启动前端（:5173，vite proxy → :8000）
cd frontend && npm run dev
```

访问 <http://localhost:5173>。

## 生产模式（单体 Docker）

镜像推送到 GHCR：

```bash
docker pull ghcr.io/bilbilmyc/trading:latest
docker compose up -d
```

`docker-compose.yaml` 启动一个服务：FastAPI 在 :8000 提供 API + 静态前端。

## 纯本地模式（不用 Docker）

```bash
cd frontend && npm run build && cd ..
uv run main.py api
# 访问 http://localhost:8000（前端由 FastAPI 静态文件服务）
```

## 环境变量（关键项）

完整列表见 `.env.example`。最重要的：

```bash
# 至少启用一个交易所（即使只是数据源）
BINANCE_ENABLED=true
BINANCE_USDM_ENABLED=true
BINANCE_API_KEY=<your-testnet-key>
BINANCE_SECRET_KEY=<your-testnet-secret>

# LLM 必填（至少一个 provider）
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# 实盘开关（默认 false；testnet 验证后再开）
ENABLE_LIVE_TRADING=false

# 可选：API 鉴权
AUTH_API_KEY=<generated-secret>
```

## 数据持久化

SQLite 文件路径：`data/trading.sqlite3`（Docker 中通过 named volume 持久化）。

Schema 演进：当前无 Alembic，使用 `CREATE TABLE IF NOT EXISTS` 一次性初始化。破坏性 schema 变更需要手动迁移。

## 监控与告警

内置：

- `GET /api/v1/monitor/status` — 监控器状态
- `GET /api/v1/monitor/alerts` — 告警列表
- `GET /api/v1/monitor/last-error` — 最近错误
- `GET /api/v1/stream/events` — SSE 实时事件流

外发告警需在 `Settings.webhook_url` 配置 webhook（详见 [security.md](security.md)）。

## 健康检查

Docker 自动跑 `python -c "urlopen('/health')"` 检查。K8s 用户需自己写 readiness/liveness probe YAML（项目当前无）。

## 升级流程

```bash
git pull
uv sync --all-extras --dev  # 拉新依赖
cd frontend && npm install && cd ..
uv run main.py api  # 自动跑 CREATE TABLE IF NOT EXISTS
```

升级前建议：

1. 备份 `data/trading.sqlite3`
2. 关闭实盘（`ENABLE_LIVE_TRADING=false`）
3. 等所有 in-flight 订单完成
