from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from derivlab.metrics import (
    cagr,
    drawdown_series,
    max_drawdown,
    score_game,
    sharpe_ratio,
    sortino_ratio,
    summarize,
    total_return,
    win_rate,
)


def test_drawdown_and_returns():
    nav = pd.Series([100, 120, 90, 110, 80, 130], dtype=float)
    assert total_return(nav) == pytest.approx(0.30)
    assert max_drawdown(nav) == pytest.approx(1 / 3)
    assert (drawdown_series(nav) <= 0).all()
    assert cagr(nav, periods=252) > 0


def test_empty_and_flat_series_are_safe():
    empty = pd.Series(dtype=float)
    assert total_return(empty) == 0
    assert max_drawdown(empty) == 0
    assert sharpe_ratio(empty) == 0
    assert sortino_ratio(empty) == 0
    assert win_rate(None) == 0
    flat = pd.Series([100.0] * 50)
    assert total_return(flat) == 0
    assert sharpe_ratio(flat) == 0
    assert sortino_ratio(flat) == 0


def test_sharpe_and_sortino_are_bounded():
    returns = pd.Series(np.linspace(-0.01, 0.011, 252))
    sharpe = sharpe_ratio(returns)
    sortino = sortino_ratio(returns)
    assert np.isfinite(sharpe) and abs(sharpe) <= 99
    assert np.isfinite(sortino) and abs(sortino) <= 99


def test_summary_shape():
    nav = pd.Series(np.linspace(100, 150, 260))
    summary = summarize(nav, [5, -2, 3], 1_000, 100_000)
    assert summary.total_return > 0
    assert summary.win_rate == 2 / 3
    assert summary.premium_yield == 0.01
    assert 0 <= summary.max_drawdown <= 1


def test_score_badges():
    good = score_game(0.15, 0.03, 0.03, strategy_key="covered_call", reason="period_end")
    assert 0 <= good.score <= 100
    assert good.badge in {
        "Yield Generator",
        "Prudent Hedger",
        "Volatility Architect",
        "Basis Mechanic",
        "Steady Operator",
        "Risk Apprentice",
        "Liquidated Speculator",
    }
    bad = score_game(-0.20, 0.30, 0.0, strategy_key="covered_call", reason="liquidated", liquidated=True)
    assert bad.badge == "Liquidated Speculator"
    assert bad.score < good.score
    assigned = score_game(0.0, 0.05, 0.01, strategy_key="cash_secured_put", reason="assigned", assigned=True)
    assert 0 <= assigned.score <= 100
