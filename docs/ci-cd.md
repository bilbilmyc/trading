# CI/CD 与发布流程

## 工作流总览

| 工作流 | 文件 | 触发 | 结果 |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` | `main` push、面向 `main` 的 PR、手动触发 | 使用锁定依赖执行后端与前端质量门禁 |
| Build and Publish Docker Image | `.github/workflows/docker.yml` | `main` push、面向 `main` 的 PR、手动触发 | 所有 PR 构建镜像；只有 main 发布 GHCR 镜像 |

两个工作流都配置了 `concurrency`：同一分支的较旧运行会在新提交出现时取消，避免浪费 runner 时间。

## CI 质量门禁

后端任务（Python 3.13 + uv）：

1. `uv sync --all-extras --dev --frozen`
2. `uv run ruff check app/ config/`
3. `uv run pytest tests/ --cov=app --cov-fail-under=60`
4. API 入口相关模块 import smoke test

前端任务（Node 22 + pnpm）：

1. `pnpm install --frozen-lockfile`
2. `pnpm typecheck`
3. `pnpm test:run`
4. `pnpm build`

本地复现完整门禁：

```bash
make ci
```

如果没有 POSIX `make`，按上面的命令顺序直接执行即可。

## Docker 构建与发布

Docker 工作流使用 Buildx 和 GitHub Actions cache：

- **Pull request**：构建 `Dockerfile`，但不会登录或推送到 GHCR。
- **Push 到 main**：构建成功后使用 `GITHUB_TOKEN` 登录 GHCR，发布：
  - `ghcr.io/bilbilmyc/trading:latest`
  - `ghcr.io/bilbilmyc/trading:sha-<commit>`
- **手动触发**：只有选择 `main` 分支时才会发布；其他分支只构建验证。

镜像构建同时验证：前端 `pnpm install --frozen-lockfile && pnpm build`、后端 `uv sync --frozen --no-dev --no-install-project`，以及最终 API 运行时镜像的文件布局。

## 发布后验证

```bash
docker pull ghcr.io/bilbilmyc/trading:latest
docker run --rm -d --name quant-trader-check -p 8000:8000 ghcr.io/bilbilmyc/trading:latest
curl --fail http://127.0.0.1:8000/health
docker logs quant-trader-check
docker stop quant-trader-check
```

如本机已有 :8000 服务，请改为未占用端口，例如 `-p 18000:8000` 并访问 `http://127.0.0.1:18000/health`。

## 失败处理

- **uv / pnpm 依赖失败**：确认 lockfile 与 manifest 同步，使用 `uv sync --frozen` / `pnpm install --frozen-lockfile` 本地复现。
- **Docker 构建失败**：运行 `docker compose build api`；检查 `.dockerignore` 没有排除运行时必须的文件。
- **GHCR 推送失败**：确认仓库 Actions 对 `GITHUB_TOKEN` 的 packages 写入权限未被组织策略禁用。
- **覆盖率门槛失败**：为实际行为添加测试，不要仅为抬高数字编写无效测试。
