# 部署与运行指南

## 运行模式与端口

| 场景 | 命令 | Web UI | API |
|---|---|---:|---:|
| 生产 / 演示（Docker） | `docker compose up --build -d` | `:8000` | `:8000` |
| 本地开发 | `uv run python main.py api` + `cd frontend && npm run dev` | `:5180` | `:8000` |
| Docker 开发 | `docker compose -f docker-compose.dev.yml up --build` | `:5180` | `:8000` |

生产模式由 FastAPI 提供编译后的静态前端，因此只暴露一个端口。开发模式运行 Vite；浏览器端 API 地址默认按 `:5180 → http://127.0.0.1:8000` 解析，可使用 `VITE_API_BASE_URL` 覆盖。

## 前置要求

- **Docker 模式**：Docker Desktop / Docker Engine（含 Compose v2）
- **本地模式**：Python 3.13、uv、Node.js 22
- 可选：交易所 testnet API key、LLM API key

## 生产部署（推荐）

```bash
cp .env.example .env
# 检查 ENABLE_LIVE_TRADING=false，除非已完成 testnet 验证
docker compose up --build -d
curl http://127.0.0.1:8000/health
docker compose logs -f api
```

浏览器访问 <http://127.0.0.1:8000>，API 文档为 <http://127.0.0.1:8000/docs>。

服务生命周期：

```bash
docker compose down       # 停止容器，保留 quant-trader-data 卷
docker compose up -d      # 使用已有镜像重新启动
docker compose up --build -d  # 代码或依赖更新后重建并启动
docker compose down -v    # 同时删除 SQLite 数据卷（不可恢复）
```

也可以使用已发布镜像：

```bash
docker pull ghcr.io/bilbilmyc/trading:latest
docker run --rm --name quant-trader -p 8000:8000 --env-file .env ghcr.io/bilbilmyc/trading:latest
```

## 本地开发（前后端分离）

```bash
uv sync --all-extras --dev
cd frontend && npm ci && cd ..
cp .env.example .env

# 终端 1
uv run python main.py api --host 127.0.0.1 --port 8000

# 终端 2
cd frontend && npm run dev
```

访问 <http://127.0.0.1:5180>。FastAPI 的 CORS 仅允许本地 Vite 的 `localhost:5180` / `127.0.0.1:5180` 来源。

## Docker 开发（热更新）

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up --build
```

API 容器以 Uvicorn reload 运行，前端容器以 Vite HMR 运行。浏览器访问 <http://127.0.0.1:5180>；停止命令为：

```bash
docker compose -f docker-compose.dev.yml down
```

## 配置与数据

完整配置清单在 `.env.example`。实践要求：

- 永远不要提交 `.env` 或交易所 / LLM 密钥。
- 默认保持 `ENABLE_LIVE_TRADING=false`；先在 testnet 完整验证。
- Docker 的 SQLite 数据位于 `quant-trader-data` named volume；本地默认位于 `data/trading.sqlite3`。
- 调整 `.env` 后请重启对应服务；不需要重建镜像，除非代码或依赖变化。

## 健康检查与排障

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/health/venues
docker compose ps
docker compose logs --tail=200 api
```

如果 :8000 或 :5180 已被占用，请停止占用端口的进程，或在 Compose 文件和前端 API 配置中成对调整端口。不要只改 Vite 端口：API 客户端回退逻辑与 CORS allowlist 必须同步更新。

## 升级流程

```bash
git pull
uv sync --all-extras --dev --frozen
cd frontend && npm ci && cd ..
make ci
# 或重新发布：docker compose up --build -d
```

发布与 CI/CD 行为见 [ci-cd.md](ci-cd.md)。
