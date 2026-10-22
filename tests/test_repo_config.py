"""Guardrails for deployment, data, and repository hygiene."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from derivlab.config import ASSETS
from derivlab.data_fetcher import MarketDataService

ROOT = Path(__file__).resolve().parents[1]


def test_compose_disables_autostart_and_persists_cache():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'restart: "no"' in text
    assert text.count('restart: "no"') >= 2
    assert "unless-stopped" not in text
    assert "restart: always" not in text
    assert "derivlab-cache" in text
    assert 'profiles: ["seed"]' in text
    assert "8501" in text


def test_dockerfile_is_multistage_and_python310():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:${PYTHON_VERSION}-slim AS builder" in text
    assert "AS runtime" in text
    assert "build-essential" in text
    assert "USER app" in text
    assert "EXPOSE 8501" in text
    assert "HEALTHCHECK" in text
    assert "requirements.txt" in text


def test_devcontainer_is_reproducible_and_ports_forwarded():
    payload = json.loads((ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8"))
    assert payload["build"]["dockerfile"] == "Dockerfile"
    assert payload["remoteUser"] == "developer"
    assert 8501 in payload["forwardPorts"]
    assert "postCreateCommand" in payload
    assert payload["shutdownAction"] == "stopContainer"
    assert "${localWorkspaceFolder}" in payload["workspaceMount"]
    assert "restart" not in json.dumps(payload).lower()
    text = (ROOT / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
    assert "/root/" not in text
    assert "/home/" not in text


def test_devcontainer_scripts_are_executable():
    for name in ("post-create.sh", "post-start.sh"):
        path = ROOT / ".devcontainer" / name
        assert path.exists()
        assert path.stat().st_mode & 0o111


def test_requirements_are_pinned():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for package in ("streamlit", "pandas", "numpy", "scipy", "yfinance", "backtrader", "plotly", "pyarrow"):
        assert package in text
    assert "==" in text


def test_seed_bundle_contains_every_asset():
    service = MarketDataService()
    manifest_assets = service.manifest(service.seed_dir).get("assets", [])
    assert len(manifest_assets) == len(ASSETS)
    for symbol in ASSETS:
        market = service.load(symbol)
        assert market.rows > 1_000, symbol
        assert list(market.frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert market.start < market.end


def test_readme_is_present_and_complete():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in (
        "DerivLab",
        "Quick Start",
        "Docker",
        "Dev Container",
        "Hold the Position",
        "not investment advice",
    ):
        assert phrase.lower() in text.lower()
    assert "docs/screenshots" in text


def test_gitignore_keeps_seed_but_not_runtime_cache():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/cache/*" in text
    assert "!data/cache/.gitkeep" in text
    assert "data/seed" not in text


def test_screenshots_exist():
    for name in (
        "strategy-deck.png",
        "backtest-lab.png",
        "hold-position-alert.png",
        "hold-position-debrief.png",
        "data-vault.png",
    ):
        path = ROOT / "docs" / "screenshots" / name
        assert path.exists(), name
        assert path.stat().st_size > 20_000


@pytest.mark.parametrize("name", ["Makefile", "CONTRIBUTING.md", "LICENSE", ".env.example", "requirements-dev.txt"])
def test_repository_files_exist(name):
    assert (ROOT / name).exists()
