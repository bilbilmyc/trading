# HTTP API 参考

FastAPI 自动生成的 OpenAPI 文档在 `/docs`（Swagger UI）和 `/openapi.json`。

## 鉴权

`/api/v1/*` 端点支持**可选 Bearer token 鉴权**：

- 默认（`AUTH_API_KEY` 留空）：无鉴权，localhost 个人使用场景
- 设置 `AUTH_API_KEY=<secret>` 后：所有状态变更端点要求 `Authorization: Bearer <secret>`
- 12 个危险端点挂上 `require_api_key` 依赖（kill-switch、order、cancel、leverage、paper reset 等）

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
| 风险 | `/api/v1/risk/kill-switch` | 1 | **是** |
| 账户（私有） | `/api/v1/balances/*` | 2 | 否（需配置 key） |
| 下单 | `/api/v1/order`, `/api/v1/contracts/order` | 2 | **是** |
| 撤单 | `DELETE /api/v1/order/*`, `DELETE /api/v1/orders/*/open` | 2 | **是** |
| 引擎 | `/api/v1/engine/*`, `/api/v1/runner/*` | 5 | 部分 |
| 模拟盘 | `/api/v1/paper`, `/api/v1/paper/reset` | 2 | **是**（reset） |
| 策略 | `/api/v1/strategies/*` | 10+ | **是**（写） |
| 信号/事件 | `/api/v1/signals/recent`, `/api/v1/events/recent` | 2 | 否 |
| 风控计算 | `/api/v1/sizing`, `/api/v1/atr-sizing` | 2 | 否 |
| 回测/推荐 | `/api/v1/backtest`, `/api/v1/strategies/suggest` | 2 | 否 |
| 投资组合 | `/api/v1/portfolio/*`, `/api/v1/trade-history` | 3 | 否 |
| AI | `/api/v1/ai/analyze` | 1 | **是** |
| LLM 策略 | `/api/v1/strategies/llm*` | 3 | **是** |
| 监控/同步 | `/api/v1/monitor/*`, `/api/v1/sync/*` | 5 | 否 |
| 数据源 | `/api/v1/sources` | 3 | **是**（写） |
| SSE | `/api/v1/stream/events` | 1 | 否 |
| 平仓 | `/api/v1/positions/close` | 1 | **是** |

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
