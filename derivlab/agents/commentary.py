"""AlphaVanguard performance reports and the cyberpunk NewsWire.

Both generators have a deterministic local implementation. When an LLM is
configured they request structured output and validate it before use; any error
or malformed response silently falls back to the local narrative.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from ..config import CURRENCY_SYMBOLS
from .llm import (
    LOCAL_CRITIC_MODEL,
    LOCAL_NEWS_MODEL,
    ROLE_CRITIC,
    ROLE_NEWS,
    LLMClient,
    LLMResult,
)
from .parsing import extract_json_array

REPORT_HEADINGS = (
    "### 📊 Performance Summary & Comparative Analysis",
    "### 🔍 Tactical Critique of User's Performance",
    "### 💡 Elite Quant Recommendation",
)

ALPHAVANGUARD_SYSTEM_PROMPT = """ROLE & PERSONA:
You are "AlphaVanguard AI", an elite, sharp, and data-driven quantitative hedge fund
manager competing directly against the user in an options/futures simulation market.
Your tone is professional, analytical, slightly competitive, and precise — resembling
a seasoned Wall Street portfolio manager or an elite crypto-quant. Avoid generic
platitudes; focus heavily on financial metrics, risk adjustments, and trading mechanics.

INPUT DATA:
You receive a JSON payload containing the selected strategy and asset, the user
portfolio, the AlphaVanguard rival portfolio, the full leaderboard, and the critical
historical triggers (IV spikes, strike breaches, assignments, drawdowns).

OUTPUT REQUIREMENTS:
Return a clean Markdown report with exactly these three sections, in this order:

### 📊 Performance Summary & Comparative Analysis
Briefly outline who won the simulation cycle. Directly compare your Sharpe Ratio and
capital efficiency against the user's metrics. Include a compact Markdown scoreboard.

### 🔍 Tactical Critique of User's Performance
Analyze how the user handled volatility shocks or strike breaches.
- If the user won: acknowledge superior execution but point out excessive risk-taking
  (for example a high Max Drawdown).
- If the user lost: explicitly diagnose the errors (poor rolling timing, failure to
  capture high implied-volatility premiums, holding a dying directional position in a
  crash, over-sized assignment risk, and so on).

### 💡 Elite Quant Recommendation
Provide one advanced, actionable tactical tip for the next execution: delta-neutral
hedging, ATR-scaled strike distance, dynamic stop-losses on option premiums, IV
percentile entry timing, or a comparable institutional technique.

RULES:
- Use only the supplied numbers. Never invent prices, dates, or trades.
- Be direct and specific; no boilerplate disclaimers.
- Do not output JSON, code fences, or any section outside the three headings.
- Keep the report under 420 words.
"""

NEWS_SYSTEM_PROMPT = """You are NewsWire 2077, a cyberpunk financial newswire embedded in
the DerivLab trading terminal. You receive a JSON payload about a completed AI Arena
cycle: user and rival metrics, the winner, model names, and critical market triggers.

Write exactly 4 punchy news items. They should sound like an institutional market wire
from a neon-lit future: crisp, data-driven, slightly dramatic, never silly. Reference
real supplied metrics, dates, strikes, or model names. Do not invent facts. No investment
advice.

Return ONLY a JSON array. Each item must be an object with:
  "tag": a short uppercase wire tag such as "NEON TAPE" or "STRIKE SHOCK"
  "headline": at most 90 characters
  "detail": one or two sentences, at most 220 characters
  "severity": "high", "medium", or "low"
No Markdown, no code fences, no prose outside the array.
"""


@dataclass
class ArenaReport:
    markdown: str
    model: str
    provider: str
    source: str
    ok: bool = True
    error: str = ""
    latency_ms: int = 0

    @property
    def used_llm(self) -> bool:
        return self.source == "llm" and self.ok

    def public_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "source": self.source,
            "ok": self.ok,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


@dataclass
class NewsItem:
    tag: str
    headline: str
    detail: str
    severity: str = "medium"
    timestamp: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "headline": self.headline,
            "detail": self.detail,
            "severity": self.severity,
            "timestamp": self.timestamp,
        }


@dataclass
class NewsBundle:
    items: list[NewsItem] = field(default_factory=list)
    model: str = LOCAL_NEWS_MODEL
    provider: str = "local"
    source: str = "local"
    ok: bool = True
    error: str = ""
    latency_ms: int = 0

    @property
    def used_llm(self) -> bool:
        return self.source == "llm" and self.ok

    def public_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "source": self.source,
            "ok": self.ok,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "items": [item.public_dict() for item in self.items],
        }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _pct(value: Any, digits: int = 1) -> str:
    number = _f(value) * 100.0
    return f"{number:+.{digits}f}%"


def _abs_pct(value: Any, digits: int = 1) -> str:
    return f"{_f(value) * 100.0:.{digits}f}%"


def _money(value: Any, currency: str = "USD") -> str:
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    amount = _f(value)
    if abs(amount) >= 1_000_000:
        return f"{symbol}{amount / 1_000_000:.2f}M"
    if abs(amount) >= 1_000:
        return f"{symbol}{amount / 1_000:.1f}K"
    return f"{symbol}{amount:,.0f}"


def _snapshot(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _desk_name(snapshot: dict[str, Any], fallback: str = "Desk") -> str:
    return str(snapshot.get("name") or fallback)


def _winner_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    winner = _snapshot(payload.get("winner"))
    if winner:
        return winner
    leaderboard = payload.get("leaderboard") or []
    if isinstance(leaderboard, list) and leaderboard:
        return max(leaderboard, key=lambda item: _f(item.get("score")))
    return _snapshot(payload.get("ai_rival_portfolio"))


def _triggers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    triggers = payload.get("critical_historical_triggers") or []
    return [item for item in triggers if isinstance(item, dict)]


def _friendly_kind(kind: Any) -> tuple[str, str]:
    text = str(kind or "event").replace("_", " ").strip()
    lower = text.lower()
    if lower == "iv spike":
        text = "IV spike"
    article = "an" if lower[:1] in {"a", "e", "i", "o", "u"} else "a"
    return article, text


def _trigger_sentence(payload: dict[str, Any]) -> str:
    triggers = _triggers(payload)
    if not triggers:
        return "No strike breach or volatility shock was recorded during the cycle."
    first = triggers[0]
    article, kind = _friendly_kind(first.get("kind", "event"))
    date = str(first.get("date", "—"))
    detail = str(first.get("detail", "")).strip()
    return f"The tape recorded {article} {kind} on {date}: {detail}"


# ---------------------------------------------------------------------------
# Local report
# ---------------------------------------------------------------------------


def local_report(payload: dict[str, Any]) -> str:
    user = _snapshot(payload.get("user_portfolio"))
    rival = _snapshot(payload.get("ai_rival_portfolio"))
    winner = _winner_from_payload(payload)
    selected = _snapshot(payload.get("selected_strategy_asset"))
    triggers = _triggers(payload)
    currency = str(selected.get("currency", "USD"))
    strategy = str(selected.get("strategy", "strategy"))
    asset = str(selected.get("asset", "the asset"))
    scenario = str(selected.get("scenario", "the scenario"))

    user_return = _f(user.get("return"))
    rival_return = _f(rival.get("return"))
    winner_return = _f(winner.get("return"))
    user_dd = _abs_pct(user.get("max_drawdown"))
    rival_dd = _abs_pct(rival.get("max_drawdown"))
    user_sharpe = _f(user.get("sharpe"))
    rival_sharpe = _f(rival.get("sharpe"))
    user_premium = _money(user.get("premium"), currency)
    rival_premium = _money(rival.get("premium"), currency)
    user_rank = user.get("rank", "—")
    winner_name = _desk_name(winner, "the rival desk")
    user_won = user_return >= winner_return
    beat_rival = user_return >= rival_return
    gap = user_return - rival_return

    summary_lines = [
        REPORT_HEADINGS[0],
        "",
        (
            f"**{winner_name}** won the {scenario} cycle on {asset} with "
            f"{_pct(winner_return)} while the user desk finished at {_pct(user_return)} "
            f"(rank {user_rank}). AlphaVanguard AI delivered {_pct(rival_return)}."
        ),
        "",
        "| Desk | Return | Max DD | Sharpe | Premium |",
        "|---|---:|---:|---:|---:|",
        (
            f"| You · {strategy} | {_pct(user_return)} | {user_dd} | {user_sharpe:.2f} | "
            f"{user_premium} |"
        ),
        (
            f"| AlphaVanguard AI | {_pct(rival_return)} | {rival_dd} | {rival_sharpe:.2f} | "
            f"{rival_premium} |"
        ),
    ]
    leaderboard = payload.get("leaderboard") or []
    for item in leaderboard:
        if not isinstance(item, dict):
            continue
        if item.get("is_user"):
            continue
        if str(item.get("name", "")) == "AlphaVanguard AI":
            continue
        summary_lines.append(
            f"| {item.get('name', 'Agent')} | {_pct(item.get('return'))} | "
            f"{_abs_pct(item.get('max_drawdown'))} | {_f(item.get('sharpe')):.2f} | "
            f"{_money(item.get('premium'), currency)} |"
        )
    if winner_name and winner_name != "AlphaVanguard AI":
        summary_lines.extend(
            [
                "",
                (
                    f"The cross-desk winner was **{winner_name}**. The user's return gap to "
                    f"AlphaVanguard was {gap * 100:+.1f} percentage points; the Sharpe gap was "
                    f"{user_sharpe - rival_sharpe:+.2f}."
                ),
            ]
        )
    else:
        summary_lines.extend(
            [
                "",
                (
                    f"Versus AlphaVanguard, the return gap was {gap * 100:+.1f} percentage "
                    f"points and the Sharpe gap was {user_sharpe - rival_sharpe:+.2f}."
                ),
            ]
        )

    critique: list[str] = [REPORT_HEADINGS[1], ""]
    if user_won:
        critique.append(
            f"You won the cycle, and that execution deserves credit. "
            f"Your {_pct(user_return)} return carried a {user_dd} maximum drawdown versus "
            f"{rival_dd} for AlphaVanguard."
        )
        if _f(user.get("max_drawdown")) > _f(rival.get("max_drawdown")) + 0.03:
            critique.append(
                "The relative win was not free: you accepted materially more peak-to-trough risk. "
                "In a repeat cycle, size the book so a single volatility shock cannot erase "
                "the premium you collected."
            )
        elif _f(user.get("premium_yield")) < _f(rival.get("premium_yield")):
            critique.append(
                "Your premium yield lagged the rival desk. You left income on the table while "
                "taking comparable risk, which is the quietest way to underperform."
            )
        else:
            critique.append(
                "The remaining improvement is consistency: convert this result into repeatable "
                "risk-adjusted yield rather than a one-off relative outperformance."
            )
    else:
        reasons: list[str] = []
        if beat_rival:
            reasons.append(
                f"You edged AlphaVanguard by {gap * 100:+.1f} points, but the cycle belonged to "
                f"{winner_name} at {_pct(winner_return)}. The miss was cross-desk, not just "
                "relative to your primary rival."
            )
        elif user_return < rival_return:
            reasons.append(
                f"AlphaVanguard finished {abs(gap) * 100:.1f} points ahead on return; your "
                f"{strategy.lower()} mandate did not monetize the regime as efficiently."
            )
        if _f(user.get("max_drawdown")) > _f(rival.get("max_drawdown")) + 0.02:
            reasons.append(
                f"Your maximum drawdown reached {user_dd} versus {rival_dd}. Risk control, "
                "not signal quality, was the first leak in the P&L."
            )
        if user_sharpe < rival_sharpe:
            reasons.append(
                f"Sharpe of {user_sharpe:.2f} trailed the rival's {rival_sharpe:.2f}; the "
                "book was not paid enough for the volatility it carried."
            )
        if _f(user.get("premium_yield")) < _f(rival.get("premium_yield")):
            reasons.append(
                f"Premium collected of {user_premium} under-used the available implied "
                "volatility, especially around the recorded shocks."
            )
        if not reasons:
            reasons.append(
                "The desk lost on execution details rather than on the macro view; compare "
                "the trigger timeline against your strike spacing and roll timing."
            )
        critique.extend(reasons)
    critique.append("")
    critique.append(_trigger_sentence(payload))
    if len(triggers) > 1:
        second = triggers[1]
        article, kind = _friendly_kind(second.get("kind", "event"))
        critique.append(
            f"A second critical marker was {article} {kind} on "
            f"{str(second.get('date', '—'))}: {str(second.get('detail', '')).strip()}"
        )

    recommendation = [REPORT_HEADINGS[2], ""]
    strategy_key = str(selected.get("strategy_key", ""))
    tips = {
        "covered_call": (
            "Scale strike distance with ATR or a 1-sigma move, not a fixed percentage. "
            "Roll up when the short call delta approaches 0.35 and harvest the credit into "
            "the next expiry instead of accepting assignment by default."
        ),
        "cash_secured_put": (
            "Budget collateral at the portfolio level and cap assignment risk per name. "
            "Roll down and out when the short put delta exceeds 0.40, and only sell puts "
            "when the IV percentile is above its 6-month median."
        ),
        "basis_trade": (
            "Stagger futures expiries to avoid a single convergence date and monitor the "
            "funding/margin ladder. Treat the basis as a carry book: size it so a 2-sigma "
            "spot move cannot force a forced unwind."
        ),
        "long_straddle": (
            "Enter long volatility only when the IV percentile is below its realized-move "
            "breakeven, and scale out on vega before the final two weeks. Gamma is only "
            "valuable when the move arrives before theta consumes the debit."
        ),
        "iron_condor": (
            "Place short strikes near the 1-sigma expected move, size wings to cap the "
            "maximum loss at 1-2% of capital, and manage the position at 50% of maximum "
            "credit. Do not sell a condor into a rising IV percentile."
        ),
    }
    recommendation.append(
        tips.get(
            strategy_key,
            "Anchor strike distance to realized volatility, pre-commit the roll rules, and "
            "measure every cycle by return per unit of maximum drawdown rather than by premium "
            "collected alone.",
        )
    )
    recommendation.extend(
        [
            "",
            (
                f"Next-cycle monitor: watch the {str(selected.get('asset', 'asset'))} IV percentile "
                f"and the distance to the short strike. {_trigger_sentence(payload)}"
            ),
        ]
    )

    return "\n".join(summary_lines + [""] + critique + [""] + recommendation).strip()


def validate_report(text: str) -> bool:
    return bool(text) and all(heading in text for heading in REPORT_HEADINGS)


def generate_report(payload: dict[str, Any], client: LLMClient | None = None) -> ArenaReport:
    """Generate the AlphaVanguard report, with a guaranteed local fallback."""

    fallback = local_report(payload)
    if client is None or not client.settings.enabled:
        return ArenaReport(
            markdown=fallback,
            model=LOCAL_CRITIC_MODEL,
            provider="local",
            source="local",
            ok=True,
        )

    result: LLMResult = client.generate(
        ALPHAVANGUARD_SYSTEM_PROMPT,
        json.dumps(payload, indent=2, default=str),
        role=ROLE_CRITIC,
        max_tokens=1100,
    )
    if not result.ok:
        return ArenaReport(
            markdown=fallback,
            model=LOCAL_CRITIC_MODEL,
            provider=client.settings.provider,
            source="local",
            ok=True,
            error=result.error or "LLM request failed; local critic used.",
        )
    if not validate_report(result.text):
        return ArenaReport(
            markdown=fallback,
            model=LOCAL_CRITIC_MODEL,
            provider=client.settings.provider,
            source="local",
            ok=True,
            error="LLM response did not contain the required three sections; local critic used.",
        )
    return ArenaReport(
        markdown=result.text.strip(),
        model=result.model,
        provider=result.provider,
        source="llm",
        ok=True,
        latency_ms=result.latency_ms,
    )


# ---------------------------------------------------------------------------
# News wire
# ---------------------------------------------------------------------------


def _news_timestamp(payload: dict[str, Any]) -> str:
    selected = _snapshot(payload.get("selected_strategy_asset"))
    window = selected.get("window") or selected.get("as_of") or ""
    text = str(window)
    if "→" in text:
        return text.split("→")[-1].strip()
    return text or "LIVE"


def local_news(payload: dict[str, Any]) -> list[NewsItem]:
    user = _snapshot(payload.get("user_portfolio"))
    rival = _snapshot(payload.get("ai_rival_portfolio"))
    winner = _winner_from_payload(payload)
    selected = _snapshot(payload.get("selected_strategy_asset"))
    model_stack = payload.get("model_stack") or []
    triggers = _triggers(payload)
    timestamp = _news_timestamp(payload)
    currency = str(selected.get("currency", "USD"))
    asset = str(selected.get("asset", "the asset"))
    user_return = _f(user.get("return"))
    winner_return = _f(winner.get("return"))
    rival_return = _f(rival.get("return"))
    winner_name = _desk_name(winner, "Rival desk")
    critic_model = "local critic"
    news_model = "local newswire"
    if isinstance(model_stack, list):
        for item in model_stack:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).lower()
            if "critic" in role:
                critic_model = str(item.get("model", critic_model))
            elif "news" in role:
                news_model = str(item.get("model", news_model))

    items: list[NewsItem] = [
        NewsItem(
            tag="NEON TAPE",
            headline=f"{winner_name.upper()} TAKES THE {asset} CYCLE",
            detail=(
                f"{winner_name} closes at {_pct(winner_return)} while the user desk prints "
                f"{_pct(user_return)}. AlphaVanguard AI marks {_pct(rival_return)}."
            ),
            severity="high" if winner_return > 0.1 else "medium",
            timestamp=timestamp,
        ),
        NewsItem(
            tag="DESK WATCH",
            headline=(
                f"USER DRAWDOWN {_abs_pct(user.get('max_drawdown'))} AS PREMIUM BOOK "
                f"PRINTS {_money(user.get('premium'), currency)}"
            ),
            detail=(
                "The terminal flags risk-adjusted efficiency as the next battlefield: return "
                f"{_pct(user_return)}, Sharpe {_f(user.get('sharpe')):.2f}."
            ),
            severity="high" if _f(user.get("max_drawdown")) > 0.15 else "medium",
            timestamp=timestamp,
        ),
    ]
    if triggers:
        trigger = triggers[0]
        trigger_kind = str(trigger.get("kind", "risk")).lower()
        tag = {
            "iv_spike": "VOLTAGE SPIKE",
            "assignment": "ASSIGNMENT ALERT",
            "breach": "STRIKE SHOCK",
            "drawdown": "DRAWDOWN WATCH",
        }.get(trigger_kind, "STRIKE SHOCK")
        items.append(
            NewsItem(
                tag=tag,
                headline=(
                    f"{asset.upper()} EVENT: {str(trigger.get('kind', 'RISK')).replace('_', ' ').upper()} "
                    f"ON {str(trigger.get('date', '—'))}"
                ),
                detail=str(trigger.get("detail", ""))[:220] or "A critical market trigger fired.",
                severity=str(trigger.get("severity", "high")),
                timestamp=str(trigger.get("date", timestamp)),
            )
        )
    else:
        items.append(
            NewsItem(
                tag="CLEAN TAPE",
                headline=f"{asset.upper()} CYCLE CLOSES WITHOUT STRIKE BREACH",
                detail="No critical strike or assignment trigger was recorded by the rival desk.",
                severity="low",
                timestamp=timestamp,
            )
        )
    items.append(
        NewsItem(
            tag="GHOST IN THE MACHINE",
            headline="AI DESKS SIGN THE CYCLE",
            detail=(
                f"Critic {critic_model} and wire model {news_model} stamp the closing tape. "
                "Three autonomous mandates, one market."
            ),
            severity="low",
            timestamp=timestamp,
        )
    )
    return items[:4]


def _normalize_news_item(raw: Any, timestamp: str) -> NewsItem | None:
    if not isinstance(raw, dict):
        return None
    tag = str(raw.get("tag") or "WIRE").strip().upper()[:24]
    headline = str(raw.get("headline") or "").strip()
    detail = str(raw.get("detail") or "").strip()
    if not headline or not detail:
        return None
    severity = str(raw.get("severity") or "medium").strip().lower()
    if severity not in {"high", "medium", "low"}:
        severity = "medium"
    return NewsItem(
        tag=tag,
        headline=headline[:120],
        detail=detail[:260],
        severity=severity,
        timestamp=timestamp,
    )


def generate_news(payload: dict[str, Any], client: LLMClient | None = None) -> NewsBundle:
    fallback = local_news(payload)
    timestamp = _news_timestamp(payload)
    if client is None or not client.settings.enabled:
        return NewsBundle(items=fallback, source="local", provider="local", ok=True)

    result = client.generate(
        NEWS_SYSTEM_PROMPT,
        json.dumps(payload, indent=2, default=str),
        role=ROLE_NEWS,
        max_tokens=700,
    )
    if not result.ok:
        return NewsBundle(
            items=fallback,
            model=LOCAL_NEWS_MODEL,
            provider=client.settings.provider,
            source="local",
            ok=True,
            error=result.error or "LLM request failed; local newswire used.",
        )
    raw_items = extract_json_array(result.text)
    if not raw_items:
        return NewsBundle(
            items=fallback,
            model=LOCAL_NEWS_MODEL,
            provider=client.settings.provider,
            source="local",
            ok=True,
            error="LLM response was not a JSON array; local newswire used.",
        )
    items = [item for item in (_normalize_news_item(raw, timestamp) for raw in raw_items) if item]
    if len(items) < 3:
        return NewsBundle(
            items=fallback,
            model=LOCAL_NEWS_MODEL,
            provider=client.settings.provider,
            source="local",
            ok=True,
            error="LLM returned too few valid news items; local newswire used.",
        )
    return NewsBundle(
        items=items[:5],
        model=result.model,
        provider=result.provider,
        source="llm",
        ok=True,
        latency_ms=result.latency_ms,
    )
