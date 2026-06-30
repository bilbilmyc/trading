# syntax=docker/dockerfile:1.7

FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY config ./config
COPY main.py README.md ./
COPY --from=frontend-builder /app/frontend/dist ./static

RUN uv sync --frozen --no-dev

# Put the synced venv on PATH so the CMD can just say `python …` without
# going through `uv run`. Going through `uv run` at container start would
# trigger a fresh `uv sync` against the lockfile, which (without --no-dev)
# pulls the dev group back in and produces the "Downloading ruff/mypy/…"
# lines the user saw in the runtime logs.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["python", "main.py", "api", "--host", "0.0.0.0", "--port", "8000"]
