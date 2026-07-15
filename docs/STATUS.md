# 项目完成度评估报告

> **评估日期**：2026-06-29
> **评估范围**：Web3 币圈合约量化交易系统（接入 LLM 市场分析）
> **评估方法**：5 维度项目审计（correctness / readability / architecture / security / performance / ops / quality）
> **项目路径**：`/Users/mayc/codes/trading`

> **更新说明**：本报告为审计快照。报告之后 10 个 commit 推进了 P0/P1 列表：
>
> - P0-2 API 鉴权中间件（`a856a36`）
> - P1-4 LLM Prompt 风险上下文 + few-shot（`8b28b41` + `91a019c`）
> - P1-5 LLM symbol 白名单（`73f333d`）
> - P0-1 CI 移除 `--ignore` 死配置（`4e007e2`）
> - P1-6 修 set_strategy_mode live 模式矛盾（`9d5b206`）
> - P0-4 / P0-5 paper_trading + llm_analyzer 单测（`e334f41` + `a8d11c6`）
> - P1-1 ruff + mypy + pre-commit（`cbcdf5f`）
> - P2-3 server.py 抽 schemas + helpers（`6917863`）
>
> **结论**：完成度从 70-75% 提升到约 **80%**。文档（API/部署/安全/项目元）+ LLM 决策安全网（白名单+风险注入+5 重风控）都到位。

---

## 1. 总览

### 1.1 项目定位

一个**单机版**币圈永续合约量化交易系统：

- 3 个交易所适配器（Binance USDⓈ-M、OKX 永续、Bitget USDT 永续）
- 2 类策略引擎（规则型 SMA、LLM 驱动的策略）
- 完整风控体系（Kill Switch、滑动窗口、每日亏损、回撤监控、per-symbol 覆盖）
- 模拟盘 + 实盘双模式
- React 19 + Vite 前端（11 个页面，已重构主题系统）
- LLM 多 provider 抽象（OpenAI、Anthropic、DeepSeek、MiniMax、Ollama）

### 1.2 完成度总览

| 维度 | 完成度 | 评级 | 关键问题 |
|---|---|---|---|
| **核心交易闭环** | 90% | ✅ 优秀 | 行情 → 策略 → 风控 → 下单 → 同步 → 审计 跑通 |
| **LLM 集成** | 75% | ⚠️ 良好 | 多 provider 已支持，缺 few-shot、缺风控上下文 |
| **风控体系** | 85% | ✅ 良好 | 6 端口 LiveOrderPipeline 完整 |
| **前端 UX** | 75% | ⚠️ 良好 | 刚完成 UI 重构，但零测试、缺鉴权 |
| **后端架构** | 80% | ✅ 良好 | 分层清晰，6 端口流水线设计优秀 |
| **测试覆盖** | 60% | ⚠️ 中等 | 75 文件 / 632 用例，但关键业务文件弱覆盖 |
| **CI / 质量门禁** | 50% | ⚠️ 中下 | 60% 覆盖率门槛、CI 跳过失败测试是反模式 |
| **安全** | 35% | ❌ 薄弱 | 无 API 鉴权、明文 .env、无 HTTPS、无依赖扫描 |
| **可观测性** | 30% | ❌ 薄弱 | 无 Prometheus / OTel / 日志聚合 / 备份 |
| **文档** | 75% | ⚠️ 良好 | README 极详尽，但元文档缺失、引用资源不存在 |
| **部署** | 80% | ✅ 良好 | Docker + CI/CD 完整，无 k8s / 多环境 |
| **数据库** | 50% | ⚠️ 中等 | SQLite 单连接，无迁移框架，高吞吐会卡 |

**综合完成度：约 70-75%** — 核心交易闭环完成，但生产化要素（鉴权、可观测、备份、依赖扫描）缺失严重。

---

## 2. 详细审计

### 2.1 后端架构

#### 优点

- **分层清晰**：`api / engine / exchanges / strategies / models / data_sources / core` 职责分明
- **6 端口 LiveOrderPipeline** (`engine/live_order_pipeline.py:64-178`)：TradingGuard → SignalFilters → RiskGate → Exchange → Tracker → PositionRecorder → Observer，是测试与替换友好的优秀设计
- **统一数据流**：`ContractOrderRequest` + `ContractExchangeBase` 让三家合约 API 走同一接口
- **统一风险**：`RiskManager` 五重保险（熔断 / 滑动窗口 / 每日亏损 / 回撤 / per-symbol override）
- **审计可观测**：所有 trade/risk/position 事件统一落 `events` 表
- **Pydantic 配置验证**：`Field(gt=0, le=1)` 校验 + 嵌套结构（`ExchangeSettings / RiskSettings / ...`）

#### 缺点

| 严重度 | 问题 | 位置 |
|---|---|---|
| Critical | 无 API 鉴权中间件，任何人能调 kill-switch / place-order | `app/api/server.py:256-822` |
| Critical | API key 明文存于 `.env`，无加密 / KMS / Vault | `config/settings.py:97-166` |
| Required | 路由用 try/except 零散，无全局 `exception_handler` | `app/api/server.py` |
| Required | `ExchangeFactory` 缓存键用 `api_key[:8]`，可能让多账户场景混淆 | `app/exchanges/factory.py:107` |
| Required | `app/api/server.py` 73KB 巨型文件 — 单文件超 1000 行应拆分 | — |
| Optional | 缺 leaderboard / portfolio metrics 的真实实现（注释明确说"待接"） | `app/api/server.py:1328-1343` |
| Optional | 缺 webhook 验签（未来接入 TradingView 通知必须先补） | — |
| Optional | SQLite 单连接 WAL 模式写串行，高吞吐会 fsync 卡顿 | `app/core/sqlite_store.py:37-42` |

#### 性能

- ✅ 全 `httpx.AsyncClient` 异步 IO，事件循环不被阻塞
- ✅ 全部列表接口强制 `limit` Query 参数（防爆量）
- ✅ `TTLCache` 缓存 config / capabilities
- ⚠️ 缺 `asyncio.to_thread` 用于 CPU-bound 任务
- ⚠️ 写操作同步阻塞，大 batch 写入会卡事件循环（`executemany` 部分缓解）

---

### 2.2 LLM 集成

#### 已实现能力

- **5 个 provider**：OpenAI / Anthropic Claude / DeepSeek / MiniMax / Ollama
- **配置驱动 URL 前缀自动路由**：`llm_analyzer.py:176-208`
- **三态结果**：`LLMResponse` 是 `LLMDecided | LLMError` tagged union
- **重试策略**：仅对 5xx / timeout / network / rate-limit 重试，4xx 立即失败
- **Fingerprint 缓存**：30s TTL + prompt_version key（省钱不存上下文）
- **三档模式**：`signal` / `paper` / `live`
- **LLM 二次确认 (B 方案)**：`LLMSignalFilter` 可附加到引擎
- **共享风控**：LLM 决策与规则策略走同一 `RiskManager` + `LiveTradingGuard`
- **充分 mock 测试**：4 大 provider × timeout / 4xx / 5xx / parse-error / 429 / cache

#### 缺点

| 严重度 | 问题 | 位置 |
|---|---|---|
| Required | **Prompt 缺 few-shot 示例**，只有 schema 规则 | `app/strategies/llm_analyzer.py:93-142` |
| Required | **Prompt 未注入风险指标**（drawdown、daily_pnl、kill_switch 状态） | `llm_analyzer.py` 全部 |
| Required | **Prompt 未注入近期交易历史**（胜率、连盈/连亏） | — |
| Required | **无 symbol 白名单校验**，LLM 输出任何 symbol 都接受 | `app/engine/openai_provider.py` |
| Required | **流式输出只在 OpenAI 半成品实现**（不是真 SSE） | `app/engine/openai_provider.py:162-182` |
| Required | **无自动 failover**，provider 选一次，无 fallback 链 | `_select_provider` |
| Required | **API 接受 `mode="live"` 但 trader 拒绝** — 矛盾点 | `app/api/server.py:1504` vs `trader.py:262-263` |
| Required | **无应用层 QPS 限制**，仅靠 provider HTTP 429 重试 | — |
| Required | **无结构化 LLM 调用日志**（raw request/response/token/latency 不持久化） | — |
| Optional | 无多轮对话 / 历史压缩机制（每次独立 system+user pair） | `llm_analyzer.py:262-265` |
| Optional | LLM live 模式无额外 confirmation step | — |
| Optional | 旧版 v1 prompt 兼容代码（`trader.py:178-186` `LLMConfig`）疑似死代码 | — |

#### 安全性（LLM 专属）

- ✅ LLM 决策与规则策略共享同一风控闸门
- ✅ LLM 信号可被第二个 LLM filter 二次确认
- ❌ 无 LLM 专属的额外 confirmation（live 模式仍是信号自动过风险→下单）
- ❌ 无"AI 沙盒模式"显式开关（通过组合 `mode=signal + paper_account` 实现）

---

### 2.3 前端

#### 优点（2026-06-29 刚完成 UI 重构）

- ✅ **双主题系统**（深色 `#38BDF8` / 浅色 `#0284C7`），完整 CSS variable token 体系
- ✅ **4 个共享组件**：`PageHeader / Card / DataTable<T> / ListRow`
- ✅ **Sidebar 5 组菜单**（数据 / 交易 / 分析 / 风控 / 系统）+ lucide 图标
- ✅ **图表 token 化**：K 线、权益曲线、订单簿深度跟随主题
- ✅ **TypeScript 严格类型** + 泛型 DataTable
- ✅ **FOUC 拦截**：index.html 同步脚本，无首屏闪烁

#### 缺点

| 严重度 | 问题 | 位置 |
|---|---|---|
| Critical | **零测试覆盖**（无 vitest / jest / RTL） | `frontend/` 全目录 |
| Critical | **无 E2E 测试**（无 Playwright / Cypress） | — |
| Required | `app/api.ts` 56KB 巨型文件 — 应按 domain 拆分 | `frontend/src/api.ts` |
| Required | 部分页面（TradePage）仍有少量内联样式 | `pages/TradePage.tsx:64-65` |
| Required | 4 个页面（DataPage / TradeHistoryPage）仍有 7 处 `style={{...}}` | — |
| Optional | `<select>` 浏览器原生外观，无统一箭头 | `styles.css:245-261` |
| Optional | SettingsPage Webhook 启用改用 segmented 控件后，Telegram / Slack 模板需更友好引导 | — |
| Optional | 移动端 sidebar 抽屉宽度 280px 偏大 | `styles.css:1351-1377` |

---

### 2.4 测试覆盖

#### 优点

- **75 个测试文件 / 632 个测试用例 / 25% 异步**
- 4 大 LLM provider 完整 mock 矩阵（test_openai_provider / test_anthropic_provider / test_ollama_provider / test_deepseek_minimax）
- `test_live_order_pipeline.py` 是 6 端口流水线的最佳烟雾测试
- `test_kill_switch.py` / `test_live_trading_guard.py` 独立覆盖最高优先级风控路径
- `asyncio_mode = "auto"` 配置（无需 `@pytest.mark.asyncio` 装饰）

#### 缺点

| 严重度 | 问题 | 位置 |
|---|---|---|
| Critical | **CI 用 `--ignore=` 跳过失败测试**（`test_sse_endpoint.py` + `test_anthropic_provider.py::test_timeout_returns_timeout_error`） — 反模式 | `.github/workflows/ci.yml` |
| Critical | **零前端测试** | `frontend/` |
| Critical | **零 OpenAPI ↔ 前端 `api.ts` 契约测试** | — |
| Required | **`app/engine/paper_trading.py` 7800B 无独立测试**（仅 HTTP 端点间接测） | `app/engine/paper_trading.py` |
| Required | **`app/strategies/llm_analyzer.py` 16504B 最大策略文件几乎裸奔** | `app/strategies/llm_analyzer.py` |
| Required | **`app/core/sqlite_store.py` 18373B 测试密度低** | `app/core/sqlite_store.py` |
| Required | **覆盖率硬门槛 60%**（行业健康水位 75-85%） | CI 配置 |
| Required | **零 `@pytest.mark.parametrize`**（无 exchange × strategy 矩阵） | `tests/` |
| Required | **无 Python 静态分析**（无 ruff / mypy / pre-commit） | — |
| Optional | 无 VCR / respx HTTP 录制 | — |
| Optional | 无多 Python 版本测试矩阵（锁 3.13） | `pyproject.toml` |
| Optional | 无 `pytest-xdist` 并行 | — |

---

### 2.5 安全

#### 现状

| 维度 | 状态 | 详情 |
|---|---|---|
| API 鉴权 | ❌ | 无 JWT / API key / OAuth |
| CORS | ✅ | 仅放本地 Vite `127.0.0.1:5180` / `localhost:5180`；生产同源 |
| SQL 注入 | ✅ | 全部参数化占位符 |
| API key 加密 | ❌ | `.env` 明文 |
| HTTPS | ❌ | 无 nginx / traefik |
| 二次确认 | ❌ | live trading / kill switch 一次请求即生效 |
| Webhook 验签 | ❌ | 无入站 webhook |
| 依赖扫描 | ❌ | 无 `pip-audit` / `npm audit` |
| 速率限制 | ❌ | 无 HTTP rate limit |
| `.env` 不入仓 | ✅ | `.gitignore` 排除（但**实际 `.env` 已在仓库根目录**） |

#### 风险

- **Critical**：能访问 8000 端口即可调 `place-order` / `kill-switch` / 改杠杆 / 改 API key
- **Critical**：`.env` 文件实际存在于仓库根（2220 字节），需立即确认是否含真实密钥
- **High**：CORS 在生产直连 FastAPI 时会失败

---

### 2.6 可观测性 / 运维

#### 现状

- ✅ loguru 日志（带文件 rotation 10MB/zip/7d）
- ✅ SSE 端点 `/api/v1/stream/events`（但只发 heartbeat，audit events 注释"待接"）
- ✅ Health check `/health` + `/api/v1/health/venues`
- ✅ Docker healthcheck
- ❌ 无 Prometheus / OpenTelemetry
- ❌ 无 metrics 端点
- ❌ 无日志聚合（ELK / Loki / CloudWatch）
- ❌ Monitor Alert 外发通道未文档化（无 webhook / 邮件 / 钉钉 / 飞书）
- ❌ 无 SQLite 备份脚本
- ❌ 无优雅停机（uvicorn worker 待验证）
- ❌ 无 K8s readiness/liveness probe

---

### 2.7 文档

#### 优点

- ✅ **README 极详尽**（中文，690 行，覆盖 D→B→A LLM 架构图、6 子系统图、9 模块 API 清单、Docker 多模式、风控参数、AI 集成、FAQ）
- ✅ 包含风险提示（实盘必须 testnet 验证）
- ✅ `.env.example` 67 行带分区注释 + 35 个环境变量
- ✅ FastAPI 自动 OpenAPI `/docs`

#### 缺点

| 严重度 | 问题 |
|---|---|
| Critical | **`docs/architecture.svg` 和 `docs/llm-architecture.svg` 引用但文件不存在** |
| Required | 无 `docs/` 目录（README 引用不存在的资源） |
| Required | 无 LICENSE / CHANGELOG / CONTRIBUTING / SECURITY / TODO |
| Required | 无 ADR（架构决策记录） |
| Required | 无英文版 README / 双语支持 |
| Required | 无截图 / GIF demo |
| Optional | API 文档仅 curl 示例，无 SDK 客户端（Python / JS） |

---

### 2.8 部署

#### 优点

- ✅ Dockerfile 多阶段构建（node:22 + python:3.13 + UV frozen install）
- ✅ docker-compose.yaml（生产单体）+ docker-compose.dev.yml（前后端分离）
- ✅ GHCR 自动构建（`.github/workflows/docker.yml`）
- ✅ Docker healthcheck + named volume 持久化

#### 缺点

- ❌ 无 k8s / helm chart
- ❌ 无 staging vs production 区分
- ❌ 无 nginx / traefik 反向代理模板
- ❌ 无 HTTPS / TLS 终止
- ❌ 前端 `app/api.ts` 56KB 单文件 — 构建后 bundle 220KB

---

### 2.9 数据库

#### 现状

- SQLite 单文件（`data/trading.sqlite3`）
- WAL 模式 + 外键
- 裸 SQL + sqlite3 stdlib（无 SQLAlchemy）
- 6 张表：`strategies / signals / paper_account / paper_positions / paper_orders / events`
- 关键索引：timestamp / strategy_symbol / category / order_id

#### 缺点

- ❌ 无 Alembic / 迁移框架（`CREATE TABLE IF NOT EXISTS` 一次性）
- ❌ 单连接 + RLock（高吞吐写串行）
- ❌ `recent_events` 有动态拼 SQL（白名单 `category = ?`，注入面小但应改 query builder）
- ❌ 无 schema 演进支持

---

## 3. 优先级路线图

### P0 — 必须立即修复

| # | 任务 | 影响面 | 工作量 |
|---|---|---|---|
| P0-1 | **修掉 CI 用 `--ignore=` 跳过的失败测试**（`test_sse_endpoint.py` / `test_anthropic_provider.py::test_timeout_returns_timeout_error`） | 质量门禁真实性 | 1d |
| P0-2 | **添加 API 鉴权中间件**（JWT 或 API key + FastAPI Depends） | 全局安全 | 2-3d |
| P0-3 | **确认 `.env` 是否含真实密钥**（已 commit 到仓库） | 密钥泄漏 | 0.5d |
| P0-4 | **补 `app/engine/paper_trading.py` 单元测试** | 模拟撮合核心 | 2-3d |
| P0-5 | **补 `app/strategies/llm_analyzer.py` 单元测试** | 最大策略文件 | 2-3d |
| P0-6 | **为前端加 vitest 基础**（`api.ts` 解析 + 关键 hooks） | 前端回归防护 | 2-3d |

### P1 — 短期（1-2 月）

| # | 任务 | 工作量 |
|---|---|---|
| P1-1 | 添加 ruff + mypy + pre-commit | 1d |
| P1-2 | 提覆盖率阈值 60% → 80% | 0.5d |
| P1-3 | OpenAPI ↔ 前端 `api.ts` 契约测试（schemathesis） | 2d |
| P1-4 | LLM Prompt 改进：注入风险指标 + 近期交易 + few-shot 示例 | 1d |
| P1-5 | LLM 决策 symbol 白名单校验 | 0.5d |
| P1-6 | 修 `set_strategy_mode` 与 API 的矛盾（`live` 模式处理） | 0.5d |
| P1-7 | 补 `docs/` 目录 + 真正的 SVG 资源 | 1-2d |
| P1-8 | 多环境配置模板（`.env.development` / `.env.production`） | 0.5d |
| P1-9 | 监控告警外发通道文档化（webhook 模板） | 1d |
| P1-10 | 加 LICENSE / CHANGELOG / CONTRIBUTING / SECURITY | 0.5d |

### P2 — 中期（3-6 月）

| # | 任务 | 工作量 |
|---|---|---|
| P2-1 | LLM 流式输出真正实现（4 个 provider 都支持） | 3d |
| P2-2 | LLM 自动 failover + 多模型 budget | 3d |
| P2-3 | 拆分 `app/api/server.py` 73KB 巨型文件 | 2-3d |
| P2-4 | 拆分 `frontend/src/api.ts` 56KB 巨型文件 | 1-2d |
| P2-5 | Prometheus / OTel metrics 端点 | 2-3d |
| P2-6 | SQLite 备份脚本 + cron | 0.5d |
| P2-7 | Alembic 数据库迁移框架 | 1-2d |
| P2-8 | `@pytest.mark.parametrize` 多 exchange × strategy 矩阵 | 1-2d |
| P2-9 | VCR / respx HTTP 录制 | 1d |
| P2-10 | nginx / traefik HTTPS 反代模板 | 1d |

### P3 — 长期（6+ 月）

| # | 任务 | 工作量 |
|---|---|---|
| P3-1 | k8s / helm chart | 5-10d |
| P3-2 | 密钥管理（Vault / 云 Secrets） | 3-5d |
| P3-3 | OpenAPI SDK 自动生成（Python + TS） | 2-3d |
| P3-4 | 切换到 Postgres + 连接池 | 3-5d |
| P3-5 | 英文 README / 双语 | 1-2d |
| P3-6 | 多 Python 版本测试矩阵（3.13 + 3.14） | 1d |
| P3-7 | E2E 测试（Playwright） | 3-5d |

---

## 4. 关键文件清单

### 后端核心
- 入口：`/Users/mayc/codes/trading/main.py`
- API：`/Users/mayc/codes/trading/app/api/server.py`（73KB 巨型）
- 配置：`/Users/mayc/codes/trading/config/settings.py`
- 引擎：`/Users/mayc/codes/trading/app/engine/trader.py`（40KB TradingEngine 主体）
- LLM 抽象：`/Users/mayc/codes/trading/app/engine/llm_types.py`
- LLM 策略：`/Users/mayc/codes/trading/app/strategies/llm_strategy.py` + `llm_analyzer.py`
- 风控：`/Users/mayc/codes/trading/app/engine/risk_manager.py` + `live_trading_guard.py`
- 持久化：`/Users/mayc/codes/trading/app/core/sqlite_store.py`
- 模拟盘：`/Users/mayc/codes/trading/app/engine/paper_trading.py`

### 前端核心
- 入口：`/Users/mayc/codes/trading/frontend/src/App.tsx`
- 主题：`/Users/mayc/codes/trading/frontend/src/contexts/ThemeContext.tsx`
- 样式：`/Users/mayc/codes/trading/frontend/src/styles.css`（2134 行）
- API 客户端：`/Users/mayc/codes/trading/frontend/src/api.ts`（56KB 巨型）
- 共享组件：`/Users/mayc/codes/trading/frontend/src/components/{PageHeader,Card,DataTable,ListRow}.tsx`
- 页面：`/Users/mayc/codes/trading/frontend/src/pages/*.tsx`（11 个）

### 配置 / 文档
- README：`/Users/mayc/codes/trading/README.md`（中文 690 行）
- .env.example：`/Users/mayc/codes/trading/.env.example`
- CI：`/Users/mayc/codes/trading/.github/workflows/ci.yml`
- Docker：`/Users/mayc/codes/trading/{Dockerfile, docker-compose*.yml}`

---

## 5. 一句话总结

**核心交易闭环与多 provider LLM 集成已成熟跑通**（约 75% 完成度），但**生产化要素严重缺失**：无 API 鉴权、零前端测试、CI 跳过失败测试、可观测性与备份为零、`.env` 已在仓库根目录——核心定位是"单机自用/演示项目"，距离"团队协作/合规生产"还有显著差距。
