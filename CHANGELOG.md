# Changelog

本项目版本号遵循 [Semantic Versioning](https://semver.org/)。

## [Unreleased]

### Added
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
