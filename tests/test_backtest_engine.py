from __future__ import annotations

import math

import pandas as pd
import pytest

from derivlab.backtest_engine import run_backtest
from derivlab.config import ASSET_SYMBOLS, STRATEGY_META, STRATEGY_ORDER, suggested_capital
from derivlab.data_fetcher import synthetic_frame
from derivlab.strategies import StrategyConfig


def config_for(service, symbol, strategy, capital=None, lookback=1, **overrides):
    market = service.load(symbol)
    meta = STRATEGY_META[strategy]
    values = dict(
        strategy_key=strategy,
        asset_symbol=symbol,
        capital=float(capital or suggested_capital(market.latest_close, market.asset.multiplier)),
        tenor_days=meta["default_tenor"],
        strike_offset_pct=meta["default_offset"],
        basis_pct=5.0,
        wing_width_pct=5.0,
        lookback_years=lookback,
    )
    values.update(overrides)
    return StrategyConfig(**values), market


@pytest.mark.parametrize("symbol", ASSET_SYMBOLS)
@pytest.mark.parametrize("strategy", STRATEGY_ORDER)
def test_backtest_matrix(symbol, strategy, service):
    config, market = config_for(service, symbol, strategy)
    result = run_backtest(symbol, market.frame, config, lookback_years=1)

    assert result.engine == "backtrader"
    assert result.contracts > 0
    assert len(result.nav) >= 200
    assert len(result.trades) > 0
    assert len(result.cycles) > 0
    assert result.start < result.end
    assert result.nav.index.is_monotonic_increasing
    assert result.nav.index.is_unique
    assert result.nav["nav"].notna().all()
    assert result.nav["nav"].map(math.isfinite).all()
    assert math.isfinite(result.final_nav)
    assert math.isfinite(result.summary.total_return)
    assert math.isfinite(result.summary.max_drawdown)
    assert 0 <= result.summary.max_drawdown <= 1
    assert -99 <= result.summary.sharpe <= 99
    assert -99 <= result.summary.sortino <= 99
    assert 0 <= result.summary.win_rate <= 1
    assert result.benchmark.iloc[-1] > 0
    assert result.initial_plan.contracts >= result.contracts


def test_lookback_windows(service):
    config, market = config_for(service, "AAPL", "covered_call", lookback=5)
    one = run_backtest("AAPL", market.frame, config, lookback_years=1)
    three = run_backtest("AAPL", market.frame, config, lookback_years=3)
    five = run_backtest("AAPL", market.frame, config, lookback_years=5)
    assert len(one.nav) < len(three.nav) < len(five.nav)
    assert one.start > three.start > five.start


def test_zero_lot_backtest_is_safe(service):
    config, market = config_for(service, "AAPL", "covered_call", capital=1_000)
    result = run_backtest("AAPL", market.frame, config, lookback_years=1)
    assert result.contracts == 0
    assert result.trades.empty
    assert result.nav["nav"].nunique() == 1
    assert result.summary.total_return == 0
    assert result.summary.max_drawdown == 0


def test_extreme_parameters_do_not_break_engine(service):
    for strategy in STRATEGY_ORDER:
        config, market = config_for(
            service,
            "AAPL",
            strategy,
            capital=5_000_000,
            iv_multiplier=2.0,
            risk_free=0.10,
            fee_bps=50.0,
            basis_pct=15.0,
            wing_width_pct=10.0,
            strike_offset_pct=20.0,
            tenor_days=90,
        )
        result = run_backtest("AAPL", market.frame, config, lookback_years=1)
        assert result.engine == "backtrader"
        assert result.nav["nav"].map(math.isfinite).all()
        assert math.isfinite(result.final_nav)


def test_synthetic_fallback_frame_runs(service):
    asset = service.load("AAPL").asset
    frame = synthetic_frame(asset, years=1, end=pd.Timestamp("2025-01-01"))
    config, _ = config_for(service, "AAPL", "cash_secured_put")
    result = run_backtest("AAPL", frame, config, lookback_years=1)
    assert len(result.nav) > 200
    assert math.isfinite(result.final_nav)


def test_short_history_raises_value_error(service):
    config, market = config_for(service, "AAPL", "covered_call")
    with pytest.raises(ValueError):
        run_backtest("AAPL", market.frame.tail(10), config, lookback_years=1)


def test_unknown_strategy_raises(service):
    config, market = config_for(service, "AAPL", "covered_call")
    bad = StrategyConfig(
        strategy_key="not_a_strategy",
        asset_symbol="AAPL",
        capital=config.capital,
    )
    with pytest.raises(ValueError):
        run_backtest("AAPL", market.frame, bad, lookback_years=1)
