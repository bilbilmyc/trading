# Single entry point for the most common dev / CI tasks.
#
# Conventions:
#   - make <target>            : print the recipe + run it
#   - each target self-documents via ## comment
#   - keep targets idempotent (safe to re-run)
#   - never `rm` user data; SQLite file lives under data/ and is gitignored
#
# Note: Make targets use a POSIX shell. On Windows, run them from WSL or Git
# Bash; the README also contains direct PowerShell-friendly commands.

.PHONY: help install dev test test-frontend test-all lint typecheck format ci clean build smoke docker-build docker-up docker-down docker-dev docker-dev-down

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install locked backend (uv) + frontend (pnpm) dependencies
	uv sync --all-extras --dev --frozen
	cd frontend && pnpm install --frozen-lockfile
	@echo "✓ install complete. next: cp .env.example .env (then edit values)"

dev: ## Run FastAPI on :8000 + Vite dev server on :5180 in parallel
	@echo "→ starting API on :8000 + Vite on :5180 (Ctrl-C to stop)"
	@trap 'kill 0' SIGINT; \
	  uv run python main.py api --host 127.0.0.1 --port 8000 & \
	  cd frontend && pnpm dev & \
	  wait

test: ## Backend pytest (no coverage, fast)
	uv run pytest tests/ -q --no-cov

test-frontend: ## Frontend vitest (single run)
	cd frontend && pnpm test:run

test-all: ## Backend + frontend tests
	$(MAKE) test
	$(MAKE) test-frontend

lint: ## ruff (backend) + tsc --noEmit (frontend)
	uv run ruff check app/ config/
	cd frontend && pnpm typecheck

typecheck: ## tsc strict (frontend only)
	cd frontend && pnpm typecheck

format: ## ruff --fix (backend) + prettier-style autofix is a no-op (we hand-write CSS)
	uv run ruff check --fix app/ config/

ci: ## Full local gate: lint + backend tests (coverage) + frontend checks + build + smoke
	$(MAKE) lint
	uv run pytest tests/ --cov=app --cov-report=term --cov-fail-under=60
	$(MAKE) test-frontend
	cd frontend && pnpm build
	$(MAKE) smoke

smoke: ## Verify backend imports used by the API image entrypoint
	uv run python -c "import app.api.server; import app.engine.live_order_pipeline; print('imports OK')"

build: ## Production frontend build (frontend → dist/)
	cd frontend && pnpm build

docker-build: ## Build the production image locally
	docker compose build api

docker-up: ## Build and start production stack in the background (:8000)
	docker compose up --build -d

docker-down: ## Stop production stack; preserve the named SQLite volume
	docker compose down

docker-dev: ## Start API reload + Vite HMR stack (:8000 + :5180)
	docker compose -f docker-compose.dev.yml up --build

docker-dev-down: ## Stop the development Compose stack
	docker compose -f docker-compose.dev.yml down

clean: ## Remove caches (.pytest_cache, .mypy_cache, .ruff_cache, dist, node_modules/.vite)
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
	rm -rf frontend/dist frontend/node_modules/.vite frontend/.tsbuildinfo
	@echo "✓ caches cleared. run 'make install' to restore."
