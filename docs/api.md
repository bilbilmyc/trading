# HTTP API 参考

FastAPI 自动生成的 OpenAPI 文档在 `/docs`（Swagger UI）和 `/openapi.json`。

## 鉴权

`/api/v1/*` 端点支持**可选 Bearer token 鉴权**：

- 默认（`AUTH_API_KEY` 留空）：无鉴权，localhost 个人使用场景
- 设置 `AUTH_API_KEY=<secret>` 后：所有状态变更端点要求 `Authorization: Bearer <secret>`
- 所有状态变更和交易控制端点挂上 `require_api_key` 依赖（kill-switch、order、cancel、leverage、paper、LLM filter 等）

生成密钥：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 路由分组

| 分组 | 路径前缀 | 端点数 | 鉴权 |
|------|---------|--------|------|
| 健康 | `/health`, `/api/v1/health` | 2 | 否 |
| 配置 | `/api/v1/config`, `/api/v1/exchanges` | 2 | 否 |
| 行情（公开） | `/api/v1/ticker`, `/klines`, `/trades`, `/prices`, `/contracts/*` | 10+ | 否 |
| 历史行情目录 | `/api/v1/market-data/datasets*` | 6 | 导入为**是**；查询为否 |
| 风险 | `/api/v1/risk/kill-switch` | 1 | **是** |
| Bot 自动化 | `/api/v1/bot`, `/api/v1/bot/autopilot/*` | 3 | 自动下单端点**是** |
| 账户（私有） | `/api/v1/balances/*` | 2 | 否（需配置 key） |
| 下单 | `/api/v1/order`, `/api/v1/contracts/order` | 2 | **是** |
| 撤单 | `DELETE /api/v1/order/*`, `DELETE /api/v1/orders/*/open` | 2 | **是** |
| 引擎 | `/api/v1/engine/*`, `/api/v1/runner/*` | 5 | 部分 |
| 模拟盘 | `/api/v1/paper`, `/api/v1/paper/positions/close`, `/api/v1/paper/reset` | 3 | **是**（写） |
| 策略 | `/api/v1/strategies/*` | 10+ | **是**（写） |
| 信号/事件 | `/api/v1/signals/recent`, `/api/v1/events/recent` | 2 | 否 |
| 风控计算 | `/api/v1/sizing`, `/api/v1/atr-sizing` | 2 | 否 |
| 回测/实验 | `/api/v1/backtest`, `/api/v1/backtest/grid-search`, `/api/v1/backtest/portfolio`, `/api/v1/backtests/*`, `/api/v1/strategies/suggest` | 4 | 读取实验为**是** |
| 投资组合 | `/api/v1/portfolio/*`, `/api/v1/trade-history` | 3 | 否 |
| AI | `/api/v1/ai/analyze`, `/api/v1/ai/insights`, `/api/v1/ai/decisions*` | 5 | **是** |
| LLM 策略 | `/api/v1/strategies/llm*` | 3 | **是** |
| 监控/同步/对账 | `/api/v1/monitor/*`, `/api/v1/sync/*`, `/api/v1/reconciliation/*` | 8+ | 读取与恢复均需 **是** |
| 数据源 | `/api/v1/sources` | 3 | **是**（写） |
| SSE | `/api/v1/stream/events` | 1 | 否 |
| 平仓（实盘） | `/api/v1/positions/close` | 1 | **是** |
| 平仓（模拟盘） | `/api/v1/paper/positions/close` | 1 | **是** |

### 历史行情数据目录

历史行情目录把每个导入数据集写入不可变的 Parquet 文件，并将数据集元数据和查询索引保存在 DuckDB。标准 K 线字段为 `symbol`、`timestamp`、`open`、`high`、`low`、`close`、`volume`、`source`、`timeframe`。`timestamp` 必须带明确时区偏移；服务端统一转换为 UTC 并在 API 响应中以 `Z` 表示。

- `POST /api/v1/market-data/datasets`：导入 JSON K 线，需 API key。请求包含 `symbol`、`timeframe`、`source` 与 `candles`；每根 K 线使用标准字段。
- `POST /api/v1/market-data/datasets/parquet?symbol=BTCUSDT&timeframe=1h&source=binance`：导入 Parquet 原始请求体，需 API key。Parquet 必须包含标准 K 线字段。
- `GET /api/v1/market-data/datasets`、`GET /api/v1/market-data/datasets/{version}`：列出或读取数据集元数据。
- `GET /api/v1/market-data/datasets/{version}/candles?symbol=BTCUSDT&timeframe=1h&start=...&end=...`：按品种、周期和 UTC 时间范围读取版本中的 K 线。

版本号格式为 `md-<内容 SHA-256>`，相同的规范化输入会幂等返回同一个版本。导入时会生成质量报告，检测缺失、重复、倒序、间隔、OHLC 关系、非正价格、异常成交量和 24x7 UTC 交易日历对齐。质量不合格的数据集会被保留以便审计，但不能用于回测；引用它会返回 `409`。

默认目录可通过以下环境变量配置：

```dotenv
MARKET_DATA_CATALOG_PATH=data/market_data.duckdb
MARKET_DATA_PARQUET_DIR=data/market_data
```

### 订单执行仿真内核

`app.engine.simulation` 提供回测、模拟盘适配器共用的确定性订单生命周期。除 SMA 回测默认使用的下一根 K 线 IOC 市价单外，策略可通过 `SignalEvent` 指定以下订单语义：

- 订单类型：`market`、`limit`、`stop_market`、`take_profit_market`；限价单在触及价格时给予价格改善，条件单按照 K 线高低价触发。
- 有效期：`ioc`、`fok`、`gtc`，以及绝对 `expires_index`。GTC 未成交或部分成交的剩余数量会进入下一根 K 线继续管理；IOC 剩余数量会取消，FOK 在不能全额成交时拒绝。
- `post_only`：仅限限价单。若限价在当前买一/卖一处会立即吃单，订单会以 `post_only_would_take` 拒绝。
- 订单取消：策略可发出 `SignalEvent(action="cancel", cancel_order_id="...")`，得到明确的 `cancelled` 状态。
- 执行成本：`ExecutionModelConfig.additional_latency_bars` 增加信号到可撮合之间的 K 线延迟；`market_regime` 为 `normal`、`volatile` 或 `stressed`，后两种状态可通过滑点乘数放大不利滑点。
- 流动性：优先使用 `bid_size` / `ask_size` 作为 L1 深度，并可叠加 `max_volume_participation` 成交量上限。被动限价单通过 `queue_position_fraction` 预留前方队列占用的流动性，作为可重复的价格—时间优先级近似。

该模型对齐了主流交易所的核心订单状态和 TIF/Post-only 语义，但不声称在缺少交易所规则版本及历史 L2/L3 逐笔数据时重建真实队列。回测输出应被视为保守、可复现的执行假设，而不是历史撮合逐笔复刻。

### 回测执行假设与可复现性

`POST /api/v1/backtest` 运行 SMA 双均线回测。必须二选一提供 `klines`（向后兼容的内联 K 线）或 `data_version`（质量合格的目录版本）；使用 `data_version` 时可再传 `start` 和 `end` 过滤时间范围。内联 K 线不能传这两个范围字段，避免声明了未实际使用的范围。

除了 `short_window`、`long_window`、`initial_capital` 与 `position_size_pct` 外，还可传入：

- `fee_rate`：每次成交的费率，默认 `0.001`（0.1%）。
- `slippage_rate`：不利滑点率，默认 `0`；买入价格上调，卖出价格下调。
- `max_volume_participation`：可选，限制单次成交最多占当根 K 线成交量的比例；启用后可能产生部分成交。
- `stop_loss_pct` / `take_profit_pct`：可选的入场价百分比保护阈值。

信号在 K 线收盘后生成，并在**下一根 K 线开盘价**执行，避免以未决策时可见的收盘价成交。止盈和止损使用当根 K 线的 high/low 判断；若同一根同时触发，回测保守地按止损成交。响应包括 `total_fees`、`gross_pnl`、`total_return_pct`、`profit_factor`、`execution_model`、`fill_history`、`trade_history`、`result_hash` 与 `backtest_run_id`。

每次回测会保存策略源码版本、策略参数、数据版本及实际范围、执行模型、风险模型、Python/引擎版本、原始请求、结果和结果哈希。使用版本化数据集的实验可通过 `GET /api/v1/backtests/{run_id}` 审计，并用 `POST /api/v1/backtests/{run_id}/reproduce`（二者均需 API key）复跑并比较结果哈希。

#### 参数网格搜索

`POST /api/v1/backtest/grid-search` 在同一份 K 线、相同初始资金、执行模型与风险模型下，遍历 `short_windows × long_windows` 的全部有效 SMA 组合。窗口值会去重并升序规范化；只保留 `short_window < long_window` 的组合，最多允许 **64** 个有效组合（每个原始窗口列表最多 16 项）。

响应的 `candidates` 按以下稳定规则排序：`total_pnl` 降序、`max_drawdown` 升序、`trades` 降序、短窗口升序、长窗口升序。`best` 包含第一名的完整回测指标、权益曲线和成交明细，候选列表只返回比较所需的紧凑指标，以限制响应体大小。

该端点标记 `search.in_sample_only: true`：它仅用于研究和候选参数筛选，不能视为样本外表现或直接晋级交易。应使用 Walk-forward 验证端点取得严格的样本外证据。版本化数据集的网格实验同样会保存哈希并可通过复现端点验证。

#### Monte Carlo 交易序列风险模拟

`POST /api/v1/backtest/monte-carlo` 先以请求中的固定 SMA 参数运行一次普通回测，再仅对该回测的**已完成交易净盈亏**做有界、固定种子的风险分布诊断。请求沿用普通回测的 `klines` / `data_version` 二选一规则、执行成本和保护参数，并额外支持：

- `simulations`：模拟次数，默认 `500`，范围 `1`–`1000`；
- `seed`：伪随机种子，默认 `42`，用于复现同一诊断；
- `return_jitter_pct`：可选的单笔净盈亏扰动上限，默认 `0`；每笔会乘以 `[1 - jitter, 1 + jitter]` 内的均匀随机系数；
- `drawdown_threshold_pct`：路径下探阈值，默认 `0.30`；权益低于或等于 `initial_capital × (1 - threshold)` 的路径会被计为一次阈值触发。

`monte_carlo.sampling` 固定为 `trade_order_permutation_without_replacement`：每次模拟都对原始交易集合做**不放回乱序**，因此在 `return_jitter_pct=0` 时每条路径的期末权益相同，但中途回撤及阈值触发概率可能不同。响应提供期末权益 `p05` / `median` / `p95`、最大回撤的 `p95`、阈值触发概率和期末权益非正的概率，并同时保留 `baseline` 的原始回测指标。

该能力用于研究和风险压力诊断，不修改策略参数、不生成订单、不触发真实或模拟盘下单，也不构成收益、风险或实盘准入承诺。它**不是** Bootstrap：后者会使用有放回抽样，应作为独立研究方法解释。版本化行情实验会保存不可变请求、结果哈希和环境信息，并可通过 `POST /api/v1/backtests/{run_id}/reproduce` 复现。

#### 滚动窗口回测

`POST /api/v1/backtest/rolling` 以固定 SMA 参数对一段行情执行局部时期诊断。请求与普通回测一样，必须二选一提供 `klines` 或经质量检查的 `data_version`，并指定 `window_size`；`step_size` 省略时等于窗口长度。每个**完整**窗口都从同一 `initial_capital` 独立开始，最多生成 **128** 个窗口。

响应的 `rolling` 固定标注 `parameter_mode: "fixed"` 和 `capital_model: "independent_per_window"`；`windows` 给出每个窗口的原始索引及紧凑回测指标，`summary` 给出窗口收益的平均值、标准差、盈利窗口比例和最佳/最差窗口收益。它适合检验一个既定参数在不同局部时间段的表现差异，**不会**在窗口内选参、连接窗口资金、修改策略配置或授权下单。若要取得训练选参后的严格样本外证据，应使用 Walk-forward 端点。

版本化行情的滚动实验同样保存不可变请求、结果哈希和运行环境，可通过 `POST /api/v1/backtests/{run_id}/reproduce` 验证。

#### 多策略组合回测

`POST /api/v1/backtest/portfolio` 接受与单策略回测相同的数据源、成本和保护参数，并额外要求至少两个 `strategies`。每个策略包含 `name`、`short_window`、`long_window` 与 `weight`；名称在请求内必须唯一，所有权重必须为正且**精确合计为 1.0**。

服务端会把 `initial_capital × weight` 隔离分配给每个 SMA 策略，在同一份 K 线和同一执行/风险模型上分别运行，然后逐根 K 线相加生成组合权益曲线。响应顶层为组合指标；`portfolio.strategies` 返回每个策略的权重、分配资金与完整独立结果。该模式不共享现金、不在策略间调仓、也不执行动态再平衡，因此适用于可重复的固定权重归因，而不是资金池级撮合。

与单策略回测相同，版本化数据集上的组合实验会保存不可变请求、结果与哈希，并可用同一个复现端点验证。

### 真实订单：幂等提交与异常对账

`POST /api/v1/order` 和 `POST /api/v1/contracts/order` 都接受可选的 `client_order_id`（4–64 个字符）。未提供时服务端会生成一个并在响应中返回。该值既是本地 SQLite 执行意图账本的主键，也会映射到交易所原生客户端订单字段：Binance 现货/合约使用 `newClientOrderId`，OKX 使用 `clOrdId`，Bitget 合约使用 `clientOid`。

- **安全重试**：使用相同 `client_order_id` 与完全相同的订单参数重复提交时，服务端直接返回已持久化结果，并标记 `idempotent_replay: true`，不会再次调用交易所。
- **冲突保护**：同一 `client_order_id` 对应不同的交易参数时返回 `409`，避免旧请求被误用为另一笔订单。
- **提交结果不明**：交易所网络/响应异常时返回 `502`，其中带有 `client_order_id` 和 `reconciliation_required: true`。此时不要生成新 ID 或盲目重试；应保留该 ID，执行对账并根据交易所实际结果处理。
- **持久恢复**：`submitting`、`submitted`、`unknown`、`pending` 和 `partially_filled` 意图都会持久化。服务重启后会重新装载到订单同步器，并以交易所订单号或客户端订单号匹配挂单。
- **运维查看**：`GET /api/v1/executions/pending`（受 `AUTH_API_KEY` 保护）返回所有未终态执行意图；`POST /api/v1/sync/orders/{exchange}` 会触发一次人工对账，并返回 `unresolved` 数量。

示例：

```json
{
  "exchange": "binance",
  "symbol": "BTCUSDT",
  "side": "buy",
  "order_type": "limit",
  "quantity": 0.001,
  "price": 60000,
  "client_order_id": "web-20260717-btc-buy-001"
}
```


### 无人值守 Bot 多周期分析与受控订单

- `GET /api/v1/bot` 返回不含密钥的 Bot 状态，以及 `autopilot` 的分析开关、交易所、
  标的白名单、轮询周期、趋势阈值与单笔/单日预算。
- `GET /api/v1/bot/autopilot/analysis?exchange=binance_usdm&symbol=BTCUSDT`
  拉取 26 根 1h K 线并丢弃可能仍在形成的最新一根，以 25 根已闭合 K 线，返回 `1h`、`5h`、`24h` 的趋势结果、`decision_id`、
  `confidence` 与 `buy` / `sell` / `observe`。该调用只分析并记录 `autopilot_analysis`
  审计事件，不会下单。
- `POST /api/v1/bot/autopilot/order` 只接受如下受限请求，并要求 Bearer key（如果已设置）：

```json
{
  "exchange": "binance_usdm",
  "symbol": "BTCUSDT",
  "side": "buy",
  "notional": 25,
  "decision_id": "bot-..."
}
```

订单端点不会相信客户端自报的分析结论：它会验证该 `decision_id` 是否对应两轮调度
窗口内的新鲜、同交易所、同标的、同方向审计记录；并依次检查双开关、实盘总开关、
Kill Switch、账户对账、白名单、Bot 单笔与单日预算、全局仓位价值和 `RiskManager`。
任何检查失败返回 4xx 且不会调用交易所。同一根已闭合 K 线的相同共识会映射为固定的
`client_order_id`，即使重启后形成新的 `decision_id` 也只回放原执行意图，不会再次调用
交易所。提交结果不明时沿用执行意图账本，返回 502 和固定的 `client_order_id`，不得用
新的决策 ID 盲目重试。


### 账户与持仓真源对账

后台同步与 `POST /api/v1/sync/positions/{exchange}` 以交易所余额和合约持仓为真源，并将每次结果写入 SQLite 快照。余额变动可能来自充值、划转或资金费，因此只记录为 `warning`；以下持仓差异为 `critical`：

- 交易所存在、本地不存在的仓位（`unexpected_position`）；
- 同一标的仓位数量或方向不一致（`position_quantity_mismatch`）；
- 本地非空、交易所完整持仓响应中缺失的仓位（`missing_position`）。

出现 `critical` 差异后，该交易所会进入**仅限新增风险订单**的本地熔断状态：HTTP 现货/合约新订单和策略实盘执行均返回或记录 `account_reconciliation_blocked`，但撤单、减仓与 `POST /api/v1/positions/close` 不会被该熔断拦截。熔断和差异记录在服务重启后仍会恢复。

运维接口（均受 `AUTH_API_KEY` 保护）：

- `GET /api/v1/reconciliation/status?exchange=...`：查看交易所级熔断状态与未解决差异计数。
- `GET /api/v1/reconciliation/issues?exchange=...&status=open|resolved`：查看持久化差异及人工恢复记录。
- `POST /api/v1/sync/positions/{exchange}`：立即拉取账户/持仓，并在响应中返回本次 `reconciliation` 结果和 `guard` 状态。
- `POST /api/v1/reconciliation/{exchange}/recover`：先连续同步两次，在交易所状态稳定且无新的严重差异时，使用人工说明解除该交易所的新增风险订单限制。

恢复请求示例：

```json
{
  "note": "已核对交易所仓位、余额及外部操作记录，以交易所当前状态为准。"
}
```

如果新订单被拦截，接口返回 `409` 和 `detail.code: "account_reconciliation_blocked"`；请先查看差异、核对交易所实际风险、必要时平仓或撤单，再执行人工恢复。不要通过重启服务来绕过该限制。

### AI 分析安全护栏

`POST /api/v1/ai/analyze` 在 LLM API Key 未配置时会先返回 `decision: "hold"` 与 `error_kind: "api_key_missing"`，不会为了无效请求访问外部行情源。行情获取失败也会转换为 `decision: "hold"` 与 `error_kind: "network"`，避免把上游网络错误暴露为服务端 500。对可执行的 `buy` / `sell` 建议，系统要求同时有正数止损和止盈，并校验其与最新价格的相对关系：做多必须为 `stop_loss < price < take_profit`，做空必须为 `take_profit < price < stop_loss`。不满足时返回 `decision: "hold"` 与 `error_kind: "safety_rejected"`；该结果不会进入自动策略或下单链路。

分析器会先在本地计算 SMA5/SMA20、RSI14、5/20 周期动量、ATR14、量比与 20 周期支撑/阻力，再将这些确定性指标与行情、仓位、风控状态和交易历史一并交给模型做交叉验证。响应除 `decision`、`confidence`、止损止盈外，还包含 `trend`、`volatility`、`summary`、`key_support`、`key_resistance`、`entry_zone`、`position_pct`、多空证据、失效条件、风险收益比和 `technical_indicators`。缓存指纹同时包含行情、技术指标、风控和历史上下文，风险状态变化后不会复用旧建议。

### AI 决策协议、审计与效果评估

AI 分析器使用版本化 `v4` 协议。协议包含 `decision`（`buy` / `sell` / `hold` / `observe`）、`confidence`、`regime`、`reasons`、`risk_factors`、`stop_loss`、`take_profit`、`position_size`、`invalidation_conditions`、`data_timestamp`、`model_version` 与 `prompt_version`。对声明协议版本的输出，服务端会在交易策略路径上执行 JSON Schema 风格的字段/枚举/范围校验；未来时间戳、超限仓位、无效止损止盈和重复建议均会被安全拦截，低置信度的可执行建议会降级为 `observe`。

审计事件保存完整的输入与输出摘要、Provider、模型、耗时、版本及拦截原因：

- `GET /api/v1/ai/decisions?symbol=BTCUSDT&limit=100`：查询历史 AI 决策。
- `GET /api/v1/ai/decisions/{event_id}/replay`：返回决策的不可变输入/输出与已记录结果，用于复盘。
- `POST /api/v1/ai/decisions/{event_id}/outcome`：追加后验结果；请求包含方向收益 `outcome_return_pct`，并可选填 `mfe_pct`、`mae_pct`、`estimated_cost_usd`、`strategy_type` 与观察窗口。原始决策不会被修改。
- `GET /api/v1/ai/insights`：除基础调用统计外，新增命中率、置信度分桶收益、MFE/MAE、AI/规则策略对比、已知成本覆盖率及模型版本表现。后验指标仅基于 outcome 审计事件，未记录结果的决策不会被计入收益统计。

### LLM 策略调用治理

长运行的 LLM 策略在其各自的 `LLMAnalyzer` 实例内使用本地调用治理：成功缓存命中直接复用，不受限流影响；需要真实 Provider 调用时可由 `LLM_MIN_REQUEST_INTERVAL_SECONDS` 设定最短间隔。连续真实 Provider 失败次数达到 `LLM_CIRCUIT_FAILURE_THRESHOLD` 后，策略会在 `LLM_CIRCUIT_COOLDOWN_SECONDS` 冷却期内安全降级为 `hold`，并返回 `error_kind: "circuit_open"`。本地限流使用 `error_kind: "rate_limited"`。这些降级结果会进入 LLM 审计与 `/api/v1/ai/insights` 的 failures 汇总，但不会伪造成真实的 Provider 延迟或 token 指标。单次 `POST /api/v1/ai/analyze` 每次都会创建独立分析器，因此上述熔断状态仅面向持续运行的策略实例。

### AI 运营指标

`GET /api/v1/ai/insights?minutes=1440&limit=2000` 汇总 SQLite 中已持久化的 `llm_decision` 审计事件，返回指定窗口内的请求总数、成功率、失败类型、安全护栏拒绝次数、输入/输出 token、平均/P95 延迟，以及按 provider + model 分组的统计。

- `minutes`：1–43200（最多 30 天），默认 1440（24 小时）
- `limit`：读取的最近审计事件条数，1–5000，默认 2000；窗口内事件超过此上限时，结果只代表最新样本
- `decisions` 仅统计成功的 `buy` / `sell` / `hold`；失败项按 `failures` 分类
- 指标用于运行健康与容量回看，**不**是供应商账单估算；命中 LLM 结果缓存的请求不会产生新的审计事件

示例响应（节选）：

```json
{
  "window_minutes": 1440,
  "calls_total": 42,
  "successful_calls": 39,
  "success_rate": 92.86,
  "safety_rejections": 2,
  "total_tokens": 18640,
  "avg_latency_ms": 876.4,
  "p95_latency_ms": 1420,
  "failures": {"safety_rejected": 2, "timeout": 1},
  "models": [
    {
      "provider": "openai",
      "model": "gpt-4o-mini",
      "calls": 42,
      "total_tokens": 18640,
      "p95_latency_ms": 1420
    }
  ]
}
```

### LLM 信号过滤器

`POST /api/v1/strategies/llm-filter/attach` 会把 LLM 二次确认过滤器挂到实盘流水线。每次过滤前，流水线按信号中的策略周期刷新 ticker 和 K 线，过滤器不会依赖过期的本地行情缓存。行情或 LLM 分析任一步失败都会 fail-closed，信号不会进入风控和交易所下单阶段。

完整 70+ 路由见 [`app/api/server.py`](../app/api/server.py) 或启动服务后访问 `/docs`。

## 错误响应

- `400` 参数错误
- `401` 鉴权失败（仅当 `AUTH_API_KEY` 设置时）
- `403` 实盘关闭时尝试下单
- `404` 资源不存在
- `409` 资源冲突（如重名数据源）
- `422` Pydantic 校验失败
- `423` Kill Switch 触发
- `502` 交易所网络错误
- `500` 未捕获异常

所有错误响应格式：

```json
{
  "detail": "error message"
}
```

部分错误（特别是 502 来自上游）会带 `error_category` 和 `exchange_detail` 字段。

### 策略版本、Walk-Forward 与模拟盘晋级

策略配置会持久化为不可变版本：创建策略、调整运行状态或模式后，只有配置指纹实际变化才会新增版本。可通过 `GET /api/v1/strategies/{name}/versions`（`AUTH_API_KEY`）查看版本、参数和创建原因。

样本外验证使用 `POST /api/v1/strategies/{name}/backtests/walk-forward`（`AUTH_API_KEY`）。请求与普通回测一致，必须二选一提供内联 `klines` 或通过质量检查的 `data_version`（后者可附带 `start` / `end`）；再指定 `train_size`、`test_size`、可选 `step_size` 和最多 24 组互不重复的 SMA 参数候选集。每个训练窗口只在自身历史上选择候选参数，再从零开始执行紧接着的测试窗口；响应及 SQLite 审计记录只聚合测试窗口结果，避免把训练期优化收益伪装成样本外表现。

响应新增 `result.optimization` 审计对象，包含候选数、稳定的训练期排序规则、每个参数对被选择的折数/比例，以及 `parameter_stability_ratio`。该稳定性值仅用于研究诊断，**不是**实盘准入或自动下单授权；端点不会修改策略参数、改变策略模式或启用真实交易。可用 `GET /api/v1/strategies/{name}/backtests` 查看已持久化的验证记录。

```json
{
  "klines": [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}],
  "train_size": 180,
  "test_size": 60,
  "step_size": 60,
  "candidate_parameters": [
    {"short_window": 3, "long_window": 15},
    {"short_window": 5, "long_window": 20}
  ],
  "fee_rate": 0.001,
  "slippage_rate": 0.0005,
  "max_volume_participation": 0.1
}
```

模拟盘晋级是**人工治理流程**，不是实盘开关：

1. `POST /api/v1/strategies/{name}/promotion/evaluate`（`AUTH_API_KEY`）根据持久化的模拟盘平仓成交，结合请求中的最小交易数、胜率、利润因子及累计 PnL 阈值创建审查记录；状态为 `eligible` 或 `insufficient_evidence`。
2. 只有 `eligible` 记录可通过 `POST /api/v1/strategies/{name}/promotion/{review_id}/decision` 由人工批准或拒绝，并写入审批人和说明。
3. 以上两个接口均不会把策略切换到 `live`，不会绕过 `LiveTradingGuard`、Kill Switch 或账户/持仓对账熔断。需要实盘时仍须使用既有策略模式接口，并由全部安全闸门最终拦截或放行。
