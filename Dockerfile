# syntax=docker/dockerfile:1.7

FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependency metadata is copied before application source so BuildKit can
# reuse this layer when only application code changes. `package = false` in
# pyproject.toml means the application itself is not installed as a wheel.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY config ./config
COPY main.py README.md ./
COPY --from=frontend-builder /app/frontend/dist ./static

# The virtual environment is already populated in the cacheable dependency
# layer above. Do not run `uv sync` at container startup: it can re-resolve
# optional groups and makes the runtime depend on package-index availability.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["python", "main.py", "api", "--host", "0.0.0.0", "--port", "8000"]
