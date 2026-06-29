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
| `qt_risk_rejections_total` | counter | `reason` | 风控拒绝数（max_position / daily_loss / max_drawdown） |
| `qt_llm_call_duration_seconds` | histogram | `provider, model, status` | LLM 调用延迟，buckets 0.1–30s |
| `qt_llm_tokens_total` | counter | `provider, model, type` | token 用量（type=prompt/completion） |
| `qt_monitor_alerts_total` | counter | `level, category` | 告警数（已发出到飞书/钉钉/企微） |
| `qt_paper_orders_total` | counter | `side` | 模拟盘成交数 |
| `qt_engine_loop_duration_seconds` | histogram | `loop` | 后台 loop 周期（sync/monitor/signal_runner） |
| `qt_positions_active` | gauge | `exchange` | 当前持仓数 |
| `qt_app_info` | gauge | `version, env` | 静态信息（值恒为 1） |

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

指标通过 `app/engine/metrics.py` 集中定义。其他模块这样用：

```python
from app.engine.metrics import ORDERS_TOTAL
ORDERS_TOTAL.labels(status="filled", exchange="binance_usdm", side="buy").inc()
```

```python
from app.engine.metrics import LLM_CALL_DURATION
with LLM_CALL_DURATION.labels(provider="openai", model="gpt-4o-mini", status="ok").time():
    response = await openai_call()
```

`render()` 导出 `(body, content_type)` 给 `/metrics` 端点。

## 当前未自动埋点的位置

下面这些是接下来想埋但还没接的（按价值排）：

1. `app/engine/live_order_pipeline.py` — 6 端口 Pipeline 的每端口耗时
2. `app/engine/strategy_performance.py` — 策略维度的胜率/回撤
3. `app/engine/sqlite_store.py` — SQLite 写入延迟
4. `app/engine/notifier.py` — 已有 webhook 计数但没接 metrics

需要时直接 import + 加 `.inc()` / `.time()` 即可。
