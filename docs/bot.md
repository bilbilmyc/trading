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
- `app/bot/scheduler.py` — `daily_report_job` 后台调度
- `app/bot/config.py` — `BotConfig` + `bot_config_from_settings`
- `app/api/middleware.py` — `ScopeContextMiddleware` access 日志
- `tests/test_bot.py` — 26 个单测（BotConfig / formatter / dispatch /
  编排器 / 告警订阅 / 包导入完整性）
