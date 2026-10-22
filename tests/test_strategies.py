from __future__ import annotations

import math

import pytest

from derivlab.config import ASSET_SYMBOLS, STRATEGY_META, STRATEGY_ORDER, suggested_capital
from derivlab.strategies import (
    StrategyConfig,
    build_position_plan,
    greeks_table,
    payoff_curve,
    size_position,
)


def build_config(symbol, strategy, service, contracts=None):
    market = service.load(symbol)
    asset = market.asset
    return StrategyConfig(
        strategy_key=strategy,
        asset_symbol=symbol,
        capital=float(suggested_capital(market.latest_close, asset.multiplier)),
        tenor_days=STRATEGY_META[strategy]["default_tenor"],
        strike_offset_pct=STRATEGY_META[strategy]["default_offset"],
        basis_pct=5.0,
        wing_width_pct=5.0,
        contracts=contracts,
    ), market


@pytest.mark.parametrize("symbol", ASSET_SYMBOLS)
@pytest.mark.parametrize("strategy", STRATEGY_ORDER)
def test_plan_is_finite_for_every_asset_and_strategy(symbol, strategy, service):
    config, market = build_config(symbol, strategy, service)
    plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
    assert plan.contracts > 0
    assert plan.spot > 0
    assert plan.iv > 0
    assert math.isfinite(plan.net_premium)
    assert math.isfinite(plan.max_loss)
    assert plan.max_profit is None or math.isfinite(plan.max_profit)
    assert math.isfinite(plan.capital_used)
    assert all(math.isfinite(leg.premium) for leg in plan.legs)
    curve = payoff_curve(plan)
    assert len(curve) >= 25
    assert curve["pnl"].map(math.isfinite).all()


def test_premium_signs(service):
    market = service.load("AAPL")
    spot, hv = market.latest_close, market.latest_hv()
    for strategy, expected_sign in [
        ("covered_call", 1),
        ("cash_secured_put", 1),
        ("iron_condor", 1),
        ("long_straddle", -1),
    ]:
        config, _ = build_config("AAPL", strategy, service)
        plan = build_position_plan(config, spot, hv, market.end)
        assert plan.net_premium * expected_sign > 0, strategy
    config, _ = build_config("AAPL", "basis_trade", service)
    plan = build_position_plan(config, spot, hv, market.end)
    assert plan.net_premium == 0
    assert plan.futures_entry is not None
    assert plan.futures_entry > spot


def test_basis_payoff_is_flat(service):
    config, market = build_config("AAPL", "basis_trade", service)
    plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
    curve = payoff_curve(plan)
    assert curve["pnl"].max() - curve["pnl"].min() < 1e-6


def test_covered_call_payoff_limits(service):
    config, market = build_config("AAPL", "covered_call", service)
    plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
    curve = payoff_curve(plan, low_mult=0.0)
    assert curve["pnl"].max() == pytest.approx(plan.max_profit, rel=1e-6, abs=1e-6)
    assert curve["pnl"].min() == pytest.approx(plan.max_loss, rel=1e-6, abs=1e-6)
    assert len(plan.breakevens) == 1


def test_condor_payoff_limits(service):
    config, market = build_config("AAPL", "iron_condor", service)
    plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
    curve = payoff_curve(plan)
    assert curve["pnl"].max() == pytest.approx(plan.max_profit, rel=1e-6, abs=1e-6)
    assert curve["pnl"].min() == pytest.approx(plan.max_loss, rel=1e-6, abs=1e-6)
    assert len(plan.breakevens) == 2


def test_straddle_has_unlimited_profit(service):
    config, market = build_config("AAPL", "long_straddle", service)
    plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
    assert plan.max_profit is None
    assert plan.max_loss < 0
    assert len(plan.breakevens) == 2


def test_low_capital_returns_zero_lots_without_error(service):
    market = service.load("AAPL")
    config = StrategyConfig(
        strategy_key="covered_call",
        asset_symbol="AAPL",
        capital=1_000,
        tenor_days=30,
        strike_offset_pct=5.0,
    )
    plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
    assert plan.contracts == 0
    assert plan.warnings
    assert plan.max_loss == 0
    assert payoff_curve(plan)["pnl"].abs().max() < 1e-9


def test_explicit_contracts_are_respected(service):
    market = service.load("AAPL")
    config = StrategyConfig(
        strategy_key="covered_call",
        asset_symbol="AAPL",
        capital=1_000_000,
        contracts=3,
    )
    plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
    assert plan.contracts == 3
    assert plan.units == 300


def test_size_position_boundaries():
    assert size_position("covered_call", 0, 100, 100) == 0
    assert size_position("covered_call", 100_000, 100, 100) == 10
    assert size_position("covered_call", 10_000, 100, 100) == 1
    assert size_position("covered_call", 20_000, 100, 100) == 2


def test_greeks_table_columns(service):
    config, market = build_config("AAPL", "iron_condor", service)
    plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
    table = greeks_table(plan)
    assert {"Leg", "Delta", "Theta / day", "Vega / pt"}.issubset(table.columns)
    assert len(table) >= 4


def test_plan_survives_extreme_parameters(service):
    market = service.load("AAPL")
    for strategy in STRATEGY_ORDER:
        config = StrategyConfig(
            strategy_key=strategy,
            asset_symbol="AAPL",
            capital=5_000_000,
            tenor_days=90,
            strike_offset_pct=20.0,
            iv_multiplier=2.0,
            risk_free=0.10,
            fee_bps=50.0,
            basis_pct=15.0,
            wing_width_pct=10.0,
        )
        plan = build_position_plan(config, market.latest_close, market.latest_hv(), market.end)
        assert plan.contracts >= 0
        assert math.isfinite(plan.net_premium)
        assert math.isfinite(plan.max_loss)
        assert payoff_curve(plan)["pnl"].map(math.isfinite).all()
