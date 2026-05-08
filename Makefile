SHELL := /bin/bash

BACKEND_DIR := backend
FRONTEND_DIR := frontend
BACKEND_VENV := $(BACKEND_DIR)/.venv
BACKEND_PY := $(BACKEND_VENV)/bin/python
BACKEND_UVICORN := $(BACKEND_VENV)/bin/uvicorn
BACKEND_PYTEST := $(BACKEND_VENV)/bin/pytest

.PHONY: help install install-backend install-frontend backend frontend dev test test-backend build build-frontend rebuild-care-plan clean

help:
	@echo "Caregiver Companion commands"
	@echo ""
	@echo "  make install          Install backend and frontend dependencies"
	@echo "  make backend          Run FastAPI on http://127.0.0.1:8000"
	@echo "  make frontend         Run Next.js on http://127.0.0.1:3000"
	@echo "  make dev              Run backend and frontend together"
	@echo "  make test             Run backend tests"
	@echo "  make build            Build frontend"
	@echo "  make rebuild-care-plan Rebuild local care plan data"
	@echo "  make clean            Remove local build/cache artifacts"

install: install-backend install-frontend

install-backend:
	@command -v uv >/dev/null || (echo "uv is required for backend install. Install from https://docs.astral.sh/uv/" && exit 1)
	cd $(BACKEND_DIR) && uv venv --clear --python 3.12 .venv && uv pip install -r requirements.txt

install-frontend:
	cd $(FRONTEND_DIR) && npm install

backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	cd $(FRONTEND_DIR) && npm run dev -- --hostname 127.0.0.1 --port 3000

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd $(BACKEND_DIR) && . .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) & \
	(cd $(FRONTEND_DIR) && npm run dev -- --hostname 127.0.0.1 --port 3000) & \
	wait

test: test-backend

test-backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && pytest -q

build: build-frontend

build-frontend:
	cd $(FRONTEND_DIR) && npm run build

rebuild-care-plan:
	curl -s -X POST http://127.0.0.1:8000/demo/reset | $(BACKEND_PY) -m json.tool

clean:
	rm -rf $(FRONTEND_DIR)/.next $(BACKEND_DIR)/.pytest_cache
	find $(BACKEND_DIR) -type d -name __pycache__ -prune -exec rm -rf {} +
