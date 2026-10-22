"""Shared fixtures. Tests are fully offline and use the bundled seed data."""

from __future__ import annotations

import pandas as pd
import pytest

from derivlab.config import suggested_capital
from derivlab.data_fetcher import MarketDataService
from derivlab.strategies import StrategyConfig


@pytest.fixture(scope="session")
def service() -> MarketDataService:
    return MarketDataService()


@pytest.fixture(scope="session")
def aapl(service: MarketDataService):
    return service.load("AAPL")


@pytest.fixture()
def aapl_config(aapl) -> StrategyConfig:
    return StrategyConfig(
        strategy_key="covered_call",
        asset_symbol="AAPL",
        capital=float(suggested_capital(aapl.latest_close, aapl.asset.multiplier)),
        tenor_days=30,
        strike_offset_pct=5.0,
        lookback_years=1,
    )


@pytest.fixture()
def sample_frame() -> pd.DataFrame:
    index = pd.bdate_range("2023-01-02", periods=400, name="Date")
    close = pd.Series(range(100, 500), index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close * 0.998,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1_000_000.0,
        },
        index=index,
    )
