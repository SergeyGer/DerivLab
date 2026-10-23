"""The AI Arena: four desks trading the same historical scenario.

The user supplies one manual mandate. Three autonomous desks examine the market
context strictly before the scenario start, choose their own strategy and
parameters, and run through the same Backtrader/Black-Scholes engine. The winner
is ranked on a composite of return, drawdown, Sharpe, and premium efficiency,
then AlphaVanguard AI writes the performance review and NewsWire writes the tape.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from ..backtest_engine import BacktestResult, run_backtest
from ..config import STRATEGY_EDU_DB, Asset
from ..data_fetcher import MarketData, compute_hv_series
from ..game_mode import scenario_frame
from ..strategies import StrategyConfig
from .bridge import AIAgentBridge
from .commentary import (
    ArenaReport,
    NewsBundle,
    NewsItem,
    generate_news,
    generate_report,
)
from .llm import (
    LOCAL_DECISION_MODEL,
    LOCAL_NEWS_MODEL,
    MODEL_RECOMMENDATIONS,
    LLMClient,
    LLMSettings,
    ModelRecommendation,
    public_model_stack,
)
from .personas import (
    AGENTS,
    AgentDecision,
    AgentPersona,
    MarketContext,
    decide_agents,
    snapshot_context,
)

LOGGER = logging.getLogger(__name__)


class ArenaError(RuntimeError):
    """A friendly arena setup error that the UI can display."""


@dataclass
class ArenaEntry:
    """One desk's completed portfolio and its associated mandate."""

    key: str
    name: str
    role: str
    color: str
    kind: str  # "user" or "agent"
    strategy_key: str
    model: str
    source: str
    result: BacktestResult
    decision: AgentDecision | None = None
    score: float = 0.0
    rank: int = 0
    avatar: str = ""

    @property
    def is_user(self) -> bool:
        return self.kind == "user"

    @property
    def return_pct(self) -> float:
        return float(self.result.summary.total_return)

    @property
    def max_dd_pct(self) -> float:
        return float(self.result.summary.max_drawdown)

    @property
    def sharpe(self) -> float:
        return float(self.result.summary.sharpe)

    @property
    def premium(self) -> float:
        return float(self.result.premium_collected)

    @property
    def strategy_name(self) -> str:
        return STRATEGY_EDU_DB.get(self.strategy_key, {}).get("short", self.strategy_key)

    def snapshot(self) -> dict[str, Any]:
        summary = self.result.summary
        return {
            "key": self.key,
            "name": self.name,
            "role": self.role,
            "color": self.color,
            "kind": self.kind,
            "is_user": self.is_user,
            "avatar": self.avatar,
            "strategy_key": self.strategy_key,
            "strategy": self.strategy_name,
            "model": self.model,
            "source": self.source,
            "return": round(float(summary.total_return), 6),
            "max_drawdown": round(float(summary.max_drawdown), 6),
            "sharpe": round(float(summary.sharpe), 4),
            "sortino": round(float(summary.sortino), 4),
            "win_rate": round(float(summary.win_rate), 4),
            "premium": round(float(self.result.premium_collected), 2),
            "premium_yield": round(float(summary.premium_yield), 6),
            "final_nav": round(float(self.result.final_nav), 2),
            "capital": round(float(self.result.initial_capital), 2),
            "assignments": int(self.result.assignments),
            "score": round(float(self.score), 1),
            "rank": int(self.rank),
            "decision": self.decision.public_dict() if self.decision else None,
        }

    def public_dict(self) -> dict[str, Any]:
        return self.snapshot()


@dataclass
class ArenaResult:
    """Everything the AI Arena screen needs to render one completed cycle."""

    asset: Asset
    scenario: str
    start: date
    end: date
    capital: float
    context: MarketContext
    entries: list[ArenaEntry]
    leaderboard: pd.DataFrame
    triggers: list[dict[str, Any]]
    payload: dict[str, Any]
    report: ArenaReport
    news: NewsBundle
    settings: LLMSettings
    model_stack: list[dict[str, Any]]
    model_assignments: list[dict[str, Any]]
    llm_status: dict[str, Any]
    use_llm: bool
    use_llm_decisions: bool
    warnings: list[str] = field(default_factory=list)
    created_at: str = ""
    bridge_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def user(self) -> ArenaEntry:
        return next(entry for entry in self.entries if entry.is_user)

    @property
    def agents(self) -> list[ArenaEntry]:
        return [entry for entry in self.entries if not entry.is_user]

    @property
    def alpha(self) -> ArenaEntry:
        return next(
            (entry for entry in self.agents if entry.key == "alpha"),
            self.agents[0],
        )

    @property
    def winner(self) -> ArenaEntry:
        return min(self.entries, key=lambda entry: entry.rank)

    @property
    def user_rank(self) -> int:
        return int(self.user.rank)

    @property
    def alpha_gap(self) -> float:
        return self.user.return_pct - self.alpha.return_pct

    @property
    def news_items(self) -> list[NewsItem]:
        return self.news.items

    @property
    def model_summary(self) -> str:
        return (
            f"critic={self.report.model}; news={self.news.model}; "
            f"decisions={'LLM' if self.use_llm_decisions else 'local policy'}"
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset.symbol,
            "scenario": self.scenario,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "winner": self.winner.snapshot(),
            "user": self.user.snapshot(),
            "alpha": self.alpha.snapshot(),
            "report": self.report.public_dict(),
            "news": self.news.public_dict(),
        }


# ---------------------------------------------------------------------------
# Market context and scoring
# ---------------------------------------------------------------------------


def build_market_context(
    market: MarketData,
    scenario: dict,
    frame: pd.DataFrame,
    capital: float,
) -> MarketContext:
    """Compute a strictly pre-simulation information set for the agent desks."""

    asset = market.asset
    start = pd.Timestamp(frame.index.min())
    history = market.frame[market.frame.index < start]
    hv_series = compute_hv_series(market.frame["Close"]).dropna()
    hv_history = hv_series[hv_series.index < start].dropna()

    if len(hv_history) >= 5:
        hv30 = float(hv_history.iloc[-1])
        reference = hv_history.tail(252)
        hv_percentile = float((reference <= hv30).mean()) if len(reference) else 0.5
        vol_ratio = float(hv30 / reference.mean()) if reference.mean() > 0 else 1.0
    else:
        hv30 = float(asset.base_iv)
        hv_percentile = 0.5
        vol_ratio = 1.0

    closes = history["Close"].dropna()
    if len(closes) >= 2:
        spot = float(closes.iloc[-1])
        trend20 = float(spot / closes.iloc[-21] - 1.0) if len(closes) >= 21 else 0.0
        trend60 = float(spot / closes.iloc[-61] - 1.0) if len(closes) >= 61 else 0.0
        drawdown120 = float(spot / closes.tail(120).max() - 1.0) if closes.tail(120).max() > 0 else 0.0
    else:
        spot = float(frame["Close"].iloc[0])
        trend20 = 0.0
        trend60 = 0.0
        drawdown120 = 0.0

    return snapshot_context(
        asset_symbol=asset.symbol,
        asset_name=asset.name,
        scenario=str(scenario.get("label", "Custom scenario")),
        as_of=start.date(),
        spot=spot,
        hv30=hv30,
        hv_percentile=hv_percentile,
        trend20=trend20,
        trend60=trend60,
        drawdown120=drawdown120,
        vol_ratio=vol_ratio,
        capital=capital,
    )


def arena_score(result: BacktestResult) -> float:
    """Composite 0-100 desk score used for the leaderboard."""

    summary = result.summary
    ret = float(summary.total_return)
    dd = min(max(float(summary.max_drawdown), 0.0), 1.0)
    sharpe = float(summary.sharpe)
    premium_yield = float(summary.premium_yield)
    raw = (
        50.0
        + 38.0 * math.tanh(ret / 0.15)
        + 15.0 * (1.0 - min(dd / 0.20, 1.0))
        + 5.0 * math.tanh(sharpe / 2.0)
        + 7.0 * math.tanh(premium_yield / 0.02)
    )
    if result.contracts <= 0:
        raw = min(raw, 20.0)
    return round(max(0.0, min(raw, 100.0)), 1)


# ---------------------------------------------------------------------------
# Critical triggers
# ---------------------------------------------------------------------------


def extract_critical_triggers(result: BacktestResult, limit: int = 8) -> list[dict[str, Any]]:
    """Derive a compact, explainable event timeline for the AI critic."""

    triggers: list[dict[str, Any]] = []
    events = result.events if result.events is not None else pd.DataFrame()
    if not events.empty:
        for _, row in events.iterrows():
            kind = str(row.get("kind", ""))
            if kind not in {"breach", "assignment"}:
                continue
            triggers.append(
                {
                    "date": pd.Timestamp(row.get("date")).date().isoformat(),
                    "kind": kind,
                    "title": str(row.get("title", kind.title())),
                    "detail": str(row.get("detail", "")),
                    "severity": "high" if kind == "assignment" else "medium",
                }
            )

    nav = result.nav
    if nav is not None and not nav.empty and "iv" in nav:
        iv = pd.to_numeric(nav["iv"], errors="coerce").dropna()
        if len(iv) >= 6:
            changes = iv.pct_change().dropna()
            if not changes.empty:
                threshold = max(0.15, float(changes.std(ddof=1) or 0.0) * 2.0)
                spikes = changes[changes >= threshold].sort_values(ascending=False).head(2)
                for ts, change in spikes.items():
                    triggers.append(
                        {
                            "date": pd.Timestamp(ts).date().isoformat(),
                            "kind": "iv_spike",
                            "title": "Implied volatility spike",
                            "detail": (
                                f"Synthetic IV jumped {float(change) * 100:+.1f}% to "
                                f"{float(iv.loc[ts]) * 100:.1f}% on {pd.Timestamp(ts).date()}."
                            ),
                            "severity": "high" if change >= 0.30 else "medium",
                        }
                    )
    if nav is not None and not nav.empty and "drawdown" in nav:
        drawdown = pd.to_numeric(nav["drawdown"], errors="coerce").dropna()
        if not drawdown.empty and float(drawdown.min()) <= -0.08:
            worst_ts = drawdown.idxmin()
            triggers.append(
                {
                    "date": pd.Timestamp(worst_ts).date().isoformat(),
                    "kind": "drawdown",
                    "title": "Drawdown threshold",
                    "detail": (
                        f"Peak-to-trough drawdown reached {abs(float(drawdown.loc[worst_ts])) * 100:.1f}% "
                        f"on {pd.Timestamp(worst_ts).date()}."
                    ),
                    "severity": "high" if float(drawdown.min()) <= -0.18 else "medium",
                }
            )

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for item in triggers:
        deduped[(item["date"], item["kind"])] = item
    ordered = sorted(deduped.values(), key=lambda item: (item["date"], item["kind"]))
    return ordered[:limit]


# ---------------------------------------------------------------------------
# Arena runner
# ---------------------------------------------------------------------------


def _entry_config(
    user_config: StrategyConfig,
    *,
    strategy_key: str,
    tenor_days: int,
    strike_offset_pct: float,
    wing_width_pct: float,
    basis_pct: float,
) -> StrategyConfig:
    return StrategyConfig(
        strategy_key=strategy_key,
        asset_symbol=user_config.asset_symbol,
        capital=float(user_config.capital),
        tenor_days=int(tenor_days),
        strike_offset_pct=float(strike_offset_pct),
        iv_multiplier=float(user_config.iv_multiplier),
        risk_free=float(user_config.risk_free),
        fee_bps=float(user_config.fee_bps),
        basis_pct=float(basis_pct),
        wing_width_pct=float(wing_width_pct),
        lookback_years=10,
    )


def _agent_model(entry: AgentDecision, settings: LLMSettings) -> str:
    if entry.source == "llm":
        return entry.model
    return LOCAL_DECISION_MODEL


def _agent_source_label(entry: AgentDecision, settings: LLMSettings) -> str:
    if entry.source == "llm":
        return f"LLM · {settings.provider_label}"
    return "Local policy"


def _entry_snapshot(entry: ArenaEntry) -> dict[str, Any]:
    return entry.snapshot()


def run_arena(
    market: MarketData,
    scenario: dict,
    user_config: StrategyConfig,
    *,
    settings: LLMSettings | None = None,
    use_llm: bool = True,
    use_llm_decisions: bool = False,
) -> ArenaResult:
    """Run the user desk and three autonomous desks on the same scenario."""

    settings = settings or LLMSettings.from_env()
    frame = scenario_frame(market, scenario)
    if len(frame) < 30:
        raise ArenaError("This scenario does not contain enough history for the AI Arena.")

    capital = float(user_config.capital)
    if capital <= 0:
        raise ArenaError("Capital must be positive to run the AI Arena.")
    context = build_market_context(market, scenario, frame, capital)
    active_llm = bool(use_llm and settings.enabled)
    client = LLMClient(settings) if active_llm else None

    decisions, decision_llm = decide_agents(
        context,
        settings,
        client,
        use_llm=bool(use_llm_decisions and settings.enabled and active_llm),
    )

    warnings: list[str] = []
    if settings.enabled and not active_llm:
        warnings.append(
            "An LLM is configured but was disabled for this run; local deterministic models were used."
        )
    if decision_llm is not None and not decision_llm.ok:
        warnings.append(f"LLM decision call failed: {decision_llm.error}. Local policies were used.")
    elif decision_llm is not None and decision_llm.ok:
        # A successful call can still contain invalid/missing persona keys.
        pass

    # User desk
    user_config = StrategyConfig(
        **{
            **user_config.__dict__,
            "capital": capital,
            "lookback_years": 10,
        }
    )
    user_bridge = AIAgentBridge()
    user_result = run_backtest(
        market.asset.symbol,
        frame,
        user_config,
        lookback_years=10,
        event_bridge=user_bridge,
    )
    user_entry = ArenaEntry(
        key="user",
        name="You · User Desk",
        role="Manual mandate",
        color="#F5F5F5",
        kind="user",
        strategy_key=user_config.strategy_key,
        model="User mandate (manual)",
        source="manual",
        result=user_result,
        decision=None,
        avatar="◆",
    )

    entries: list[ArenaEntry] = [user_entry]
    for persona, decision in zip(AGENTS, decisions, strict=False):
        config = _entry_config(
            user_config,
            strategy_key=decision.strategy_key,
            tenor_days=decision.tenor_days,
            strike_offset_pct=decision.strike_offset_pct,
            wing_width_pct=decision.wing_width_pct,
            basis_pct=decision.basis_pct,
        )
        bridge = AIAgentBridge()
        result = run_backtest(
            market.asset.symbol,
            frame,
            config,
            lookback_years=10,
            event_bridge=bridge,
        )
        entries.append(
            ArenaEntry(
                key=persona.key,
                name=persona.name,
                role=persona.role,
                color=persona.color,
                kind="agent",
                strategy_key=decision.strategy_key,
                model=_agent_model(decision, settings),
                source=_agent_source_label(decision, settings),
                result=result,
                decision=decision,
                avatar=persona.avatar,
            )
        )

    for entry in entries:
        entry.score = arena_score(entry.result)
    ranked = sorted(entries, key=lambda item: (-item.score, -item.return_pct, item.name))
    for rank, entry in enumerate(ranked, start=1):
        entry.rank = rank

    leaderboard = pd.DataFrame(
        [
            {
                "Rank": entry.rank,
                "Desk": entry.name,
                "Model": entry.model,
                "Strategy": entry.strategy_name,
                "Return": entry.return_pct,
                "Max Drawdown": entry.max_dd_pct,
                "Sharpe": entry.sharpe,
                "Sortino": entry.result.summary.sortino,
                "Win Rate": entry.result.summary.win_rate,
                "Premium": entry.premium,
                "Score": entry.score,
                "Kind": entry.kind,
                "Source": entry.source,
            }
            for entry in ranked
        ]
    )

    triggers = extract_critical_triggers(user_result)
    stack_settings = settings if active_llm else LLMSettings.local()
    stack = public_model_stack(
        stack_settings,
        use_llm_decisions=bool(use_llm_decisions and active_llm),
    )
    for entry in entries:
        if entry.kind != "agent":
            continue
        stack.append(
            {
                "role": f"{entry.name} trade mandate",
                "model": entry.model,
                "provider": settings.provider_label if entry.decision and entry.decision.source == "llm" else "Offline deterministic",
                "mode": "LLM" if entry.decision and entry.decision.source == "llm" else "Local policy",
            }
        )

    alpha_entry = next((entry for entry in entries if entry.key == "alpha"), entries[1])
    winner = ranked[0]
    payload: dict[str, Any] = {
        "selected_strategy_asset": {
            "asset": market.asset.symbol,
            "asset_name": market.asset.name,
            "strategy_key": user_config.strategy_key,
            "strategy": user_entry.strategy_name,
            "scenario": str(scenario.get("label", "Custom scenario")),
            "window": f"{pd.Timestamp(frame.index.min()).date()} → {pd.Timestamp(frame.index.max()).date()}",
            "capital": round(capital, 2),
            "currency": market.asset.currency,
        },
        "market_context": context.public_dict(),
        "user_portfolio": user_entry.snapshot(),
        "ai_rival_portfolio": alpha_entry.snapshot(),
        "winner": winner.snapshot(),
        "leaderboard": [entry.snapshot() for entry in ranked],
        "critical_historical_triggers": triggers,
        "model_stack": stack,
        "agents": [entry.snapshot() for entry in entries if entry.kind == "agent"],
    }

    report = generate_report(payload, client)
    news = generate_news(payload, client)
    if report.error:
        warnings.append(report.error)
    if news.error:
        warnings.append(news.error)

    # The user-visible stack must show what actually happened, including a local
    # fallback when a configured LLM failed validation.
    for row in stack:
        role = str(row.get("role", "")).lower()
        if "critic" in role:
            row["model"] = report.model
            row["mode"] = "LLM" if report.used_llm else "Local fallback"
            if not report.used_llm:
                row["provider"] = "Offline deterministic"
        elif "news" in role:
            row["model"] = news.model
            row["mode"] = "LLM" if news.used_llm else "Local fallback"
            if not news.used_llm:
                row["provider"] = "Offline deterministic"

    news_model = news.model
    model_assignments = [
        {
            "agent": entry.name,
            "role": entry.role,
            "decision_model": entry.model,
            "decision_source": entry.source,
            "critic_model": report.model,
            "news_model": news.model if entry.key == "alpha" else news_model,
            "avatar": entry.avatar,
            "color": entry.color,
        }
        for entry in entries
        if entry.kind == "agent"
    ]

    llm_status = {
        "configured": settings.enabled,
        "use_llm": active_llm,
        "use_llm_decisions": bool(use_llm_decisions and active_llm),
        "provider": settings.provider,
        "provider_label": settings.provider_label,
        "decision_result": decision_llm.public_dict() if decision_llm else None,
        "report": report.public_dict(),
        "news": news.public_dict(),
    }
    result = ArenaResult(
        asset=market.asset,
        scenario=str(scenario.get("label", "Custom scenario")),
        start=pd.Timestamp(frame.index.min()).date(),
        end=pd.Timestamp(frame.index.max()).date(),
        capital=capital,
        context=context,
        entries=entries,
        leaderboard=leaderboard,
        triggers=triggers,
        payload=payload,
        report=report,
        news=news,
        settings=settings,
        model_stack=stack,
        model_assignments=model_assignments,
        llm_status=llm_status,
        use_llm=active_llm,
        use_llm_decisions=bool(use_llm_decisions and active_llm),
        warnings=list(dict.fromkeys(warnings)),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        bridge_events=[event.public_dict() for event in user_bridge.events],
    )
    return result


def model_catalog() -> list[ModelRecommendation]:
    return list(MODEL_RECOMMENDATIONS)


def default_model_stack(settings: LLMSettings, use_llm_decisions: bool = False) -> list[dict[str, Any]]:
    return public_model_stack(settings, use_llm_decisions=use_llm_decisions)


def describe_agent(persona: AgentPersona) -> dict[str, Any]:
    return persona.public_dict()


def local_models_for_ui() -> tuple[str, str, str]:
    return (LOCAL_DECISION_MODEL, LOCAL_NEWS_MODEL, "DerivLab deterministic critic")


def serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)
