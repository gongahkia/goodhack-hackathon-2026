SHELL := /bin/bash

BACKEND_DIR := backend
BACKEND_VENV := $(BACKEND_DIR)/.venv
BACKEND_PY := $(BACKEND_VENV)/bin/python
BACKEND_UVICORN := $(BACKEND_VENV)/bin/uvicorn
BACKEND_PYTEST := $(BACKEND_VENV)/bin/pytest

.PHONY: help install install-backend backend test test-backend robustness-loop clean

help:
	@echo "Caregiver Companion commands"
	@echo ""
	@echo "  make install          Install backend dependencies"
	@echo "  make backend          Run FastAPI on http://127.0.0.1:8000"
	@echo "  make test             Run backend tests"
	@echo "  make robustness-loop  Run bounded frontend-readiness robustness checks"
	@echo "  make clean            Remove local build/cache artifacts"

install: install-backend

install-backend:
	@command -v uv >/dev/null || (echo "uv is required for backend install. Install from https://docs.astral.sh/uv/" && exit 1)
	cd $(BACKEND_DIR) && uv venv --clear --python 3.12 .venv && uv pip install -r requirements.txt

backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

test: test-backend

test-backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && pytest -q

robustness-loop:
	cd $(BACKEND_DIR) && . .venv/bin/activate && python scripts/ralph_loop.py --max-iterations 1

clean:
	rm -rf $(BACKEND_DIR)/.pytest_cache
	find $(BACKEND_DIR) -type d -name __pycache__ -prune -exec rm -rf {} +
