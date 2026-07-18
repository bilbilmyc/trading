# 文档总览

README 负责让新用户在几分钟内跑起来；本目录负责记录部署、接口、安全和运维细节。

## 按场景查找

### 我第一次运行项目

1. 阅读根目录 [`README.md`](../README.md) 的 [快速开始](../README.md#快速开始)。
2. 选择 [Docker 部署](deployment.md#生产部署推荐) 或 [本地开发](deployment.md#本地开发前后端分离)。
3. 使用 [配置模板](../.env.example) 创建 `.env`。

### 我想接入 API 或开发前端

- [HTTP API 参考](api.md)：鉴权、路由分组、错误响应。
- 启动后直接打开 `/docs`：查看当前版本自动生成的 Swagger UI。
- 前端代码位于 [`frontend/src`](../frontend/src)，API client 位于 [`frontend/src/api`](../frontend/src/api)。

### 我想验证策略或开启实盘

- [安全指南](security.md)：实盘开关、风控闸门、密钥和权限。
- [项目状态](STATUS.md)：已实现能力、已知问题和优先级路线图。
- [待办事项](TODO.md)：后续开发阶段、功能清单和当前开工任务。
- 根目录 README 的 [开发工作流](../README.md#开发工作流)：signal → paper → testnet → live。

### 我想部署和排障

- [部署指南](deployment.md)：Docker、热更新、升级、数据卷和健康检查。
- [可观测性](observability.md)：Prometheus、事件流和监控建议。
- [告警配置](alerts.md)：飞书、钉钉、企业微信。
- [Telegram Bot](bot.md)：监控 Bot、日报和静默时段。

## 文档维护约定

- 面向用户的行为变化先更新 README 或对应指南，再更新代码示例。
- 所有命令必须使用当前工具链：后端使用 `uv`，前端默认使用 `pnpm`；只有明确要求时才使用 `bun`。
- 不在文档中写入真实 API key、私有地址或本地数据库内容。
- 配置项以 `.env.example` 为单一参考来源；新增配置时同步更新说明。
- 路由说明以 FastAPI `/docs` 和 `docs/api.md` 为准，避免在 README 复制整份接口列表。
- 重大架构决策记录在 `docs/decisions/`，保留历史记录，不覆盖旧决策。

## 文档结构

```text
docs/
├── README.md             # 本页：文档导航与维护约定
├── deployment.md         # 部署、开发、升级与排障
├── api.md                # HTTP API、鉴权与错误响应
├── security.md           # 安全边界与实盘保护
├── alerts.md             # 告警 provider
├── bot.md                # Telegram 监控 Bot
├── observability.md      # metrics、SSE、监控建议
├── STATUS.md             # 项目审计与路线图
├── TODO.md               # 分阶段待办事项与实施顺序
├── architecture.svg      # 系统架构图
└── llm-architecture.svg  # LLM D→B→A 架构图
```
