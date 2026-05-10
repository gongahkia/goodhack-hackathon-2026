SHELL := /bin/bash

BACKEND_DIR := backend
BACKEND_VENV := $(BACKEND_DIR)/.venv
BACKEND_PY := $(BACKEND_VENV)/bin/python
BACKEND_UVICORN := $(BACKEND_VENV)/bin/uvicorn
BACKEND_PYTEST := $(BACKEND_VENV)/bin/pytest
FRONTEND_DIR := frontend

.PHONY: help install install-backend install-frontend backend frontend dev fresh-dev stop-dev test test-backend build-frontend live-external-e2e robustness-loop clean

help:
	@echo "Caregiver Companion commands"
	@echo ""
	@echo "  make install           Install backend and frontend dependencies"
	@echo "  make dev               Run backend and frontend"
	@echo "  make fresh-dev         Stop existing dev servers, then run both"
	@echo "  make stop-dev          Stop listeners on :8000 and :5173"
	@echo "  make backend           Run FastAPI on http://127.0.0.1:8000"
	@echo "  make frontend          Run Vite on http://127.0.0.1:5173"
	@echo "  make test              Run backend tests"
	@echo "  make build-frontend    Build frontend"
	@echo "  make live-external-e2e Run opt-in live external-provider E2E"
	@echo "  make robustness-loop  Run bounded frontend-readiness robustness checks"
	@echo "  make clean             Remove local build/cache artifacts"

install: install-backend install-frontend

install-backend:
	@command -v uv >/dev/null || (echo "uv is required for backend install. Install from https://docs.astral.sh/uv/" && exit 1)
	cd $(BACKEND_DIR) && uv venv --clear --python 3.12 .venv && uv pip install -r requirements.txt

install-frontend:
	cd $(FRONTEND_DIR) && npm install

backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	@if lsof -tiTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "frontend already running on http://127.0.0.1:5173"; \
	else \
		cd $(FRONTEND_DIR) && npm run dev -- --host 127.0.0.1 --port 5173 --strictPort; \
	fi

dev:
	@set -e; \
	$(MAKE) backend & backend_pid=$$!; \
	$(MAKE) frontend & frontend_pid=$$!; \
	trap 'kill $$backend_pid $$frontend_pid 2>/dev/null || true' INT TERM EXIT; \
	wait $$backend_pid $$frontend_pid

fresh-dev: stop-dev dev

stop-dev:
	@pids=$$(lsof -tiTCP:8000 -sTCP:LISTEN 2>/dev/null; lsof -tiTCP:5173 -sTCP:LISTEN 2>/dev/null); \
	if [ -n "$$pids" ]; then \
		echo "$$pids" | xargs kill; \
		echo "stopped dev listeners on :8000/:5173"; \
	else \
		echo "no dev listeners on :8000/:5173"; \
	fi

test: test-backend

test-backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && pytest -q

build-frontend:
	cd $(FRONTEND_DIR) && npm run build

live-external-e2e:
	cd $(BACKEND_DIR) && . .venv/bin/activate && RUN_LIVE_EXTERNAL_E2E=1 pytest tests/test_live_integrations.py::test_live_external_provider_full_api_e2e -q -s

robustness-loop:
	cd $(BACKEND_DIR) && . .venv/bin/activate && python scripts/ralph_loop.py --max-iterations 1

clean:
	rm -rf $(BACKEND_DIR)/.pytest_cache
	rm -rf $(FRONTEND_DIR)/dist
	find $(BACKEND_DIR) -type d -name __pycache__ -prune -exec rm -rf {} +
