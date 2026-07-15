# Changelog

本项目版本号遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

### Added (风险事件时间线 + 命令面板)
- `LiveTradingGuard` 加 observer 模式：所有 kill switch 状态切换
  走 observer 统一记录，API endpoint 和 risk_manager 都不再单独写
  事件（消除重复）；observer 接收 reason 透传给 audit details
- `risk_manager.disable_trading / enable_trading` 透传 reason 到 guard
- `/api/v1/events/recent` 加 `minutes` 过滤（默认无过滤）
- 新增 `/events` 路由 + `EventsPage` 页面：7 个 category 过滤 tab
  （全部/风险/订单/持仓/成交/撤单/系统）+ CRIT/ERR/WARN 计数 pill +
  时间线列表 + 10s 自动刷新
- `Sidebar` 加"事件时间线"入口
- 新增 `CommandPalette` 全局命令面板：`⌘K` / `Ctrl+K` 打开，
  12 个页面跳转 + 3 个命令（刷新全部 / 切换实盘 / 切换 Kill Switch），
  模糊匹配 + ↑↓/Enter 选择 + Esc 关闭，App.tsx 全局挂载
- `recentEvents` API 签名改 opts 对象（向后兼容旧 limit/category 调用）

### Added (frontend freshness 全员接入)
- 5 个页面 PageHeader 接 `freshness` prop 显示"数据 / 风控 / Bot / 状态 / 配置 · Ns 前"
  pill（30s 内 fresh 绿 / 120s 内 stale 黄 / 之后 old 灰，1s tick）

### Added (TopTicker 24h 变化)
- 后端 `/api/v1/market/top-movers` 端点：默认 exchange + 10 个 USDT 永续
  热门币，server 端 20s TTL 缓存（独立 `ticker24h` cache 名字）
- 前端 `marketApi.topMovers()` 方法 + `TopTicker` 渲染 `is-up` / `is-down`
  / `is-flat` 三色 pill（30s 轮询，避免热点请求堆到 5s 价格 tick）
- 新增 `tests/test_top_movers_endpoint.py`（3 用例：默认 watchlist / symbols
  过滤 / TTL 缓存命中）+ `TopTicker.test.tsx`（2 用例：正负变化 pill 渲染）

### Added (RiskPage 5 重保险 sparkline)
- 后端 `engine._risk_snapshot_loop`：每 30s 把 5 重风控 + kill switch
  状态写一条 events row（category='risk', event_type='snapshot'）
- 后端 `/api/v1/risk/history?minutes=30&limit=200` 端点：从 events 拉
  最近 N 分钟 snapshot，0 行时返回空数组不抛错
- 前端 `api/risk.ts` 加 `RiskSnapshot` 类型 + `riskHistory()` 方法
- `RiskPage` 5 重保险每行 ProgressBar 右侧加 64×20 Sparkline（30 分钟
  趋势），60s 拉一次
- 新增 `tests/test_risk_history_endpoint.py`（3 用例：空 / 多行 / 时间窗过滤）

### Fixed (frontend fetch wrapper)
- `_client.ts` headers 合并：caller 传 init 不再覆盖默认 Content-Type
- `_client.ts` JSON.parse 失败兜底：HTML 502 / 非 JSON body 错误信息
  落回 response.statusText

### Added (前端信息密度 — 第二轮)
- `RiskPage` 加"5 重保险"Card：5 个 ProgressBar 显示实时占用 vs 上限
  （Kill Switch / 当日 P&L / 当前回撤 / 活跃仓位名义价值 / 每分钟
  订单），按 50% / 80% 阈值切色（绿/黄/红）
- `TopTicker` 加左侧 venue strip：每 15s 拉 `/api/v1/health/venues`，
  4 色 dot（绿=public ok / 黄=private fail / 红=public fail / 灰=disabled）
  + pulse 动画，hover tooltip 显示 testnet + clock skew
- `PageHeader` 加可选 `freshness` prop：标题旁渲染 "数据 · 3s 前"
  pill，按 30s / 120s 阈值切色（fresh / stale / old），内部 1s tick
- `api/meta.ts` 暴露 `VenueHealth` / `VenueHealthResponse` 类型 +
  `metaApi.venueHealth()` 方法
- `styles.css` 加 `.risk-bars` / `.top-ticker__venue*` / `pulse-ok/fail`
  / `.page-header__freshness*` 一组规则（颜色全部走现有 token）

- `StatusDrawer` 升级：顶栏加 4 个 level 过滤 tab（全部 / CRIT / ERR /
  WARN），badge 计数仍反映全 buffer；行可点击展开详情（exchange /
  symbol / category / level / timestamp）；每行加 category chip
  （system / order / risk / position / fill / cancel / error 不同色）
- 新增 `frontend/src/hooks/useSseStatus.ts`（SSE 连接级 hook：state =
  connecting/open/closed + lastEventAt 时间戳）
- `SettingsPage` 加"运行信息"Card：API 端点（`API_BASE`）/ 后端 env
  （testnet 警示）/ SSE 连接状态（重连中=warning）/ 上次心跳相对时间
  / 上次刷新绝对时间
- `StatusContext` 暴露 `lastRefreshedAt`
- `styles.css` 加 `.status-drawer__filter` / `__chip` / `__row-detail` /
  `__detail` 等 7 组新规则（severity → var(--negative/warning/info/...)）
- 新增 `StatusDrawer.test.tsx`（5 用例：empty state / 折叠态 / 过滤
  toggle / badge 不随 filter 隐藏 / 行展开详情）

### Added (dev 易用性)
- 根目录 `Makefile` 单入口：`make help / install / dev / test / test-frontend /
  test-all / lint / typecheck / format / ci / smoke / build / clean`
- `.env.example` 补 14 个 `BOT_*` 字段（Telegram bot 完整配置：token、
  chat id 白名单、daily report、quiet hours、rate limit、scope 头）
- `frontend/.env.example` 新建：文档化 `VITE_API_BASE_URL`（当前唯一用到）
  + 几个 reserved 变量（dev banner / SSE heartbeat / feature flags）
- `.github/workflows/ci.yml` test-frontend job 加 `npm run test:run`（之前
  只跑 typecheck + build，vitest 跑过但 CI 不知道）
- `CONTRIBUTING.md` 工作流段改用 `make ci` 一键门禁 + `make dev` 双进程

### Added (frontend vitest 基础)
- 装 vitest 4 + @testing-library/react + happy-dom（package.json devDeps）
- 新增 `frontend/vitest.config.ts`（happy-dom env + setup 文件）
- 新增 `frontend/src/test/setup.ts`（jest-dom matchers + afterEach cleanup）
- 新增 `frontend/src/utils/format.test.ts`（13 用例：formatNumber /
  formatPercent / formatSignedPercent / formatUsd 全覆盖边界）
- 新增 `frontend/src/hooks/useLiveEvents.test.ts`（10 用例：URL 构造 /
  payload 过滤 / buffer 截断到 50 / 重连重置 / 解析失败安全忽略 / 卸载关闭）
- `package.json` 加 `test` / `test:run` / `typecheck` scripts

### Added (SSE alerts stream → StatusDrawer)
- `/api/v1/stream/events` 升级：除 snapshot + heartbeat 外，轮询
  `engine.monitor.recent_alerts(50)` 与 `store.recent_events(50)`，
  按"游标 = 最高已发 timestamp"过滤，避免新连接重放历史
- 新增 `frontend/src/hooks/useLiveEvents.ts`：`EventSource` 订阅 SSE，
  仅保留 `kind: "event"` 载荷，浏览器原生重连 + buffer 自动重置
- `StatusDrawer` 改用 `useLiveEvents`，删除 5s 轮询（EngineContext.events
  通道），告警延迟从 0–5s 降到秒内
- 新增 `tests/test_sse_alerts_stream.py`（3 个）：snapshot 首发、
  Monitor.push 进入流、回填告警被 snapshot 游标过滤
- 修 `sqlite_store.append_events` 末尾重复 `self._conn.commit()` bug

### Added (bot 监控盯盘)
- Telegram bot 监控盯盘：从表面 5 个文件扩展到完整可启动的服务
- 新增 `app/bot/runner.py`（TradingBot 编排器：start/stop/run_forever + 异常不死）
- 新增 `app/bot/alerts.py`（BotAlertSubscriber：Monitor.on_alert 钩子 + 冷却去重 + 静默时段）
- 新增 `app/bot/scheduler.py`（daily_report_job：到点推日报，去抖动）
- 新增 `app/api/middleware.py`（ScopeContextMiddleware：X-Bot-Scope 头 → access log）
- `config/settings.py` 加 14 个 `bot_*` 字段 + `Settings.bot` property + `BotSettings` Pydantic 子模型
- `main.py` 加 `bot` 子命令（`python main.py bot [--engine-url ...]`）
- `BotApiClient` 每次请求注入 `X-Bot-Scope` + `Authorization: Bearer ...`，复用 `auth_api_key`
- bot 主动告警（CRITICAL/ERROR）绕过 quiet hours；WARNING 在静默时段内压下
- docs/bot.md 启用步骤 / 命令表 / 配置字段 / 静默策略 / 接入 FastAPI
- tests/test_bot.py 新增 26 个单测（settings.bot 属性、quiet hours 跨夜、BotConfig 白名单、
  formatter 全部纯函数、BotApiClient scope 头注入、dispatch + httpx 错误处理、
  TradingBot 生命周期 / 白名单拒绝 / token 缺失、BotAlertSubscriber 过滤 / 去重 /
  静默 / 渲染、app.bot 包导入完整性）

### Refactored (observability cleanup)
- `app/engine/metrics.py` 加 `safe_inc` / `safe_observe` / `safe_set` 帮手；删除 6 处
  裸 `try/except ImportError`（notifier ×3, alert_dispatcher ×2, cache ×1, monitor ×1）
- `qt_notifier_webhooks_total` 与新增 `qt_alert_dispatcher_total{provider,outcome}` 分离：
  generic webhook 走前者，飞书/钉钉/企微走后者
- `TTLCache` 加 `name` 字段（默认 `"default"`），`qt_cache_events_total{cache=...}` 现在能
  区分多实例
- `Monitor._check_loop` 把 `time.monotonic()` 移到 `asyncio.sleep` 之后，histogram 现在
  真正测的是 checker round-trip
- 3 个 `trader.py` 后台 loop 的 `qt_engine_loop_duration_seconds` 时序口径统一为
  "work + sleep" 一个完整 cycle
- `LiveOrderPipeline` 缓存 `_exchange_name` 到 `__init__`（不再每次 execute() 取 `name`）
- `LiveOrderPipeline` 信号过滤器 veto 现在也走 `qt_risk_rejections_total{reason="signal_filter:..."}`，之前漏计

### Added (P0-monitoring)
- 监控埋点全面接通：/metrics 端点从"定义了 9 个指标但全是 0"变成真实可观测
- qt_engine_loop_duration_seconds 接通到 signal_runner / order_sync / position_sync / monitor_check 四个 loop
- qt_orders_total + qt_risk_rejections_total 接通到 6 端口 LiveOrderPipeline 的 filled / failed / risk_rejected / trading_disabled 四个出口
- qt_monitor_alerts_total 接通到 Monitor._push_alert_obj 全量计数
- qt_positions_active gauge 接通到 PositionManager.update_position / remove_position / PositionSync.sync
- qt_app_info gauge 在 FastAPI lifespan 启动时 set(1) 携带 version + env
- 新增 qt_notifier_webhooks_total 接通 generic webhook + 飞书/钉钉/企微
- 新增 qt_cache_events_total 接通 TTL 缓存命中率
- tests/test_metrics_integration.py 新增 9 个集成测试，钉死每个指标的触发点
- docs/observability.md 新增 v0.3.0 章节，列明每处接通点

### Added (P2-5 + P1-9 + P2-4)
- `/metrics` Prometheus 端点 + 9 个指标（orders / risk / LLM / monitor / paper / engine loop / positions / app_info）— commit `0963ff3`
- 告警外发到飞书/钉钉/企微群机器人（独立 provider 模块，错误隔离）— commit `7d4eee1`
- `frontend/src/api.ts` 拆 9 个 domain 模块（560 → 66 行，-88%）— commits `62f4850` `721d188` `4dfe8bc` `22df689` `93f8135`
- `app/api/schemas.py` + `app/api/helpers.py` 抽 Pydantic + stateless helpers（server.py 1848 → 1705 行）— commit `6917863`

### Added (P0-4 + P0-5 + P1-1 + P1-6)
- 27 个 paper_trading 状态机测试（开仓/加仓/flip/关闭/标记价格/reset/load/summary）— commit `e334f41`
- 23 个 llm_analyzer 内部测试 + 修 OllamaProvider api_key bug — commit `a8d11c6`
- ruff + mypy + pre-commit 工具链（5 个历史遗留 bug 顺手抓出）— commit `cbcdf5f`
- 修 set_strategy_mode live 模式矛盾（3 处）— commit `9d5b206`

### Added (P1-4 + P1-5 + P0-2 + P0-1)
- LLM Prompt 风险上下文 + 交易历史 + few-shot 示例 + Symbol 白名单 + RiskContextProvider — commits `8b28b41` `73f333d` `91a019c`
- 可选 Bearer token 鉴权中间件（AUTH_API_KEY）— commit `a856a36`
- CI 移除 `--ignore` 死配置（SSE 测试现在跑）— commit `4e007e2`

### Added (UI)
- 双主题系统（深色 `#38BDF8` / 浅色 `#0284C7`）— 前端 5 维度重构
- 4 个共享组件：`PageHeader` / `Card` / `DataTable<T>` / `ListRow`
- Sidebar 5 组业务域菜单（数据/交易/分析/风控/系统）
- 主题切换按钮（Sun/Moon）+ localStorage 持久化
- FOUC 拦截脚本（首屏无闪烁）
- 可选 Bearer token 鉴权中间件（`AUTH_API_KEY`）
- LLM Prompt 注入风险上下文 + 交易历史 + few-shot 示例
- LLM 决策 symbol 白名单（`LLM_ALLOWED_SYMBOLS`）
- LLM 引擎数据接入（`LLMContextProvider` Protocol + `DefaultLLMContextProvider`）
- 修复 `set_strategy_mode` 接受 live 模式的 3 处矛盾
- 修复 `OllamaProvider` 缺 `api_key` 参数的构造 bug
- 修复 `llm_analyzer.py` 中 `cache` 未定义（之前编辑遗留）
- `app/api/schemas.py`（13 个 Pydantic models 抽出来）
- `app/api/helpers.py`（4 个 stateless helpers 抽出来）
- `app/engine/llm_context.py`（`DefaultLLMContextProvider`）
- `docs/architecture.svg`, `docs/llm-architecture.svg`（真实 SVG 资源）
- `docs/api.md`, `docs/deployment.md`, `docs/security.md`, `docs/STATUS.md`
- ruff + mypy + pre-commit 工具链接入
- CI 跑 `ruff check app/ config/`

### Changed
- 前端样式 5 维度重构：双主题 + token 化 + 共享组件
- 删除死代码：`.source-card` CSS 块
- CI 移除 `--ignore=` 跳过（SSE 测试 3/3 稳定通过）
- 后端 server.py 抽 schemas 和 helpers（1848 → 1705 行）

### Tests
- 633 → 738 个测试（+105）
- 0 回归
- 新增覆盖：API 鉴权、symbol 白名单、context provider、strategy mode 一致性、paper trading 状态机、llm_analyzer 内部方法

## [0.2.0] - 2026-06-29

第二轮迭代：13 个 commit 推进 P0/P1/P2 主要任务，覆盖 LLM 安全加固、
API 鉴权、文档、可观测性、前后端代码质量债务。

详见 [docs/STATUS.md](docs/STATUS.md) § "自本报告以来的更新"。

## [0.1.0] - 2026-06-29

初始版本。

### Added
- Web3 量化交易系统骨架
- Binance USDⓈ-M + OKX Swap + Bitget USDT 永续合约适配器
- 统一现货 + 永续合约接口
- SMA 双均线策略
- LLMAnalyzer v2（5 provider 抽象：OpenAI / Anthropic / DeepSeek / MiniMax / Ollama）
- LLMStrategy + LLMSignalFilter
- 5 重风控（仓位/金额/频率/日亏/回撤）
- 6 端口 LiveOrderPipeline
- Kill Switch + LiveTradingGuard
- Paper Trading 模拟账户
- SQLite 持久化（6 张表）
- SSE 实时事件流
- FastAPI REST API（70+ 路由）
- React 19 + Vite + TypeScript 前端
- Docker 多阶段构建 + CI/CD
