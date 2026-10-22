"""Tests for the autonomous AI agent layer (all offline)."""

from __future__ import annotations

import asyncio
import json

import pytest

from derivlab.agents.arena import (
    ArenaError,
    arena_score,
    build_market_context,
    extract_critical_triggers,
    run_arena,
)
from derivlab.agents.bridge import AIAgentBridge
from derivlab.agents.commentary import (
    REPORT_HEADINGS,
    generate_news,
    generate_report,
    local_news,
    local_report,
    validate_report,
)
from derivlab.agents.llm import (
    LOCAL_CRITIC_MODEL,
    LOCAL_DECISION_MODEL,
    LOCAL_NEWS_MODEL,
    MODEL_RECOMMENDATIONS,
    LLMClient,
    LLMResult,
    LLMSettings,
    public_model_stack,
)
from derivlab.agents.parsing import extract_json_array, extract_json_object
from derivlab.agents.personas import (
    AGENTS,
    STRATEGY_CHOICES,
    MarketContext,
    build_decision_prompt,
    decide_agents,
    normalize_agent_decision,
    policy_decision,
    snapshot_context,
)
from derivlab.backtest_engine import run_backtest
from derivlab.config import GAME_SCENARIOS, suggested_capital
from derivlab.strategies import StrategyConfig


def scenario(scenario_id: str = "rate_shock_2022") -> dict:
    return next(item for item in GAME_SCENARIOS if item["id"] == scenario_id)


def context_for(market, scenario_id: str = "rate_shock_2022") -> MarketContext:
    from derivlab.game_mode import scenario_frame

    frame = scenario_frame(market, scenario(scenario_id))
    return build_market_context(market, scenario(scenario_id), frame, 100_000)


def user_config_for(market, strategy="covered_call", capital=None) -> StrategyConfig:
    return StrategyConfig(
        strategy_key=strategy,
        asset_symbol=market.asset.symbol,
        capital=float(capital or suggested_capital(market.latest_close, market.asset.multiplier)),
        tenor_days=30,
        strike_offset_pct=5.0 if strategy != "cash_secured_put" else -5.0,
        basis_pct=5.0,
        wing_width_pct=5.0,
        lookback_years=10,
    )


def enabled_settings() -> LLMSettings:
    return LLMSettings(
        provider="openai_compatible",
        base_url="https://example.invalid/v1",
        api_key="test-key",
        decision_model="fake-decision",
        critic_model="fake-critic",
        news_model="fake-news",
        timeout=5.0,
        temperature=0.4,
        explicitly_configured=True,
    )


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, settings: LLMSettings, decision_text: str | None = None,
                 report_text: str | None = None, news_text: str | None = None,
                 ok: bool = True):
        self.settings = settings
        self.decision_text = decision_text
        self.report_text = report_text
        self.news_text = news_text
        self.ok = ok
        self.calls: list[tuple[str, str]] = []

    def generate(self, system, user, *, role="critic", max_tokens=900):
        self.calls.append((role, user))
        texts = {
            "decision": self.decision_text,
            "critic": self.report_text,
            "news": self.news_text,
        }
        text = texts.get(role, "")
        if not self.ok or text is None:
            return LLMResult(
                text="",
                ok=False,
                model=LOCAL_CRITIC_MODEL,
                provider="local",
                source="local",
                error="fake outage",
            )
        model = {
            "decision": self.settings.decision_model,
            "critic": self.settings.critic_model,
            "news": self.settings.news_model,
        }[role]
        return LLMResult(
            text=text,
            ok=True,
            model=model,
            provider=self.settings.provider,
            source="llm",
            latency_ms=12,
        )


# ---------------------------------------------------------------------------
# Settings and model catalog
# ---------------------------------------------------------------------------


def test_llm_settings_local_defaults():
    settings = LLMSettings.from_env({})
    assert settings.provider == "local"
    assert settings.enabled is False
    assert settings.active_model_for("decision") == LOCAL_DECISION_MODEL
    assert settings.active_model_for("critic") == LOCAL_CRITIC_MODEL
    assert settings.active_model_for("news") == LOCAL_NEWS_MODEL
    public = settings.public_dict()
    assert public["mode"] == "LOCAL QUANT CORE"
    assert public["api_key_configured"] is False


def test_llm_settings_environment_inference():
    settings = LLMSettings.from_env(
        {
            "OPENAI_API_KEY": "sk-test",
            "DERIVLAB_CRITIC_MODEL": "critic-x",
            "DERIVLAB_NEWS_MODEL": "news-y",
        }
    )
    assert settings.provider == "openai"
    assert settings.enabled is True
    assert settings.api_key == "sk-test"
    assert settings.critic_model == "critic-x"
    assert settings.news_model == "news-y"
    assert settings.public_dict()["decision_model"] == settings.decision_model


def test_llm_settings_anthropic_and_no_key_compatible():
    anthropic = LLMSettings.from_env({"ANTHROPIC_API_KEY": "ak-test"})
    assert anthropic.provider == "anthropic"
    assert anthropic.enabled is True
    assert "claude" in anthropic.critic_model

    ollama = LLMSettings.from_env(
        {
            "DERIVLAB_LLM_PROVIDER": "ollama",
            "DERIVLAB_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "DERIVLAB_LLM_MODEL": "qwen3:32b",
        }
    )
    assert ollama.enabled is True
    assert ollama.api_key == ""


def test_model_advice_catalog():
    labels = " ".join(
        rec.primary + " " + " ".join(rec.alternatives) for rec in MODEL_RECOMMENDATIONS
    ).lower()
    assert "gpt-5" in labels
    assert "claude" in labels
    assert "qwen" in labels
    stack = public_model_stack(LLMSettings.local(), use_llm_decisions=False)
    assert all(item["model"].startswith("derivlab-local-") for item in stack)
    assert any("critic" in item["role"].lower() for item in stack)


# ---------------------------------------------------------------------------
# HTTP clients
# ---------------------------------------------------------------------------


def test_openai_client_parses_response(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json))
        return FakeResponse({"choices": [{"message": {"content": "hello from model"}}]})

    monkeypatch.setattr("derivlab.agents.llm.requests.post", fake_post)
    settings = LLMSettings(
        provider="openai",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        decision_model="m1",
        critic_model="m2",
        news_model="m3",
    )
    result = LLMClient(settings).generate("system", "user", role="critic")
    assert result.ok is True
    assert result.source == "llm"
    assert result.text == "hello from model"
    assert result.model == "m2"
    assert calls[0][0] == "https://api.openai.com/v1/chat/completions"
    assert calls[0][1]["Authorization"] == "Bearer secret"


def test_openai_client_retries_max_completion_tokens(monkeypatch):
    payloads = []

    def fake_post(url, headers=None, json=None, timeout=None):
        payloads.append(dict(json) if json else {})
        if len(payloads) == 1:
            return FakeResponse({"error": "max_tokens unsupported"}, status_code=400)
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("derivlab.agents.llm.requests.post", fake_post)
    settings = enabled_settings()
    result = LLMClient(settings).generate("s", "u", role="critic")
    assert result.ok is True
    assert "max_tokens" in payloads[0]
    assert "max_completion_tokens" in payloads[1]
    assert "max_tokens" not in payloads[1]


def test_openai_client_failure_falls_back(monkeypatch):
    def fake_post(*args, **kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr("derivlab.agents.llm.requests.post", fake_post)
    settings = enabled_settings()
    result = LLMClient(settings).generate("s", "u", role="critic")
    assert result.ok is False
    assert result.source == "local"
    assert result.model == LOCAL_CRITIC_MODEL
    assert "timeout" in result.error.lower()


def test_anthropic_client_parses_response(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json))
        return FakeResponse({"content": [{"type": "text", "text": "anthropic hello"}]})

    monkeypatch.setattr("derivlab.agents.llm.requests.post", fake_post)
    settings = LLMSettings(
        provider="anthropic",
        base_url="https://api.anthropic.com",
        api_key="ak",
        decision_model="d",
        critic_model="c",
        news_model="n",
    )
    result = LLMClient(settings).generate("s", "u", role="critic")
    assert result.ok is True
    assert result.text == "anthropic hello"
    assert calls[0][0].endswith("/v1/messages")
    assert calls[0][1]["x-api-key"] == "ak"


def test_json_parsing_helpers():
    assert extract_json_object("prefix ```json\n{\"a\": 1}\n``` suffix") == {"a": 1}
    assert extract_json_array("```\n[{\"tag\": \"X\"}]\n```") == [{"tag": "X"}]
    assert extract_json_object("not json") is None
    assert extract_json_array("{}") is None


# ---------------------------------------------------------------------------
# Personas and decisions
# ---------------------------------------------------------------------------


def test_policy_decisions_are_valid(service):
    market = service.load("AAPL")
    context = context_for(market)
    decisions = [policy_decision(agent, context) for agent in AGENTS]
    assert len(decisions) == 3
    for decision in decisions:
        assert decision.strategy_key in STRATEGY_CHOICES
        assert decision.tenor_days in (30, 60, 90)
        assert decision.source == "policy"
        assert decision.model == LOCAL_DECISION_MODEL
        assert decision.rationale
    assert {d.strategy_key for d in decisions}.__len__() >= 2


def test_persona_policy_responds_to_regime():
    base = dict(
        asset_symbol="AAPL",
        asset_name="Apple",
        scenario="test",
        as_of=__import__("datetime").date(2024, 1, 2),
        spot=100.0,
        trend20=0.05,
        trend60=0.08,
        drawdown120=-0.01,
        vol_ratio=1.2,
        capital=100_000.0,
    )
    high_vol = snapshot_context(hv30=0.40, hv_percentile=0.90, **base)
    low_vol = snapshot_context(hv30=0.10, hv_percentile=0.10, **base)
    alpha_high = policy_decision(AGENTS[0], high_vol)
    volt_high = policy_decision(AGENTS[1], high_vol)
    basis_any = policy_decision(AGENTS[2], high_vol)
    assert alpha_high.strategy_key == "covered_call"
    assert volt_high.strategy_key == "long_straddle"
    assert basis_any.strategy_key == "basis_trade"
    assert policy_decision(AGENTS[0], low_vol).strategy_key == "iron_condor"
    assert policy_decision(AGENTS[1], low_vol).strategy_key in {"iron_condor", "long_straddle"}


def test_decision_prompt_contains_constraints(service):
    context = context_for(service.load("AAPL"))
    prompt = build_decision_prompt(context, AGENTS)
    assert "covered_call" in prompt
    assert all(agent.key in prompt for agent in AGENTS)
    assert "strike_offset_pct" in prompt


def test_normalize_agent_decision_clamps():
    context = MarketContext(
        asset_symbol="AAPL",
        asset_name="Apple",
        scenario="test",
        as_of=__import__("datetime").date(2024, 1, 2),
        spot=100.0,
        hv30=0.25,
        hv_percentile=0.5,
        trend20=0.0,
        trend60=0.0,
        drawdown120=0.0,
        vol_ratio=1.0,
        capital=100_000.0,
    )
    decision = normalize_agent_decision(
        {
            "strategy_key": "iron_condor",
            "tenor_days": 999,
            "strike_offset_pct": -100,
            "wing_width_pct": 999,
            "basis_pct": -10,
            "rationale": "test",
        },
        AGENTS[0],
        context,
    )
    assert decision.strategy_key == "iron_condor"
    assert decision.tenor_days in (30, 60, 90)
    assert 2 <= decision.strike_offset_pct <= 20
    assert 1 <= decision.wing_width_pct <= 10
    assert 0 <= decision.basis_pct <= 15


def test_decide_agents_llm_path(service):
    settings = enabled_settings()
    context = context_for(service.load("AAPL"))
    decisions_json = {
        "alpha": {
            "strategy_key": "cash_secured_put",
            "tenor_days": 60,
            "strike_offset_pct": -6,
            "wing_width_pct": 5,
            "basis_pct": 5,
            "rationale": "LLM alpha mandate",
        },
        "volt": {
            "strategy_key": "long_straddle",
            "tenor_days": 30,
            "strike_offset_pct": 0,
            "wing_width_pct": 5,
            "basis_pct": 5,
            "rationale": "LLM volt mandate",
        },
        "basis": {
            "strategy_key": "basis_trade",
            "tenor_days": 90,
            "strike_offset_pct": 0,
            "wing_width_pct": 5,
            "basis_pct": 5,
            "rationale": "LLM basis mandate",
        },
    }
    client = FakeClient(settings, decision_text=json.dumps(decisions_json))
    decisions, result = decide_agents(context, settings, client, use_llm=True)
    assert result is not None and result.ok
    assert [decision.strategy_key for decision in decisions] == [
        "cash_secured_put",
        "long_straddle",
        "basis_trade",
    ]
    assert all(decision.source == "llm" for decision in decisions)
    assert all(decision.model == "fake-decision" for decision in decisions)


def test_decide_agents_invalid_json_falls_back(service):
    settings = enabled_settings()
    context = context_for(service.load("AAPL"))
    client = FakeClient(settings, decision_text="definitely not json")
    decisions, result = decide_agents(context, settings, client, use_llm=True)
    assert result is not None and result.ok
    assert all(decision.source == "policy" for decision in decisions)


# ---------------------------------------------------------------------------
# Reports and news
# ---------------------------------------------------------------------------


def _payload_for(market, arena):
    return arena.payload


def test_local_report_format_and_metrics(service):
    market = service.load("AAPL")
    arena = run_arena(
        market,
        scenario(),
        user_config_for(market),
        settings=LLMSettings.local(),
        use_llm=False,
    )
    report = local_report(_payload_for(market, arena))
    assert validate_report(report)
    for heading in REPORT_HEADINGS:
        assert heading in report
    assert "AlphaVanguard" in report
    assert "Recommendation" in report
    assert "Max DD" in report


def test_generate_report_llm_and_fallback(service):
    market = service.load("AAPL")
    arena = run_arena(
        market,
        scenario(),
        user_config_for(market),
        settings=LLMSettings.local(),
        use_llm=False,
    )
    payload = arena.payload
    settings = enabled_settings()
    llm_text = "\n\n".join(
        f"{heading}\n\nLLM content for the desk comparison and risk review."
        for heading in REPORT_HEADINGS
    )
    client = FakeClient(settings, report_text=llm_text)
    report = generate_report(payload, client)
    assert report.source == "llm"
    assert report.model == "fake-critic"
    assert report.latency_ms == 12

    bad_client = FakeClient(settings, report_text="No headings here")
    fallback = generate_report(payload, bad_client)
    assert fallback.source == "local"
    assert fallback.model == LOCAL_CRITIC_MODEL
    assert fallback.error


def test_news_local_and_llm(service):
    market = service.load("AAPL")
    arena = run_arena(
        market,
        scenario(),
        user_config_for(market),
        settings=LLMSettings.local(),
        use_llm=False,
    )
    payload = arena.payload
    local = local_news(payload)
    assert len(local) == 4
    assert all(item.tag and item.headline and item.detail for item in local)
    local_bundle = generate_news(payload, None)
    assert local_bundle.source == "local"
    assert local_bundle.model == LOCAL_NEWS_MODEL

    settings = enabled_settings()
    items = [
        {
            "tag": "NEON TAPE",
            "headline": "Model headline one",
            "detail": "Model detail one",
            "severity": "high",
        },
        {
            "tag": "DESK WATCH",
            "headline": "Model headline two",
            "detail": "Model detail two",
            "severity": "medium",
        },
        {
            "tag": "STRIKE SHOCK",
            "headline": "Model headline three",
            "detail": "Model detail three",
            "severity": "low",
        },
        {
            "tag": "WIRE",
            "headline": "Model headline four",
            "detail": "Model detail four",
            "severity": "low",
        },
    ]
    client = FakeClient(settings, news_text=json.dumps(items))
    bundle = generate_news(payload, client)
    assert bundle.source == "llm"
    assert bundle.model == "fake-news"
    assert len(bundle.items) == 4


def test_news_invalid_json_falls_back(service):
    market = service.load("AAPL")
    arena = run_arena(
        market,
        scenario(),
        user_config_for(market),
        settings=LLMSettings.local(),
        use_llm=False,
    )
    settings = enabled_settings()
    bundle = generate_news(arena.payload, FakeClient(settings, news_text="not an array"))
    assert bundle.source == "local"
    assert bundle.error


# ---------------------------------------------------------------------------
# Bridge and arena
# ---------------------------------------------------------------------------


def test_bridge_collects_and_processes_events():
    bridge = AIAgentBridge()
    event = bridge.emit(
        {
            "event": "STRIKE_BREACH",
            "date": "2022-03-24",
            "spot_price": 170.0,
            "strike_price": 167.0,
            "message": "test breach",
        }
    )
    assert event.event == "STRIKE_BREACH"
    assert bridge.pending == 1
    drained = bridge.drain()
    assert len(drained) == 1
    processed = asyncio.run(
        bridge.process_market_shock(
            {
                "event": "ASSIGNMENT",
                "date": "2022-04-04",
                "spot_price": 174.0,
                "strike_price": 167.0,
            }
        )
    )
    assert processed.event == "ASSIGNMENT"
    assert len(bridge.processed_events) == 1


def test_backtest_emits_bridge_events(service):
    market = service.load("AAPL")
    config = user_config_for(market)
    bridge = AIAgentBridge()
    result = run_backtest(
        "AAPL",
        market.frame,
        config,
        lookback_years=1,
        event_bridge=bridge,
    )
    assert len(bridge.events) > 0
    assert any(event.event in {"STRIKE_BREACH", "ASSIGNMENT"} for event in bridge.events)
    assert "breach" in set(result.events["kind"]) or "assignment" in set(result.events["kind"])


def test_arena_local_run(service):
    market = service.load("AAPL")
    arena = run_arena(
        market,
        scenario(),
        user_config_for(market),
        settings=LLMSettings.local(),
        use_llm=False,
    )
    assert len(arena.entries) == 4
    assert len(arena.leaderboard) == 4
    assert sorted(arena.leaderboard["Rank"].tolist()) == [1, 2, 3, 4]
    assert arena.winner.rank == 1
    assert arena.report.source == "local"
    assert arena.report.model == LOCAL_CRITIC_MODEL
    assert len(arena.news.items) == 4
    assert arena.triggers
    assert arena.bridge_events
    assert all(model["model"].startswith("derivlab-local-") for model in arena.model_stack)
    assert arena.user_rank in {1, 2, 3, 4}
    assert arena.alpha.key == "alpha"
    assert arena.context.as_of == arena.start
    assert all(entry.strategy_key in STRATEGY_CHOICES for entry in arena.agents)
    assert {entry.strategy_key for entry in arena.agents} >= {"covered_call", "long_straddle", "basis_trade"}


def test_arena_llm_path(service, monkeypatch):
    market = service.load("AAPL")
    settings = enabled_settings()
    decisions_json = {
        agent.key: {
            "strategy_key": "covered_call" if agent.key != "volt" else "long_straddle",
            "tenor_days": 30,
            "strike_offset_pct": 5,
            "wing_width_pct": 5,
            "basis_pct": 5,
            "rationale": f"{agent.name} LLM mandate",
        }
        for agent in AGENTS
    }
    report_text = "\n\n".join(f"{heading}\n\nModel-generated analysis." for heading in REPORT_HEADINGS)
    news_items = [
        {
            "tag": f"TAG {i}",
            "headline": f"Headline {i}",
            "detail": f"Detail {i}",
            "severity": "medium",
        }
        for i in range(4)
    ]
    fake = FakeClient(
        settings,
        decision_text=json.dumps(decisions_json),
        report_text=report_text,
        news_text=json.dumps(news_items),
    )
    monkeypatch.setattr("derivlab.agents.arena.LLMClient", lambda _settings: fake)
    arena = run_arena(
        market,
        scenario(),
        user_config_for(market),
        settings=settings,
        use_llm=True,
        use_llm_decisions=True,
    )
    assert arena.report.source == "llm"
    assert arena.report.model == "fake-critic"
    assert arena.news.source == "llm"
    assert arena.news.model == "fake-news"
    assert all(entry.decision and entry.decision.source == "llm" for entry in arena.agents)
    assert all(entry.model == "fake-decision" for entry in arena.agents)
    assert any(model["model"] == "fake-critic" for model in arena.model_stack)


def test_arena_requires_enough_history(service):
    market = service.load("AAPL")
    from derivlab.config import GAME_SCENARIOS

    tiny = dict(next(item for item in GAME_SCENARIOS if item["id"] == "full_history"))
    tiny["lookback_bars"] = 10
    # scenario_frame falls back for lookback scenarios; construct a custom slice instead.
    from derivlab.data_fetcher import MarketData

    short_market = MarketData(asset=market.asset, frame=market.frame.tail(20), source="cache")
    with pytest.raises(ArenaError):
        run_arena(
            short_market,
            tiny,
            user_config_for(market),
            settings=LLMSettings.local(),
            use_llm=False,
        )


def test_scores_and_triggers(service):
    market = service.load("AAPL")
    config = user_config_for(market)
    result = run_backtest("AAPL", market.frame, config, lookback_years=1)
    score = arena_score(result)
    assert 0 <= score <= 100
    triggers = extract_critical_triggers(result)
    assert isinstance(triggers, list)
    assert all("date" in item and "kind" in item for item in triggers)
