# Bot 监控盯盘

Telegram 机器人：用 `/status` `/pnl` `/kill` 这类命令遥控本机跑的 Engine，
同时也会把 CRITICAL/ERROR 告警和每日报告主动推到白名单的 chat。

## 启用 5 步走

1. 在 Telegram 里给 [@BotFather](https://t.me/BotFather) 发 `/newbot`，
   拿到 `BOT_TELEGRAM_TOKEN`（形如 `1234567890:AAFxxx...`）。
2. 在你的目标 chat（私聊或群）里给机器人发一条消息，浏览器打开
   `https://api.telegram.org/bot<TOKEN>/getUpdates` 找到
   `message.chat.id`。群 chat id 通常是负数。
3. 在 `.env` 里加：
   ```env
   BOT_ENABLED=true
   BOT_TELEGRAM_TOKEN=1234567890:AAFxxx...
   BOT_ALLOWED_CHAT_IDS=-1001234567890,123456789
   BOT_QUIET_HOURS=22-8          # 可选：跨夜静默
   BOT_MIN_ALERT_LEVEL=warning   # 可选：info|warning|error|critical
   BOT_DAILY_REPORT_HOUR=0
   BOT_DAILY_REPORT_MINUTE=5
   ```
4. （强烈推荐）如果你的 Engine API 启用了 `AUTH_API_KEY`，把
   `BOT_API_KEY` 设成同一个值。bot 复用了同一个 key，所有受保护
   端点（kill switch / strategy control）仍要求这个 token。
5. 启动：
   ```bash
   python main.py bot
   ```

## 命令表

| 命令 | 说明 |
| --- | --- |
| `/help` | 帮助 |
| `/status` | 引擎运行状态 / 持仓数 / 日盈亏 / Kill Switch / 信号运行器 |
| `/pnl` | 模拟盘现金 / 权益 / 已实现 / 未实现 / 总盈亏 |
| `/positions` | 当前持仓（含 uPnL） |
| `/signals` | 最近 5 条信号 |
| `/strategies` | 已注册策略及运行状态 |
| `/risk` | 风控阈值 / 当前回撤 / 下单频率 |
| `/kill` | 查询 kill switch 状态 |
| `/kill on [reason]` | 启用 kill switch（reason 可选，会记入 audit） |
| `/kill off [reason]` | 关闭 kill switch |
| `/ticker SYMBOL` | 查行情（默认 BTCUSDT） |
| `/events` | 最近 8 条审计事件 |
| `/runner` | 信号运行器周期数 / 最近错误 |
| `/start_strategy NAME` | 启用策略 |
| `/stop_strategy NAME` | 停用策略 |

所有 `/kill` / `/start_strategy` / `/stop_strategy` 调用都会附 `X-Bot-Scope: monitor`
头，便于服务器 access 日志区分 bot 调用和前端调用。

## 配置字段

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `bot_enabled` | `false` | 总开关 |
| `bot_telegram_token` | `""` | Telegram Bot API token（必填） |
| `bot_allowed_chat_ids` | `""` | 白名单，CSV，例 `-100123,456789`；空 = 允许所有 |
| `bot_api_base_url` | `http://127.0.0.1:8000` | Engine API 地址 |
| `bot_api_key` | `""` | 空 → 降级到 `auth_api_key` |
| `bot_request_timeout_seconds` | `10` | HTTP 客户端超时 |
| `bot_daily_report_enabled` | `true` | 每日报告开关 |
| `bot_daily_report_hour` | `0` | 报告触发小时（24h） |
| `bot_daily_report_minute` | `5` | 报告触发分钟 |
| `bot_quiet_hours` | `""` | 闭区间，例 `"22-8"` 表示 22:00–次日 08:00 |
| `bot_send_rate_per_second` | `4.0` | Telegram 出向限速 |
| `bot_min_alert_level` | `warning` | 主动推送的最低级别 |
| `bot_alert_fingerprint_cooldown_seconds` | `300` | 相同 (level,category,title) 在窗口内只推一次 |
| `bot_outbound_scope` | `monitor` | 注入到 `X-Bot-Scope` 头，记录到 access 日志 |


## 无人值守多周期分析（1h / 5h / 24h）

从 **2026-07-18** 起，`python main.py bot` 可选地启动受控的无人值守
分析任务。它每轮只读取 **已闭合的 1 小时 K 线**，并分别计算最近 `1h`、`5h`
和 `24h` 的收益率：

- 只有三个窗口都上涨且每段都超过 `bot_autopilot_min_return_pct`，才产生 `buy` 候选；
- 只有三个窗口都下跌且每段都超过该绝对阈值，才产生 `sell` 候选；
- 数据不足、单个窗口波动过小或趋势不一致时一律为 `observe`，**不会下单**。

这是一套可解释的趋势共识/预测信号，不是对未来收益的承诺，也不会把 LLM 的
原始输出直接转换成订单。每次分析（包括 `observe`）都会写入 SQLite 审计事件，
Telegram 只推送严格共识的候选动作，避免按周期刷屏。

### 三层开关与预算

默认只有分析与告警能力。自动实盘订单必须同时满足以下全部条件：

1. `BOT_ENABLED=true` 且 Bot 进程正在运行；
2. `BOT_AUTOPILOT_ENABLED=true`（允许分析任务）；
3. `BOT_AUTOPILOT_LIVE_ORDER_ENABLED=true`（单独允许 Bot 提交订单）；
4. `ENABLE_LIVE_TRADING=true`、全局 Kill Switch 未开启、账户对账没有未解决差异；
5. 标的在 `BOT_AUTOPILOT_SYMBOLS` 白名单，且 1h / 5h / 24h 同向；
6. 请求金额不超过 `BOT_AUTOPILOT_MAX_ORDER_NOTIONAL`、当天累计不超过
   `BOT_AUTOPILOT_MAX_DAILY_NOTIONAL`，并再次通过统一预交易闸门：全局
   `MAX_POSITION_VALUE`、`MAX_DAILY_ORDER_NOTIONAL`、`MAX_LEVERAGE`、单品种限制、
   黑名单、交易时段和 `RiskManager` 其他规则。

提交时服务端还要求 `decision_id` 对应一条新鲜、同交易所、同标的、同方向的已审计
分析记录。同一根已闭合 K 线的相同共识有稳定信号指纹；即使调度器重启后产生新的
`decision_id`，服务端也只会回放既有执行意图，绝不会再次触发下单。网络异常后订单会
进入既有幂等执行意图与对账流程，调度器本轮不会盲目重试。

建议先使用以下**只告警**配置运行至少数日，再在测试网验证订单、撤单与对账流程：

```dotenv
BOT_ENABLED=true
BOT_AUTOPILOT_ENABLED=true
BOT_AUTOPILOT_LIVE_ORDER_ENABLED=false
BOT_AUTOPILOT_EXCHANGE=binance_usdm
BOT_AUTOPILOT_SYMBOLS=BTCUSDT,ETHUSDT
BOT_AUTOPILOT_CYCLE_SECONDS=300
BOT_AUTOPILOT_MIN_RETURN_PCT=0.002
BOT_AUTOPILOT_MAX_ORDER_NOTIONAL=25
BOT_AUTOPILOT_MAX_DAILY_NOTIONAL=100
```

启动方式为两个独立进程（先 API，后 Bot）：

```bash
uv run python main.py api
uv run python main.py bot
```

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `bot_autopilot_enabled` | `false` | 多周期分析总开关；不等于可下单 |
| `bot_autopilot_live_order_enabled` | `false` | Bot 自动实盘下单第二开关 |
| `bot_autopilot_exchange` | `binance_usdm` | 唯一允许的行情/交易所 |
| `bot_autopilot_symbols` | 默认标的 | CSV 白名单；留空只使用 `default_symbol` |
| `bot_autopilot_cycle_seconds` | `300` | 分析轮询间隔，范围 60–3600 秒 |
| `bot_autopilot_min_return_pct` | `0.002` | 每个 1h/5h/24h 窗口的最小绝对趋势阈值（0.2%） |
| `bot_autopilot_max_order_notional` | `25` | 单笔最大名义金额（USDT） |
| `bot_autopilot_max_daily_notional` | `100` | 当日 Bot 专属累计名义金额（USDT）；仍受跨入口 `MAX_DAILY_ORDER_NOTIONAL` 共同限制 |

通用风险配置（如 `MAX_DAILY_ORDER_NOTIONAL`、`MAX_LEVERAGE`、
`RISK_BLOCKED_SYMBOLS`）详见[安全指南](security.md#统一预交易风控)和
[`.env.example`](../.env.example)。


## 静默时段策略

`bot_quiet_hours` 同时影响两类消息：

- **主动告警**：`WARNING` / `INFO` 在静默时段内丢弃；`ERROR` /
  `CRITICAL` 始终绕过——真正炸雷时不能让用户睡过去。
- **每日报表**：静默时段内生成但不立刻发送，留到时段结束后的
  第一次 poll window 推送（避免一觉醒来收到一堆老消息）。

按需命令（用户在 Telegram 里主动发的 `/status` 等）不受静默时段
影响，永远即时回复。

## 主动告警去重

`BotAlertSubscriber` 用 `(level, category, title)` 作为 fingerprint，
在 `bot_alert_fingerprint_cooldown_seconds` 秒内只推一次。这样：

- 同一条连接断线告警不会刷屏；
- 但告警内容真的变了（title 不同）时仍能立刻上报。

## 接入到 API worker

bot 也可以和 FastAPI worker 共享进程，在 `app/api/server.py` 的
`create_app(...)` 末尾加一段：

```python
from app.bot.alerts import BotAlertSubscriber
from app.bot.config import bot_config_from_settings
from app.bot.runner import TradingBot
from app.bot.telegram import TelegramProvider
from app.bot.scheduler import daily_report_job

cfg = bot_config_from_settings(settings)
if cfg.enabled:
    bot = TradingBot(
        cfg,
        TelegramProvider(cfg),
        monitor=state.engine.monitor,
        alert_subscriber=BotAlertSubscriber(cfg, sender=None),  # 用 bot.push_to_all
        schedule_jobs=[daily_report_job],
    )
```

（实际上 `bot.api` 默认走 loopback 8000，跟 FastAPI 同进程时更简单
的方案是 `sender=bot.push_to_all`，这样主动告警/日报都走同一个
provider。生产部署建议 bot 与 API 解耦，分别进程跑。）

## 故障排查

- `Bot is disabled` — `BOT_ENABLED` 没设成 `true`。
- `BOT_TELEGRAM_TOKEN is required but empty` — 同上，但只针对子命令
  `bot`；也能在 `BotConfig.telegram_token` 为空时拒绝 `start()`。
- `chat_id=... not in whitelist` — 把 chat id 加到
  `BOT_ALLOWED_CHAT_IDS`，逗号分隔。
- bot 一直在 poll 但没响应 — `getUpdates` 长轮询时间默认 30s；
  检查上游 NAT / 防火墙是否放行了 30s 以上的闲置连接。
- 告警看不到 — `bot_min_alert_level` 太高（默认 `warning`，设成
  `error` 会过滤掉 drawdown 警告）。

## 相关文件

- `app/bot/runner.py` — 编排器，主循环 + 生命周期
- `app/bot/telegram.py` — Telegram Bot API 长轮询 + 限速
- `app/bot/commands.py` — `/status` `/kill` 等命令 handler + `dispatch()`
- `app/bot/formatter.py` — Engine API JSON → HTML 消息
- `app/bot/alerts.py` — `BotAlertSubscriber` 主动告警订阅
- `app/bot/scheduler.py` — `daily_report_job` 与 `autopilot_job` 后台调度
- `app/bot/autopilot.py` — 可测试的 1h / 5h / 24h 多周期共识分析
- `app/bot/config.py` — `BotConfig` + `bot_config_from_settings`
- `app/api/middleware.py` — `ScopeContextMiddleware` access 日志
- `tests/test_bot.py` — 26 个单测（BotConfig / formatter / dispatch /
  编排器 / 告警订阅 / 包导入完整性）
