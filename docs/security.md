# 安全指南

## 默认安全姿态

**默认情况下（个人本地使用）：**

- 监听 `0.0.0.0:8000`（如需仅本地，改为 `127.0.0.1`）
- 无 API 鉴权（任何能访问 8000 端口的人都能调所有端点）
- CORS 允许 `http://localhost:5173` 和 `http://127.0.0.1:5173`
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

`server.py` 硬编码：

```python
allow_origins=[
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]
```

仅放本地前端域名。生产部署若用 nginx 反代，CORS 配置可保持默认（nginx 在外层去掉 CORS 头）。

## 数据库安全

SQLite 文件位置 `data/trading.sqlite3`：

- WAL 模式 + 外键开启（[`app/core/sqlite_store.py:40-41`](../app/core/sqlite_store.py)）
- 单连接 + RLock（高并发写串行——单机够用，不适合横向扩展）
- 所有查询用参数化占位符（`?`），无 SQL 注入

**未加密存储**：交易所 API key 在 `.env`（明文）、SQLite 存交易历史（明文）。如果设备被入侵，攻击者能读到历史交易和当前 key 引用（虽然 key 不在 SQLite 里）。

## 风控层（LLM 决策的安全网）

LLM 决策经过 5 重保险：

1. **Symbol 白名单**（`.env` 配置 `LLM_ALLOWED_SYMBOLS`）—— 阻止 typo 错传 symbol
2. **System message 硬约束**（always on）—— 5 条风控规则写死在 prompt
3. **风险状态注入**（每次重新拉取）—— LLM 看到 Kill Switch / 日亏 / 回撤，违反时降级 hold
4. **RiskManager 6 端口**—— 滑动窗口、日亏、回撤、per-symbol 限仓
5. **LiveTradingGuard 全局闸门**—— `ENABLE_LIVE_TRADING=false` 时整个实盘路径被拦

详见 [`docs/llm-architecture.svg`](llm-architecture.svg) 和 [`docs/STATUS.md`](STATUS.md)。
