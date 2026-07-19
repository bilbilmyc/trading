# 安全指南

## 默认安全姿态

**默认情况下（个人本地使用）：**

- 监听 `0.0.0.0:8000`（如需仅本地，改为 `127.0.0.1`）
- 无 API 鉴权（任何能访问 8000 端口的人都能调所有端点）
- CORS 允许 `http://localhost:5180` 和 `http://127.0.0.1:5180`
- API key 明文存于 `.env`（无 KMS / 加密）
- SQLite 无备份（依赖磁盘）

**这一切都假设是个人 localhost 使用**——不要把 :8000 暴露到公网。

## 启用鉴权

```bash
# 1. 生成随机密钥
AUTH_API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# 2. 写入 .env
echo "AUTH_API_KEY=$AUTH_API_KEY" >> .env

# 3. 前端需要在 localStorage 设置这个 key 并通过 Authorization 头发送
#    （前端集成是后续任务）
```

启用后，12 个状态变更端点要求 `Authorization: Bearer <key>`：

- `POST /api/v1/risk/kill-switch`
- `POST /api/v1/order`, `POST /api/v1/contracts/order`
- `DELETE /api/v1/order/*`, `DELETE /api/v1/orders/*/open`
- `POST /api/v1/contracts/*/leverage`
- `POST /api/v1/paper/reset`
- `POST /api/v1/runner/start`, `POST /api/v1/runner/stop`
- `POST /api/v1/strategies/sma`
- `POST /api/v1/ai/analyze`
- `POST /api/v1/positions/close`

公开端点（health、ticker、klines、portfolio 查询）不需要鉴权。

## API key 管理

- **交易所 key**：存于 `.env`，**只在 Binance/OKX/Bitget testnet 上** 验证
- **LLM key**：同样存 `.env`，建议用最小权限的 key
- **生产部署**：用云 Secrets Manager（AWS Secrets Manager / Vault），不要把 .env commit

`.env` 已被 `.gitignore` 排除，但建议在 README onboarding 里加：

```
⚠️ 永远不要把 .env commit 到 git
```

## 报告漏洞

[SECURITY.md](../SECURITY.md) 给出漏洞报告流程。当前没有公开披露邮箱，建议用 GitHub Security Advisories 报告。

## CORS

`server.py` 仅允许本地 Vite 开发服务器：

```python
allow_origins=[
    "http://127.0.0.1:5180",
    "http://localhost:5180",
]
```

生产镜像以同源方式在 :8000 提供前端和 API，不需要浏览器跨域。若部署到额外的 Web 域名，请在上线前显式将该 HTTPS 来源加入 allowlist；不要使用 `*`。
## 数据库安全

SQLite 文件位置 `data/trading.sqlite3`：

- WAL 模式 + 外键开启（[`app/core/sqlite_store.py:40-41`](../app/core/sqlite_store.py)）
- 单连接 + RLock（高并发写串行——单机够用，不适合横向扩展）
- 所有查询用参数化占位符（`?`），无 SQL 注入

**未加密存储**：交易所 API key 在 `.env`（明文）、SQLite 存交易历史（明文）。如果设备被入侵，攻击者能读到历史交易和当前 key 引用（虽然 key 不在 SQLite 里）。

## 统一预交易风控

所有真实订单入口（现货、合约和受控 Bot）会在创建执行意图、调用交易所前使用同一
`RiskManager` 校验。它不是收益保证，而是阻止明显超限、失控或不应交易的请求。

| 控制项 | 环境变量 | 默认值 | 行为 |
| --- | --- | --- | --- |
| 单笔名义金额 | `MAX_POSITION_VALUE` | `1000` | 数量 × 参考价格不得超过上限。 |
| 全路由单日预算 | `MAX_DAILY_ORDER_NOTIONAL` | `5000` | SQLite 原子预留，跨现货、合约和 Bot 累计；`0` 关闭。网络结果不明确时预算会保守保留，等待对账而不是冒险释放。 |
| 组合总毛暴露 | `MAX_PORTFOLIO_EXPOSURE` | `0` | 根据本地同步持仓按绝对数量 × 市场价聚合；新开/加仓后的投影总额不得超过上限，`0` 关闭。 |
| 单交易对集中度 | `MAX_ASSET_CONCENTRATION_PCT` | `0` | 按标准化交易对聚合跨交易所本地持仓；已有组合时，新开/加仓后的该交易对毛暴露占比不得超过比例，`0` 关闭。 |
| 资产分组集中度 | `MAX_ASSET_GROUP_CONCENTRATION_PCT` + `RISK_ASSET_GROUPS` | `0` + `{}` | 对显式配置的交易对分组聚合本地毛暴露；已有组合时，新开/加仓后的分组占比不得超过比例。每个交易对只能属于一个分组，未映射交易对不猜测分类。 |
| 持仓相关性 | `MAX_POSITION_CORRELATION` | `0` | 对候选标的与本地非零持仓拉取同周期 K 线，仅在至少 `CORRELATION_MIN_SAMPLES` 个对齐收益样本齐全时拦截超过阈值的**正**相关；数据不足或数据源不可用时不猜测、不拦截，并在风险状态中留下证据。 |
| 波动率自适应仓位 | `VOLATILITY_SIZING_ENABLED` + `VOLATILITY_*` | `false` | 启用后从候选下单交易所获取带时间戳的 OHLC K 线，按 ATR/最新收盘价计算波动率；高于 `VOLATILITY_TARGET_ATR_PCT` 时按比例收紧 `MAX_POSITION_VALUE`，最低至 `VOLATILITY_MIN_MULTIPLIER`。低波动绝不放大静态额度；样本不足、异常 K 线或数据源不可用时维持静态上限。 |
| 最大杠杆 | `MAX_LEVERAGE` | `5` | 合约下单的全局杠杆上限；`0` 关闭，生产环境不建议关闭。 |
| 单品种覆盖 | `RISK_SYMBOL_OVERRIDES` | `{}` | JSON 对象，可为某标的收紧 `max_leverage` 或 `max_position_value`。 |
| 禁交易标的 | `RISK_BLOCKED_SYMBOLS` | `[]` | JSON 数组；匹配后拒绝新订单。 |
| 交易时段 | `RISK_TRADING_START_HOUR_UTC` / `RISK_TRADING_END_HOUR_UTC` | `0` / `24` | UTC 半开区间 `[start, end)`；默认全天。 |
| 连续亏损暂停 | `MAX_CONSECUTIVE_LOSSES` | `0` | 达到阈值后拒绝新订单；`0` 关闭。需要将成交后的已实现盈亏持续写入风险状态。 |

风险拦截会返回 HTTP `422`，不会创建待提交的执行意图，也会记录 `risk_order_blocked`

### 交易后风险归因

已确认的真实成交会按 `client_order_id`（策略流水线使用交易所订单号）保存累计成交量与累计均价水位线。系统只处理新增成交量，以实际成交价计算平仓已实现盈亏，并更新连续亏损、当日盈亏；已同步的 USD/USDT/USDC 账户余额会作为回撤基线。重复回调、重复同步或服务重启不会重复记账；提交成功但没有确认成交量/均价的订单不会改变风险状态。

审计事件（含入口、交易所、标的、触发原因和限额上下文）。幂等重放不会重复扣减
单日额度；所有配置示例以 [`.env.example`](../.env.example) 为准。

组合暴露读取的是引擎内 `PositionSync` 与已记录成交维护的**本地持仓快照**：当前待交易标的
会用下单参考价覆盖旧标记价，其他标的使用最近同步价格。它不会把“已提交但尚未成交/对账”的
订单当成持仓，也尚未进行跨进程全局聚合；因此实盘必须保持单一交易引擎的持仓同步和账户对账正常，
并在 testnet 上先以小额度启用。资产分组使用 `RISK_ASSET_GROUPS` 的显式映射，不会把未配置交易对
自动归类；相关性使用候选下单交易所及持仓所属交易所的公开 K 线进行时间对齐，只限制正相关。仍待补充的是待成交订单预留与交易后风险归因。

> **上线建议**：先在 testnet 设定很小的 `MAX_DAILY_ORDER_NOTIONAL`、正数
> `MAX_LEVERAGE` 和明确的标的黑名单；确认审计、对账和 Kill Switch 演练正常后，才逐步调整额度。

## 风控层（LLM 决策的安全网）

LLM 决策经过 5 重保险：

1. **Symbol 白名单**（`.env` 配置 `LLM_ALLOWED_SYMBOLS`）—— 阻止 typo 错传 symbol
2. **System message 硬约束**（always on）—— 5 条风控规则写死在 prompt
3. **风险状态注入**（每次重新拉取）—— LLM 看到 Kill Switch / 日亏 / 回撤，违反时降级 hold
4. **RiskManager 统一预交易闸门**—— 单笔/单日名义金额、日亏、回撤、频率、单品种限制、杠杆、黑名单与交易时段
5. **LiveTradingGuard 全局闸门**—— `ENABLE_LIVE_TRADING=false` 时整个实盘路径被拦

详见 [`docs/llm-architecture.svg`](llm-architecture.svg) 和 [`docs/STATUS.md`](STATUS.md)。
