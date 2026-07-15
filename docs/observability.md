# 可观测性（Prometheus / /metrics）

后端在 `/metrics` 暴露 Prometheus 文本格式的指标，配合 Prometheus + Grafana 可以做监控告警和可视化。

## 启用

```bash
# 1. 装 prometheus_client（已加到 pyproject.toml）
uv pip install prometheus_client

# 2. 启动后端
uv run main.py api

# 3. 拉取指标
curl http://localhost:8000/metrics
```

端点无鉴权（`AUTH_API_KEY` 不覆盖 `/metrics`），部署时建议：
- 用 nginx/Caddy 限源 IP
- 或用 reverse proxy auth 套一层

## 暴露的指标

| 名称 | 类型 | 标签 | 含义 |
|------|------|------|------|
| `qt_orders_total` | counter | `exchange, side, status` | 下单数（filled / rejected / failed） |
| `qt_risk_rejections_total` | counter | `reason` | 风控拒绝数（max_position / daily_loss / max_drawdown / signal_filter） |
| `qt_llm_call_duration_seconds` | histogram | `provider, model, status` | LLM 调用延迟，buckets 0.1–30s |
| `qt_llm_tokens_total` | counter | `provider, model, type` | token 用量（type=prompt/completion） |
| `qt_monitor_alerts_total` | counter | `level, category` | 告警数（已发出到飞书/钉钉/企微） |
| `qt_paper_orders_total` | counter | `side` | 模拟盘成交数 |
| `qt_engine_loop_duration_seconds` | histogram | `loop` | 后台 loop 周期（sync/monitor/signal_runner）；含义为 work+sleep 一个完整 cycle |
| `qt_positions_active` | gauge | `exchange` | 当前持仓数 |
| `qt_app_info` | gauge | `version, env` | 静态信息（值恒为 1） |
| `qt_notifier_webhooks_total` | counter | `outcome` | generic webhook 推送（OK / failed / disabled） |
| `qt_alert_dispatcher_total` | counter | `provider, outcome` | 飞书/钉钉/企微 bot webhook 推送（provider=feishu/dingtalk/wecom） |
| `qt_cache_events_total` | counter | `cache, event` | TTLCache 命中 / 漏出（`cache` 是 TTLCache 实例名） |

## Prometheus 抓取配置

```yaml
# prometheus.yml
scrape_configs:
  - job_name: quant-trader
    scrape_interval: 30s
    static_configs:
      - targets: ["localhost:8000"]
    metrics_path: /metrics
```

## Grafana 仪表盘建议

### 关键面板

1. **系统健康**
   - `qt_monitor_alerts_total` rate by `level`（堆叠柱图，5min rate）
   - `qt_risk_rejections_total` rate by `reason`
   - `qt_app_info`（静态 label，查 version/env）

2. **交易流**
   - `rate(qt_orders_total[5m])` by status（success vs rejected 比例）
   - `qt_positions_active` by exchange（活跃持仓数）

3. **LLM 成本 + 性能**
   - `rate(qt_llm_tokens_total[1h])` by type, model（成本趋势）
   - `histogram_quantile(0.95, rate(qt_llm_call_duration_seconds_bucket[5m]))` by provider（P95 延迟）
   - `rate(qt_llm_call_duration_seconds_count[5m])` by status（错误率）

4. **后台健康**
   - `histogram_quantile(0.95, rate(qt_engine_loop_duration_seconds_bucket[1m]))` by loop（loop 是否变慢）

### 推荐告警规则

```yaml
groups:
  - name: quant-trader-critical
    rules:
      - alert: HighRiskRejectionRate
        expr: rate(qt_risk_rejections_total[5m]) > 1
        for: 5m
        annotations:
          summary: "风控拒绝率 > 1/min"

      - alert: LLMErrors
        expr: rate(qt_llm_call_duration_seconds_count{status="error"}[5m]) > 0.5
        for: 5m
        annotations:
          summary: "LLM 错误率 > 0.5/s"

      - alert: EngineLoopSlow
        expr: histogram_quantile(0.95, rate(qt_engine_loop_duration_seconds_bucket[5m])) > 10
        for: 10m
        annotations:
          summary: "后台 loop P95 > 10s"
```

## 集成点

指标通过 `app/engine/metrics.py` 集中定义。所有 hot-path 推荐用
`safe_*` 帮手，避免某次 Prometheus 内部错误打断交易循环：

```python
from app.engine.metrics import ORDERS_TOTAL, safe_inc
safe_inc(ORDERS_TOTAL, status="filled", exchange="binance_usdm", side="buy")
```

`safe_inc` / `safe_observe` / `safe_set` 三个函数都 swallow 所有异常 —
只在确实需要把底层错误传出去时（比如测试里）才用裸
`metric.labels(...).inc()`。

```python
from app.engine.metrics import LLM_CALL_DURATION, safe_observe
start = time.monotonic()
response = await openai_call()
safe_observe(
    LLM_CALL_DURATION,
    time.monotonic() - start,
    provider="openai",
    model="gpt-4o-mini",
    status="ok",
)
```

`render()` 导出 `(body, content_type)` 给 `/metrics` 端点。

## Bot 调用怎么从 access log 中识别

bot 监控盯盘的所有出向 HTTP 调用都带 `X-Bot-Scope` 头（默认
`monitor`，可在 `.env` 改 `BOT_OUTBOUND_SCOPE`）。FastAPI 端的
`ScopeContextMiddleware` 把每条请求的 scope 写到 access log 一行，
示例（loguru INFO 级）：

```
access scope=monitor method=POST path=/api/v1/risk/kill-switch status=200 elapsed_ms=12.4
access scope=web-ui method=GET path=/api/v1/engine/status status=200 elapsed_ms=3.1
access scope=anonymous method=GET path=/api/v1/health status=200 elapsed_ms=0.5
```

事故调查时可以用 `grep "scope=monitor"` 单独拉出所有 bot 触发的端点。

## 当前未自动埋点的位置

下面这些是接下来想埋但还没接的（按价值排）：

1. `app/engine/strategy_performance.py` — 策略维度的胜率/回撤
2. `app/core/sqlite_store.py` — SQLite 写入延迟
3. `app/bot/runner.py` — bot 命令处理耗时（可加 `qt_bot_dispatch_duration_seconds`）

需要时直接 import + 加 `safe_inc()` / `safe_observe()` 即可。

## v0.3.1 监控整改（本次变更）

本次迭代在 v0.3.0 之上：

1. 抽出 `safe_inc` / `safe_observe` / `safe_set` 帮手，去掉 6 处裸
   `try/except ImportError`；hot-path 一律走 safe_*，行为不变。
2. 拆分指标：
   - `qt_notifier_webhooks_total{outcome}` 只服务 `WebhookNotifier`（generic webhook）
   - 新增 `qt_alert_dispatcher_total{provider,outcome}` 服务飞书/钉钉/企微
   - `TTLCache(name="config")` 让 `qt_cache_events_total{cache=...}` 能区分多实例
3. 修三个口径不一致的 loop 计时：
   - `Monitor._check_loop` 把 `time.monotonic()` 移到 `asyncio.sleep` 之后
   - `trader.py` 3 个后台 loop 的 `qt_engine_loop_duration_seconds` 统一为
     "work + sleep" 一个完整 cycle
4. `LiveOrderPipeline`：
   - 缓存 `_exchange_name` 到 `__init__`，不再每次 `execute()` 取
   - 信号过滤器 veto 现在也走 `qt_risk_rejections_total{reason="signal_filter:..."}`

## v0.3.0 监控整改（历史）

上一次迭代把 `/metrics` 端点从"定义了指标但全是 0"变成真实可观测：

**已接通（10 处）**

| 模块 | 指标 | 触发点 |
|------|------|--------|
| `app/engine/live_order_pipeline.py` | `qt_orders_total` | filter/risk/place 异常 -> `failed`；`OK(receipt)` -> `filled` |
| `app/engine/live_order_pipeline.py` | `qt_risk_rejections_total` | `trading_disabled` + risk gate reason |
| `app/engine/monitor.py` | `qt_monitor_alerts_total` | `Monitor._push_alert_obj()` 全量计数 |
| `app/engine/monitor.py` | `qt_engine_loop_duration_seconds{loop="monitor_check"}` | checker round-trip 时延 |
| `app/engine/trader.py` | `qt_engine_loop_duration_seconds{loop=...}` | `signal_runner` / `order_sync` / `position_sync` 每轮用时 |
| `app/engine/position_manager.py` | `qt_positions_active` | `update_position` / `remove_position` 后重算 |
| `app/engine/position_sync.py` | `qt_positions_active` | 每轮 `sync()` 后调 `sync_positions_gauge()` |
| `app/engine/notifier.py` | `qt_notifier_webhooks_total` | disabled / ok / failed 三态 |
| `app/engine/alert_dispatcher.py` | `qt_alert_dispatcher_total` | 飞书/钉钉/企微 webhook 状态码 |
| `app/api/cache.py` | `qt_cache_events_total` | `TTLCache.get_or_set` 命中分支 |
| `app/api/server.py` | `qt_app_info` | FastAPI lifespan 启动时 `set(1)` |

**新增指标（v0.3.0）**

- `qt_notifier_webhooks_total{outcome}` — webhook 推送：`ok` / `failed` / `disabled`
- `qt_cache_events_total{cache, event}` — 缓存 `hit` / `miss`

**v0.3.1 新增**

- `qt_alert_dispatcher_total{provider, outcome}` — 替代 v0.3.0 误用 generic 计数器的部分
