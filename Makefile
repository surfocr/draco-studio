.PHONY: install dev backend frontend migrate lint clean help

PYTHON := python
PIP := pip
NPM := npm

help:
	@echo "Draco Dataset Studio v6"
	@echo ""
	@echo "  make install    Install all dependencies (backend + frontend)"
	@echo "  make dev        Start backend + frontend in parallel"
	@echo "  make backend    Start backend only (uvicorn)"
	@echo "  make frontend   Start frontend only (vite)"
	@echo "  make migrate    Run Alembic migrations"
	@echo "  make lint       Run linters"
	@echo "  make clean      Remove caches and build artifacts"

install:
	$(PIP) install -r backend/requirements.txt
	cd frontend && $(NPM) install

migrate:
	cd backend && alembic upgrade head

backend:
	cd backend && uvicorn main:app --reload --host 127.0.0.1 --port 18082

frontend:
	cd frontend && $(NPM) run dev

dev:
	@echo "Starting Draco Studio..."
	@$(MAKE) -j2 backend frontend

lint:
	cd backend && python -m ruff check . && python -m mypy . --ignore-missing-imports
	cd frontend && npm run build -- --noEmit 2>/dev/null || true

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/dist frontend/node_modules/.vite
	rm -rf backend/.ruff_cache
