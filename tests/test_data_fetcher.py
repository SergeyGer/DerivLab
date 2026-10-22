from __future__ import annotations

import json

import pandas as pd
import pytest

from derivlab.config import ASSETS, MANIFEST_NAME
from derivlab.data_fetcher import (
    MarketDataService,
    _normalize_frame,
    compute_hv_series,
    save_frame,
    synthetic_frame,
)


def test_normalize_multiindex_yfinance_frame():
    index = pd.bdate_range("2024-01-01", periods=5, name="Date")
    columns = pd.MultiIndex.from_product(
        [["Close", "High", "Low", "Open", "Volume"], ["AAPL"]],
        names=["Price", "Ticker"],
    )
    raw = pd.DataFrame(
        [
            [100, 102, 99, 101, 1_000],
            [101, 103, 100, 102, 1_100],
            [102, 104, 101, 103, 1_200],
            [103, 105, 102, 104, 1_300],
            [104, 106, 103, 105, 1_400],
        ],
        index=index,
        columns=columns,
    )
    clean = _normalize_frame(raw)
    assert list(clean.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert clean.index.tz is None
    assert clean["Close"].iloc[-1] == 104
    assert (clean["High"] >= clean["Close"]).all()
    assert (clean["Low"] <= clean["Close"]).all()


def test_short_frame_is_rejected():
    raw = pd.DataFrame(
        {"Open": [1, 2], "High": [1, 2], "Low": [1, 2], "Close": [1, 2], "Volume": [1, 2]},
        index=pd.bdate_range("2024-01-01", periods=2),
    )
    with pytest.raises(ValueError):
        _normalize_frame(raw)


def test_synthetic_fallback_is_deterministic():
    first = synthetic_frame(ASSETS["AAPL"], years=2, end=pd.Timestamp("2025-01-01"))
    second = synthetic_frame(ASSETS["AAPL"], years=2, end=pd.Timestamp("2025-01-01"))
    pd.testing.assert_frame_equal(first, second)
    assert len(first) >= 500
    assert (first["High"] >= first["Close"]).all()


def test_hv_series_and_latest(service):
    market = service.load("AAPL")
    hv = compute_hv_series(market.frame["Close"])
    assert len(hv) == len(market.frame)
    assert hv.dropna().iloc[-1] > 0
    assert market.latest_hv() > 0


def test_cache_preferred_on_tie_and_seed_fallback(tmp_path, sample_frame):
    cache_dir = tmp_path / "cache"
    seed_dir = tmp_path / "seed"
    service = MarketDataService(cache_dir=cache_dir, seed_dir=seed_dir, assets={"AAPL": ASSETS["AAPL"]})
    save_frame(sample_frame, seed_dir / "AAPL.parquet")
    loaded_seed = service.load("AAPL")
    assert loaded_seed.source == "seed"
    assert loaded_seed.rows == len(sample_frame)

    save_frame(sample_frame, cache_dir / "AAPL.parquet")
    loaded_cache = service.load("AAPL")
    assert loaded_cache.source == "cache"

    # A stale cache must not hide a fresher seed.
    stale = sample_frame.iloc[:-50]
    save_frame(stale, cache_dir / "AAPL.parquet")
    fresher = service.load("AAPL")
    assert fresher.source == "seed"
    assert fresher.rows == len(sample_frame)


def test_synthetic_last_resort(tmp_path, sample_frame):
    service = MarketDataService(cache_dir=tmp_path / "c", seed_dir=tmp_path / "s", assets={"AAPL": ASSETS["AAPL"]})
    loaded = service.load("AAPL")
    assert loaded.source == "synthetic"
    assert loaded.rows > 100
    coverage = service.coverage()
    assert coverage.loc[0, "Source"] == "synthetic"


def test_refresh_failure_is_graceful(tmp_path, monkeypatch):
    service = MarketDataService(cache_dir=tmp_path / "c", seed_dir=tmp_path / "s", assets={"AAPL": ASSETS["AAPL"]})

    def boom(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(service, "_download_one", boom)
    result = service.refresh_one("AAPL", retries=1)
    assert result.ok is False
    assert "network down" in result.message
    report = service.refresh(["AAPL"], retries=1, pause=0)
    assert report.failed
    assert "failed" in report.summary()


def test_manifest_and_purge(tmp_path, sample_frame):
    cache_dir = tmp_path / "cache"
    seed_dir = tmp_path / "seed"
    service = MarketDataService(cache_dir=cache_dir, seed_dir=seed_dir, assets={"AAPL": ASSETS["AAPL"]})
    save_frame(sample_frame, cache_dir / "AAPL.parquet")
    save_frame(sample_frame, seed_dir / "AAPL.parquet")
    manifest = service.write_manifest(cache_dir, years=5)
    payload = json.loads(manifest.read_text())
    assert payload["assets"][0]["symbol"] == "AAPL"
    assert (cache_dir / MANIFEST_NAME).exists()

    removed = service.purge_runtime_cache()
    assert removed >= 2
    assert service.load("AAPL").source == "seed"
