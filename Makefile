# Convenience commands for local development and Docker demos.
PYTHON ?= python3.10
VENV ?= .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
STREAMLIT := $(VENV)/bin/streamlit

.PHONY: help install run seed test lint docker-build docker-up docker-down docker-logs docker-seed docker-verify clean

help:
	@echo "DerivLab targets"
	@echo "  make install       Create .venv and install pinned dependencies"
	@echo "  make run           Start the Streamlit terminal on :8501"
	@echo "  make seed          Download 5Y data and promote it to the bundled seed"
	@echo "  make test          Run the full pytest suite"
	@echo "  make lint          Run ruff"
	@echo "  make docker-up     Build and start the compose stack in the background"
	@echo "  make docker-down   Stop and remove the compose stack (volume persists)"
	@echo "  make docker-seed   Refresh the cache inside the Docker volume"
	@echo "  make docker-verify Verify restart policy is 'no'"

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

run:
	$(STREAMLIT) run app.py --server.port 8501

seed:
	$(PY) -m derivlab.data_preprocessor --all --years 5 --output both

test:
	$(PY) -m pytest -q

lint:
	$(VENV)/bin/ruff check .

docker-build:
	docker compose build

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f --tail=100 derivlab-app

docker-seed:
	docker compose --profile seed run --rm derivlab-seed

docker-verify:
	@policy=$$(docker inspect derivlab-app --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || true); \
	echo "derivlab-app restart policy: $${policy:-not running}"; \
	test "$$policy" = "no"

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
