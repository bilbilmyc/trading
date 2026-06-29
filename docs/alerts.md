# 告警外发配置

把 Monitor 产生的告警（`/api/v1/monitor/alerts`）实时推送到飞书/钉钉/企微群机器人。

## 架构

```
Monitor  ──► AlertDispatcher ──► FeishuProvider
                          ├───► DingTalkProvider
                          └───► WeComProvider
```

- 告警是 `Alert` 对象（见 `app/engine/monitor.py`）
- `AlertDispatcher` 挂在 Monitor 的 `on_alert` 回调上
- 每个 provider 独立启用（URL 不配置 = 跳过）
- 错误隔离：单个 provider 失败不影响其他 provider
- 异步发送：调用 `handle_alert` 不阻塞 Monitor 主循环

## 三种群机器人配置

| 平台 | 添加路径 | webhook URL 形式 |
|------|---------|----------------|
| **飞书 (Lark)** | 群 → 设置 → 群机器人 → 添加机器人 → 自定义 webhook | `https://open.feishu.cn/open-apis/bot/v2/hook/<token>` |
| **钉钉** | 群设置 → 智能群助手 → 添加机器人 → 自定义 (勾选"加签"或"自定义关键词") | `https://oapi.dingtalk.com/robot/send?access_token=<token>` |
| **企微 (WeCom)** | 群 → 群机器人 → 添加 | `https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<key>` |

## .env 配置

```bash
# 至少填一个 URL 才能外发。空 = 关闭该 provider
ALERT_FEISHU_WEBHOOK=
ALERT_DINGTALK_WEBHOOK=
ALERT_WECOM_WEBHOOK=

# 过滤阈值：info | warning | error | critical
# 只发送 ≥ 该级别的告警（避免被 info 噪音淹没）
ALERT_MIN_LEVEL=warning

# HTTP 超时（秒）
ALERT_HTTP_TIMEOUT=10
```

全部空时 dispatcher 静默 nothing-to-do，不影响其他功能。

## 消息格式

三个 provider 都用 `text` 类型机器人，content 形如：

```
🚨 [CRITICAL] 风控熔断触发

daily_pnl 已超过 max_daily_loss 阈值（-150.00 USDT / -100.00）

Context: binance_usdm · BTCUSDT
Time: 2026-06-29T17:48:53.422Z
```

不同平台包装字段不同（`msg_type` vs `msgtype`），但用户看到的内容一致。

## 触发流程

1. Monitor 后台循环（默认 30s 一次）跑注册的 health checkers
2. checker 返回非 None 的 `Alert` → `Monitor.push` → 触发所有 `on_alert` 回调
3. AlertDispatcher.handle_alert 过滤 `min_level` 后 fan-out
4. 每个 provider `await send()` 调 webhook

## 测试 / 调试

- 启动日志会显示：`Alert dispatcher wired to N provider(s) (min_level=warning)` — 0 provider 表示没配
- 想测试 webhook 通不通：在 Settings 页加 "测试告警" 按钮（**TODO**），后端调 `AlertDispatcher.send_test()`
- 所有 provider 的 HTTP 失败只 log warning，不抛出（一个 webhook 挂掉不会让其他 webhook 跟着挂）

## 钉钉加签（可选安全加固）

钉钉 webhook 支持加签，URL 变成：
```
https://oapi.dingtalk.com/robot/send?access_token=XXX&sign=YYY&timestamp=ZZZ
```

加签算法见[钉钉官方文档](https://open.dingtalk.com/document/orgapp/customize-robot-access-website-request-rate-limit)。本项目目前不实现加签，**生产环境建议加上**。

## 飞书签名校验

飞书 webhook 也支持加签（`sign` 参数），同样**生产建议加上**。当前实现只走 URL token。
