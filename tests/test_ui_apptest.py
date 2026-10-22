"""End-to-end UI smoke tests using Streamlit's official AppTest harness."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from derivlab.config import STRATEGY_ORDER


def _clean(at: AppTest) -> None:
    assert not at.exception, [str(item.value) for item in at.exception]
    assert not at.error, [item.value for item in at.error]
    body = "\n".join(
        item.value for item in list(at.markdown) + list(at.caption) + list(at.warning)
    )
    assert "unexpected condition" not in body
    assert "Traceback" not in body


def _new_app() -> AppTest:
    at = AppTest.from_file("app.py", default_timeout=180)
    at.run()
    _clean(at)
    return at


def test_strategy_deck_all_cards():
    at = _new_app()
    for strategy in STRATEGY_ORDER:
        at.radio(key="strategy_deck_radio").set_value(strategy).run()
        _clean(at)
        assert at.radio(key="strategy_deck_radio").value == strategy


def test_backtest_all_strategies_and_assets():
    at = _new_app()
    at.radio(key="page_selector").set_value("backtest").run()
    _clean(at)
    assert len(at.get("plotly_chart")) >= 2

    for strategy in STRATEGY_ORDER:
        at.selectbox(key="bt_strategy").set_value(strategy).run()
        _clean(at)
        assert len(at.get("plotly_chart")) >= 2

    for asset in ("MSFT", "SAP.DE", "EURUSD=X", "JPY=X", "^GSPC"):
        at.selectbox(key="bt_asset").set_value(asset).run()
        _clean(at)

    at.selectbox(key="bt_asset").set_value("AAPL").run()
    at.number_input(key="bt_capital_AAPL").set_value(1_000).run()
    _clean(at)
    assert len(at.warning) >= 1
    at.number_input(key="bt_capital_AAPL").set_value(69_000).run()
    _clean(at)

    at.selectbox(key="bt_strategy").set_value("iron_condor").run()
    at.slider(key="bt_condor_distance").set_value(12.0).run()
    at.slider(key="bt_condor_wing").set_value(2.0).run()
    _clean(at)


def test_game_flow_and_debrief():
    at = _new_app()
    at.radio(key="page_selector").set_value("game").run()
    _clean(at)
    assert any(button.key == "game_launch" for button in at.button)

    at.button(key="game_launch").click().run()
    _clean(at)
    assert any(button.key == "game_fast" for button in at.button)

    at.button(key="game_fast").click().run()
    # Fragment state changes are applied on the next fragment run; AppTest has
    # no wall-clock timer, so trigger one explicitly.
    at.run()
    _clean(at)
    if any(button.key == "decision_hold" for button in at.button):
        at.button(key="decision_hold").click().run()
        at.run()
        _clean(at)
        if any(button.key == "game_fast" for button in at.button):
            at.button(key="game_fast").click().run()
            at.run()
            _clean(at)
    if any(button.key == "decision_liquidate" for button in at.button):
        at.button(key="decision_liquidate").click().run()
        at.run()
        _clean(at)
    at.run()
    _clean(at)
    body = "\n".join(item.value for item in at.markdown)
    assert "Thematic profile" in body or "Final NAV" in body


def test_data_vault_and_field_guide():
    at = _new_app()
    at.radio(key="page_selector").set_value("data").run()
    _clean(at)
    assert len(at.dataframe) >= 1
    assert len(at.selectbox) == 0  # only widgets; the refresh actions are buttons

    at.radio(key="page_selector").set_value("guide").run()
    _clean(at)
    assert any("Greeks" in item.value for item in at.markdown)


def test_ai_arena_local_showdown():
    at = _new_app()
    at.radio(key="page_selector").set_value("arena").run()
    _clean(at)
    body = "\n".join(item.value for item in at.markdown)
    assert "AlphaVanguard AI" in body
    assert "derivlab-local-quant-core-v1" in body or "derivlab-local-critic-v1" in body
    assert any(button.key == "arena_run" for button in at.button)
    at.button(key="arena_run").click().run()
    _clean(at)
    assert at.session_state["arena_result"] is not None
    assert len(at.get("plotly_chart")) >= 1
    assert len(at.tabs) >= 4
    body = "\n".join(item.value for item in at.markdown)
    assert "Performance Summary" in body
    assert "Tactical Critique" in body
    assert "NEON TAPE" in body or "DESK WATCH" in body


def test_sidebar_navigation_covers_every_page():
    at = _new_app()
    for page in ("strategy", "backtest", "arena", "game", "data", "guide"):
        at.radio(key="page_selector").set_value(page).run()
        _clean(at)


@pytest.mark.parametrize("strategy", ["iron_condor", "long_straddle"])
def test_game_game_setup_other_strategies(strategy):
    at = _new_app()
    at.radio(key="page_selector").set_value("game").run()
    at.selectbox(key="game_strategy").set_value(strategy).run()
    _clean(at)
    at.selectbox(key="game_asset").set_value("MSFT").run()
    _clean(at)
