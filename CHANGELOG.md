# Changelog

本项目版本号遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

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
