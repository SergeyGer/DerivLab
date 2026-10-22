from __future__ import annotations

import math

import pytest

from derivlab.config import GAME_SCENARIOS, STRATEGY_META, STRATEGY_ORDER, suggested_capital
from derivlab.game_mode import (
    GameStartError,
    build_game,
    game_result_payload,
    scenario_choices,
    scenario_frame,
)
from derivlab.strategies import StrategyConfig


def scenario_by_id(scenario_id: str) -> dict:
    return next(item for item in GAME_SCENARIOS if item["id"] == scenario_id)


def make_game(service, strategy="covered_call", scenario_id="rate_shock_2022", capital=None, symbol="AAPL"):
    market = service.load(symbol)
    meta = STRATEGY_META[strategy]
    config = StrategyConfig(
        strategy_key=strategy,
        asset_symbol=symbol,
        capital=float(capital or suggested_capital(market.latest_close, market.asset.multiplier)),
        tenor_days=meta["default_tenor"],
        strike_offset_pct=meta["default_offset"],
        basis_pct=5.0,
        wing_width_pct=5.0,
    )
    return build_game(market, config, scenario_by_id(scenario_id)), market


def advance_until_alert(game, limit=400):
    for _ in range(limit):
        if game.state != "running":
            break
        game.advance()
    return game


def advance_to_finish(game, limit=400):
    for _ in range(limit):
        if game.state == "finished":
            break
        if game.state == "alert":
            game.hold()
        else:
            game.advance()
    return game


def test_scenario_slicing_and_choices(service):
    market = service.load("AAPL")
    choices = scenario_choices(market)
    ids = {choice["id"] for choice in choices}
    assert "rate_shock_2022" in ids
    assert "full_history" in ids
    frame = scenario_frame(market, scenario_by_id("rate_shock_2022"))
    assert len(frame) > 200
    assert frame.index.min().year == 2022
    full = scenario_frame(market, scenario_by_id("full_history"))
    assert len(full) == len(market.frame)


def test_game_starts_and_advances(service):
    game, _ = make_game(service)
    assert game.state == "running"
    assert game.days_elapsed == 1
    assert game.nav() > 0
    game.advance_days(5)
    assert game.days_elapsed == 6
    assert game.nav_series().notna().all()


@pytest.mark.parametrize("strategy", STRATEGY_ORDER)
def test_every_strategy_can_reach_a_decision_or_finish(strategy, service):
    game, _ = make_game(service, strategy=strategy)
    advance_until_alert(game, limit=80)
    assert game.state in {"alert", "finished", "running"}
    if game.state == "alert":
        assert game.active_alert is not None
        assert game.active_alert.title
        game.hold()
        assert game.state == "running"
        assert game.holds == 1


def test_hold_roll_liquidate_paths(service):
    # Hold
    game, _ = make_game(service)
    advance_until_alert(game, limit=80)
    assert game.state == "alert"
    key = game.active_alert.key
    assert game.hold() is True
    assert game.state == "running"
    assert key in game.suppressed
    assert game.holds == 1

    # Roll
    game, _ = make_game(service)
    advance_until_alert(game, limit=80)
    assert game.state == "alert"
    can_roll, _reason = game.can_roll()
    assert can_roll
    assert game.roll() is True
    assert game.rolls == 1
    assert game.state == "running"

    # Liquidate
    game, _ = make_game(service)
    advance_until_alert(game, limit=80)
    assert game.state == "alert"
    assert game.liquidate() is True
    assert game.state == "finished"
    assert game.finish_reason == "liquidated"
    assert game.score_card is not None
    assert 0 <= game.score_card.score <= 100
    payload = game_result_payload(game)
    assert payload["badge"]
    assert math.isfinite(payload["return"])


def test_csp_assignment_or_completion(service):
    game, _ = make_game(service, strategy="cash_secured_put")
    advance_to_finish(game, limit=400)
    assert game.state == "finished"
    assert game.score_card is not None
    assert game.finish_reason in {"assigned", "period_end", "capital_exhausted", "liquidated"}
    assert math.isfinite(game.final_nav)
    assert game.days_elapsed >= 1


def test_covered_call_called_away_or_completion(service):
    game, _ = make_game(service, strategy="covered_call")
    advance_to_finish(game, limit=500)
    assert game.state == "finished"
    assert game.score_card is not None
    assert 0 <= game.score_card.score <= 100


def test_low_capital_raises_friendly_error(service):
    market = service.load("AAPL")
    config = StrategyConfig(
        strategy_key="covered_call",
        asset_symbol="AAPL",
        capital=500,
        tenor_days=30,
        strike_offset_pct=5.0,
    )
    with pytest.raises(GameStartError):
        build_game(market, config, scenario_by_id("rate_shock_2022"))


def test_short_scenario_is_rejected(service):
    market = service.load("AAPL")
    truncated = market.frame.tail(20)
    from derivlab.data_fetcher import MarketData

    short_market = MarketData(asset=market.asset, frame=truncated, source="cache")
    config = StrategyConfig(
        strategy_key="covered_call",
        asset_symbol="AAPL",
        capital=100_000,
        tenor_days=30,
        strike_offset_pct=5.0,
    )
    with pytest.raises(GameStartError):
        build_game(short_market, config, scenario_by_id("full_history"))
