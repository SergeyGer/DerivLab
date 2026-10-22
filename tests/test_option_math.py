from __future__ import annotations

import math

import pytest

from derivlab.option_math import (
    black_scholes_metrics,
    bs_greeks,
    bs_price,
    estimate_iv,
    implied_volatility,
    intrinsic_value,
    synthetic_futures_price,
)


def test_put_call_parity_with_dividend_yield():
    spot, strike, years, rate, sigma, q = 100.0, 100.0, 1.0, 0.05, 0.20, 0.02
    call = bs_price("call", spot, strike, years, rate, sigma, q)
    put = bs_price("put", spot, strike, years, rate, sigma, q)
    forward = spot * math.exp(-q * years) - strike * math.exp(-rate * years)
    assert call - put == pytest.approx(forward, abs=1e-9)


def test_known_atm_black_scholes_value():
    call = bs_price("call", 100, 100, 1.0, 0.05, 0.20, 0.0)
    put = bs_price("put", 100, 100, 1.0, 0.05, 0.20, 0.0)
    assert call == pytest.approx(10.4506, abs=1e-3)
    assert put == pytest.approx(5.5735, abs=1e-3)


def test_greeks_have_expected_signs():
    call = bs_greeks("call", 100, 100, 0.5, 0.03, 0.25)
    put = bs_greeks("put", 100, 100, 0.5, 0.03, 0.25)
    assert 0 < call.delta < 1
    assert -1 < put.delta < 0
    assert call.gamma > 0 and put.gamma > 0
    assert call.vega > 0 and put.vega > 0
    assert call.theta < 0 and put.theta < 0


def test_expired_option_returns_intrinsic_value():
    call = black_scholes_metrics("call", 110, 100, 0.0, 0.05, 0.2)
    put = black_scholes_metrics("put", 90, 100, 0.0, 0.05, 0.2)
    assert call.price == 10
    assert put.price == 10
    assert call.time_value == 0
    assert call.greeks.delta == 1
    assert put.greeks.delta == -1


@pytest.mark.parametrize(
    ("kind", "spot", "strike"),
    [("call", 0, 100), ("put", 0, 100), ("call", 100, 0), ("put", 100, 0), ("call", -5, 100)],
)
def test_degenerate_inputs_never_raise(kind, spot, strike):
    metrics = black_scholes_metrics(kind, spot, strike, 0.5, 0.03, 0.2)
    assert math.isfinite(metrics.price)
    assert metrics.price >= 0


def test_zero_volatility_is_finite():
    metrics = black_scholes_metrics("call", 100, 100, 1.0, 0.05, 0.0)
    assert math.isfinite(metrics.price)
    assert metrics.price >= 0


def test_implied_volatility_roundtrip():
    price = bs_price("put", 100, 95, 0.75, 0.04, 0.31, 0.01)
    iv = implied_volatility(price, "put", 100, 95, 0.75, 0.04, 0.01)
    assert iv == pytest.approx(0.31, abs=1e-5)


def test_implied_volatility_returns_none_below_intrinsic():
    assert implied_volatility(0.0, "call", 100, 90, 0.5, 0.03) is None
    assert implied_volatility(-1.0, "put", 100, 90, 0.5, 0.03) is None


def test_iv_estimate_clamps():
    assert estimate_iv(0.0) == 0.05
    assert estimate_iv(10.0) == 2.50
    assert estimate_iv(0.2, 1.5) == pytest.approx(0.30)


def test_intrinsic_values():
    assert intrinsic_value("call", 110, 100) == 10
    assert intrinsic_value("put", 90, 100) == 10
    assert intrinsic_value("call", 90, 100) == 0
    assert intrinsic_value("put", 110, 100) == 0


def test_synthetic_futures_contango():
    future = synthetic_futures_price(100, 1.0, 0.04, 0.0, 0.05)
    assert future == pytest.approx(100 * math.exp(0.09), abs=1e-9)
    assert synthetic_futures_price(100, 0.0, 0.04, 0.0, 0.05) == pytest.approx(100)
    assert synthetic_futures_price(0, 1.0, 0.04) == 0
