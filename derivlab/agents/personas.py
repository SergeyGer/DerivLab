"""Autonomous rival personas, market context, and trading policies."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..config import STRATEGY_EDU_DB
from .llm import (
    LOCAL_DECISION_MODEL,
    ROLE_DECISION,
    LLMClient,
    LLMResult,
    LLMSettings,
)
from .parsing import extract_json_object

STRATEGY_CHOICES: tuple[str, ...] = (
    "covered_call",
    "cash_secured_put",
    "basis_trade",
    "long_straddle",
    "iron_condor",
)
TENOR_CHOICES = (30, 60, 90)


@dataclass(frozen=True)
class AgentPersona:
    """One autonomous desk with a distinct mandate and visual identity."""

    key: str
    name: str
    avatar: str
    color: str
    role: str
    mandate: str
    policy_summary: str

    @property
    def decision_model_label(self) -> str:
        return LOCAL_DECISION_MODEL

    def public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "avatar": self.avatar,
            "color": self.color,
            "role": self.role,
            "mandate": self.mandate,
            "policy_summary": self.policy_summary,
            "decision_model": self.decision_model_label,
        }


AGENTS: tuple[AgentPersona, ...] = (
    AgentPersona(
        key="alpha",
        name="AlphaVanguard AI",
        avatar="◈",
        color="#00E676",
        role="Institutional relative-value PM",
        mandate=(
            "Defend capital, harvest the best risk-adjusted carry, and rotate into "
            "delta-neutral basis when the trend and volatility disagree."
        ),
        policy_summary=(
            "Sells premium with the trend in high-vol regimes, uses basis trades in "
            "conflicting regimes, and switches to defined-risk condors when volatility "
            "is cheap."
        ),
    ),
    AgentPersona(
        key="volt",
        name="VoltHawk AI",
        avatar="⚡",
        color="#E040FB",
        role="Volatility arbitrage desk",
        mandate=(
            "Express a view on volatility itself: buy convexity when it is underpriced "
            "by realized moves, sell range when the market is asleep."
        ),
        policy_summary=(
            "Buys straddles in high-vol / fast-trend regimes and sells iron condors "
            "when volatility is compressed and the tape is range-bound."
        ),
    ),
    AgentPersona(
        key="basis",
        name="BasisDyne AI",
        avatar="⛓",
        color="#00E5FF",
        role="Carry and basis desk",
        mandate=(
            "Harvest structural carry and basis convergence while keeping directional "
            "risk close to zero."
        ),
        policy_summary=(
            "Runs synthetic futures basis trades across the curve and only reaches for "
            "premium when carry is rich and the trend is strongly positive."
        ),
    ),
)


@dataclass(frozen=True)
class MarketContext:
    """The pre-simulation information set available to the autonomous desks.

    All features are computed strictly before the scenario start, so the agents
    cannot peek at the outcome they are about to trade.
    """

    asset_symbol: str
    asset_name: str
    scenario: str
    as_of: date
    spot: float
    hv30: float
    hv_percentile: float
    trend20: float
    trend60: float
    drawdown120: float
    vol_ratio: float
    capital: float

    @property
    def regime(self) -> str:
        if self.hv_percentile >= 0.68:
            return "high-volatility"
        if self.hv_percentile <= 0.32:
            return "low-volatility"
        return "balanced"

    @property
    def trend_label(self) -> str:
        if self.trend20 > 0.025:
            return "uptrend"
        if self.trend20 < -0.025:
            return "downtrend"
        return "sideways"

    def public_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset_symbol,
            "asset_name": self.asset_name,
            "scenario": self.scenario,
            "as_of": self.as_of.isoformat(),
            "spot": round(self.spot, 4),
            "hv30": round(self.hv30, 5),
            "hv_percentile": round(self.hv_percentile, 4),
            "trend20": round(self.trend20, 5),
            "trend60": round(self.trend60, 5),
            "drawdown120": round(self.drawdown120, 5),
            "vol_ratio": round(self.vol_ratio, 4),
            "regime": self.regime,
            "trend_label": self.trend_label,
            "capital": round(self.capital, 2),
        }


@dataclass
class AgentDecision:
    """A fully specified, reproducible mandate for one agent."""

    agent_key: str
    strategy_key: str
    tenor_days: int
    strike_offset_pct: float
    wing_width_pct: float
    basis_pct: float
    rationale: str
    source: str
    model: str

    @property
    def strategy_name(self) -> str:
        return STRATEGY_EDU_DB.get(self.strategy_key, {}).get("short", self.strategy_key)

    def public_dict(self) -> dict[str, Any]:
        return {
            "agent_key": self.agent_key,
            "strategy_key": self.strategy_key,
            "strategy_name": self.strategy_name,
            "tenor_days": self.tenor_days,
            "strike_offset_pct": round(self.strike_offset_pct, 2),
            "wing_width_pct": round(self.wing_width_pct, 2),
            "basis_pct": round(self.basis_pct, 2),
            "rationale": self.rationale,
            "source": self.source,
            "model": self.model,
        }


def _clamp(value: float, low: float, high: float) -> float:
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return low


def _base_offset(hv30: float) -> float:
    """ATR-ish strike distance: wider when realized volatility is high."""

    raw = _clamp(hv30 * 100.0 * 0.22, 3.0, 12.0)
    return round(raw * 2.0) / 2.0


def _tenor_for_regime(hv_percentile: float, base: int = 30) -> int:
    if hv_percentile >= 0.65:
        return 30
    if hv_percentile <= 0.35:
        return 60
    return base


def _rationale(agent: AgentPersona, context: MarketContext, strategy: str, offset: float) -> str:
    return (
        f"HV30 is {context.hv30 * 100:.1f}% at the {context.hv_percentile * 100:.0f}th "
        f"percentile; the 20-day trend is {context.trend20 * 100:+.1f}% and the regime is "
        f"{context.regime}. {STRATEGY_EDU_DB[strategy]['short']} at "
        f"{offset:+.1f}% from spot is the best fit for the {agent.role.lower()} mandate."
    )


def policy_decision(agent: AgentPersona, context: MarketContext) -> AgentDecision:
    """Deterministic, auditable policy used when no LLM is configured."""

    hv = context.hv_percentile
    trend = context.trend20
    base = _base_offset(context.hv30)
    strategy = "covered_call"
    tenor = 30
    offset = base
    wing = 5.0
    basis = 5.0

    if agent.key == "alpha":
        if hv >= 0.68 and trend >= 0:
            strategy, tenor, offset = "covered_call", 30, base
        elif hv <= 0.32:
            strategy, tenor, offset, wing = "iron_condor", 60, max(base, 4.0), 5.0
        elif trend <= -0.02 and hv >= 0.45:
            strategy, tenor, offset = "basis_trade", 90, 0.0
        elif abs(trend) < 0.025:
            strategy, tenor, offset = "basis_trade", 90, 0.0
        else:
            strategy, tenor, offset = "covered_call", _tenor_for_regime(hv), base
    elif agent.key == "volt":
        if hv >= 0.60:
            strategy, tenor, offset = "long_straddle", 30, 0.0
        elif hv <= 0.38:
            strategy, tenor, offset, wing = "iron_condor", _tenor_for_regime(hv, 60), max(base, 4.0), 5.0
        elif abs(trend) >= 0.05:
            strategy, tenor, offset = "long_straddle", 30, 0.0
        else:
            strategy, tenor, offset, wing = "iron_condor", 30, max(base, 4.0), 5.0
    else:  # BasisDyne: structural carry first, regardless of the equity regime
        strategy, tenor, offset = "basis_trade", 90, 0.0

    rationale = _rationale(agent, context, strategy, offset)
    return AgentDecision(
        agent_key=agent.key,
        strategy_key=strategy,
        tenor_days=tenor,
        strike_offset_pct=offset,
        wing_width_pct=wing,
        basis_pct=basis,
        rationale=rationale,
        source="policy",
        model=LOCAL_DECISION_MODEL,
    )


def normalize_agent_decision(
    raw: dict[str, Any] | None,
    agent: AgentPersona,
    context: MarketContext,
    *,
    source: str = "llm",
    model: str | None = None,
) -> AgentDecision:
    """Validate and clamp an LLM decision; fall back to policy on bad input."""

    fallback = policy_decision(agent, context)
    if not isinstance(raw, dict):
        return fallback
    strategy = str(raw.get("strategy_key") or raw.get("strategy") or "").strip().lower()
    if strategy not in STRATEGY_CHOICES:
        return fallback
    try:
        tenor = int(raw.get("tenor_days", fallback.tenor_days))
    except (TypeError, ValueError):
        tenor = fallback.tenor_days
    if tenor not in TENOR_CHOICES:
        tenor = fallback.tenor_days
    try:
        offset = float(raw.get("strike_offset_pct", fallback.strike_offset_pct))
    except (TypeError, ValueError):
        offset = fallback.strike_offset_pct
    offset = _clamp(offset, -25.0, 25.0)
    if strategy == "basis_trade":
        offset = 0.0
    elif strategy == "iron_condor":
        offset = _clamp(abs(offset), 2.0, 20.0)
    try:
        wing = float(raw.get("wing_width_pct", fallback.wing_width_pct))
    except (TypeError, ValueError):
        wing = fallback.wing_width_pct
    wing = _clamp(wing, 1.0, 10.0)
    try:
        basis = float(raw.get("basis_pct", fallback.basis_pct))
    except (TypeError, ValueError):
        basis = fallback.basis_pct
    basis = _clamp(basis, 0.0, 15.0)
    rationale = str(raw.get("rationale") or "").strip()
    if not rationale:
        rationale = fallback.rationale
    return AgentDecision(
        agent_key=agent.key,
        strategy_key=strategy,
        tenor_days=tenor,
        strike_offset_pct=offset,
        wing_width_pct=wing,
        basis_pct=basis,
        rationale=rationale[:320],
        source=source,
        model=model or LOCAL_DECISION_MODEL,
    )


DECISION_SYSTEM_PROMPT = """You are the DerivLab autonomous trading desk.
For each persona, choose one strategy and a small set of parameters using ONLY the
provided market context. Do not use future information. Do not invent prices.
Return ONLY a JSON object keyed by the persona key. Each value must contain:
  strategy_key: one of ["covered_call","cash_secured_put","basis_trade","long_straddle","iron_condor"]
  tenor_days: one of [30, 60, 90]
  strike_offset_pct: number from -25 to 25 (0 for basis and straddles)
  wing_width_pct: number from 1 to 10 (used by iron condors)
  basis_pct: number from 0 to 15 (used by basis trades)
  rationale: a short, specific sentence grounded in the supplied metrics.
Stay in character for each persona. Be conservative with leverage and respect the
mandate. No Markdown, no code fences, no commentary outside the JSON object."""


def build_decision_prompt(context: MarketContext, agents: tuple[AgentPersona, ...]) -> str:
    payload = {
        "market_context": context.public_dict(),
        "personas": [
            {
                "key": agent.key,
                "name": agent.name,
                "role": agent.role,
                "mandate": agent.mandate,
                "policy_bias": agent.policy_summary,
            }
            for agent in agents
        ],
        "allowed_strategies": list(STRATEGY_CHOICES),
        "allowed_tenors": list(TENOR_CHOICES),
        "decision_fields": [
            "strategy_key",
            "tenor_days",
            "strike_offset_pct",
            "wing_width_pct",
            "basis_pct",
            "rationale",
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _parse_llm_decisions(
    text: str,
    context: MarketContext,
    agents: tuple[AgentPersona, ...],
    model: str,
) -> dict[str, AgentDecision]:
    payload = extract_json_object(text) or {}
    decisions: dict[str, AgentDecision] = {}
    for agent in agents:
        raw = payload.get(agent.key)
        decisions[agent.key] = normalize_agent_decision(
            raw if isinstance(raw, dict) else None,
            agent,
            context,
            source="llm" if isinstance(raw, dict) else "policy",
            model=model,
        )
    return decisions


def decide_agents(
    context: MarketContext,
    settings: LLMSettings,
    client: LLMClient | None = None,
    *,
    use_llm: bool = True,
) -> tuple[list[AgentDecision], LLMResult | None]:
    """Choose mandates for all agents, optionally with one LLM call.

    One call covers all personas to keep cost and latency predictable. Any
    malformed or missing persona falls back to its deterministic policy.
    """

    baseline = {agent.key: policy_decision(agent, context) for agent in AGENTS}
    if not use_llm or client is None or not settings.enabled:
        return [baseline[agent.key] for agent in AGENTS], None

    prompt = build_decision_prompt(context, AGENTS)
    result = client.generate(
        DECISION_SYSTEM_PROMPT,
        prompt,
        role=ROLE_DECISION,
        max_tokens=900,
    )
    if not result.ok:
        return [baseline[agent.key] for agent in AGENTS], result
    parsed = _parse_llm_decisions(result.text, context, AGENTS, settings.decision_model)
    decisions = [parsed.get(agent.key) or baseline[agent.key] for agent in AGENTS]
    return decisions, result


def snapshot_context(
    *,
    asset_symbol: str,
    asset_name: str,
    scenario: str,
    as_of: date,
    spot: float,
    hv30: float,
    hv_percentile: float,
    trend20: float,
    trend60: float,
    drawdown120: float,
    vol_ratio: float,
    capital: float,
) -> MarketContext:
    """Build a context with safe defaults for cold-start scenarios."""

    return MarketContext(
        asset_symbol=asset_symbol,
        asset_name=asset_name,
        scenario=scenario,
        as_of=as_of,
        spot=max(float(spot), 0.0),
        hv30=max(float(hv30), 0.01),
        hv_percentile=_clamp(hv_percentile, 0.0, 1.0),
        trend20=float(trend20) if math.isfinite(trend20) else 0.0,
        trend60=float(trend60) if math.isfinite(trend60) else 0.0,
        drawdown120=float(drawdown120) if math.isfinite(drawdown120) else 0.0,
        vol_ratio=float(vol_ratio) if math.isfinite(vol_ratio) else 1.0,
        capital=max(float(capital), 0.0),
    )
