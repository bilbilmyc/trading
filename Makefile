# Single entry point for the most common dev / CI tasks.
#
# Conventions:
#   - make <target>            : print the recipe + run it
#   - each target self-documents via ## comment
#   - keep targets idempotent (safe to re-run)
#   - never `rm` user data; SQLite file lives under data/ and is gitignored

.PHONY: help install dev test test-frontend test-all lint typecheck format ci clean build smoke

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install backend (uv) + frontend (npm) deps
	uv sync --all-extras --dev
	cd frontend && npm install
	@echo "✓ install complete.  next: cp .env.example .env  (edit values)"

dev: ## Run FastAPI on :8000 + Vite dev server on :5173 in parallel
	@echo "→  starting API on :8000  +  Vite on :5173 (Ctrl-C to stop)"
	@trap 'kill 0' SIGINT; \
	  uv run python main.py api --host 127.0.0.1 --port 8000 & \
	  cd frontend && npm run dev & \
	  wait

test: ## Backend pytest (no coverage, fast)
	uv run pytest tests/ -q --no-cov

test-frontend: ## Frontend vitest (single run)
	cd frontend && npm run test:run

test-all: ## Backend + frontend tests
	$(MAKE) test
	$(MAKE) test-frontend

lint: ## ruff (backend) + tsc --noEmit (frontend)
	uv run ruff check app/ config/
	cd frontend && npm run typecheck

typecheck: ## tsc strict (frontend only)
	cd frontend && npm run typecheck

format: ## ruff --fix (backend) + prettier-style autofix is a no-op (we hand-write CSS)
	uv run ruff check --fix app/ config/

ci: ## Full local gate: lint + backend tests (with coverage) + frontend typecheck + tests + build
	$(MAKE) lint
	uv run pytest tests/ --cov=app --cov-report=term --cov-fail-under=60
	$(MAKE) test-frontend
	cd frontend && npm run build

smoke: ## Verify backend imports + server boots
	uv run python -c "import app.api.server; import app.engine.live_order_pipeline; print('imports OK')"

build: ## Production build (frontend → dist/, backend dist not built — pure Python)
	cd frontend && npm run build

clean: ## Remove caches (.pytest_cache, .mypy_cache, .ruff_cache, dist, node_modules/.vite)
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
	rm -rf frontend/dist frontend/node_modules/.vite frontend/.tsbuildinfo
	@echo "✓ caches cleared.  run 'make install' to restore."
