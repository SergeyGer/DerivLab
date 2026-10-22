"""Performance analytics and the Hold-the-Position scoring model."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import TRADING_DAYS


def _finite(value: float | None, default: float = 0.0) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def daily_returns(nav: pd.Series | list[float] | np.ndarray) -> pd.Series:
    series = pd.Series(nav, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 2:
        return pd.Series(dtype=float)
    returns = series.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    return returns.clip(lower=-0.9999)


def total_return(nav: pd.Series | list[float] | np.ndarray) -> float:
    series = pd.Series(nav, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 2 or series.iloc[0] == 0:
        return 0.0
    return _finite(series.iloc[-1] / series.iloc[0] - 1.0)


def cagr(nav: pd.Series | list[float] | np.ndarray, periods: int | None = None) -> float:
    series = pd.Series(nav, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(series) < 2 or series.iloc[0] <= 0:
        return 0.0
    n = int(periods or max(len(series) - 1, 1))
    years = max(n / TRADING_DAYS, 1.0 / TRADING_DAYS)
    ratio = series.iloc[-1] / series.iloc[0]
    if ratio <= 0:
        return -1.0
    return _finite(ratio ** (1.0 / years) - 1.0)


def drawdown_series(nav: pd.Series | list[float] | np.ndarray) -> pd.Series:
    series = pd.Series(nav, dtype=float).replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0)
    if series.empty:
        return series
    peak = series.cummax().replace(0, np.nan).ffill().fillna(1.0)
    return (series / peak - 1.0).clip(upper=0.0)


def max_drawdown(nav: pd.Series | list[float] | np.ndarray) -> float:
    dd = drawdown_series(nav)
    if dd.empty:
        return 0.0
    return float(abs(dd.min()))


def annualized_volatility(returns: pd.Series) -> float:
    clean = pd.Series(returns, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 2:
        return 0.0
    return _finite(clean.std(ddof=1) * math.sqrt(TRADING_DAYS))


def _safe_ratio(value: float, limit: float = 99.0) -> float:
    value = _finite(value)
    return float(max(-limit, min(limit, value)))


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    clean = pd.Series(returns, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3:
        return 0.0
    daily_rf = (1.0 + max(risk_free, -0.99)) ** (1.0 / TRADING_DAYS) - 1.0
    excess = clean - daily_rf
    std = excess.std(ddof=1)
    if std <= 1e-10 or not math.isfinite(float(std)):
        return 0.0
    return _safe_ratio(float(excess.mean() / std * math.sqrt(TRADING_DAYS)))


def sortino_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    clean = pd.Series(returns, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3:
        return 0.0
    daily_rf = (1.0 + max(risk_free, -0.99)) ** (1.0 / TRADING_DAYS) - 1.0
    excess = clean - daily_rf
    downside = excess[excess < 0]
    if downside.empty or float(downside.std(ddof=1) or 0.0) <= 1e-10:
        return 0.0
    dstd = downside.std(ddof=1)
    if dstd <= 1e-10 or not math.isfinite(float(dstd)):
        return 0.0
    return _safe_ratio(float(excess.mean() / dstd * math.sqrt(TRADING_DAYS)))


def _as_float_series(values: pd.Series | list[float] | None) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    if isinstance(values, pd.Series):
        series = values
    else:
        try:
            series = pd.Series(list(values), dtype=float)
        except TypeError:
            series = pd.Series([values], dtype=float)
    return pd.Series(series, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()


def win_rate(cycle_pnls: pd.Series | list[float] | None) -> float:
    series = _as_float_series(cycle_pnls)
    if series.empty:
        return 0.0
    return float((series > 0).mean())


def profit_factor(cycle_pnls: pd.Series | list[float] | None) -> float:
    series = _as_float_series(cycle_pnls)
    if series.empty:
        return 0.0
    gains = float(series[series > 0].sum())
    losses = float(abs(series[series < 0].sum()))
    if losses <= 1e-12:
        return 0.0 if gains <= 0 else 99.0
    return gains / losses


def exposure_ratio(capital_used: float, capital: float) -> float:
    if capital <= 0:
        return 0.0
    return _finite(max(capital_used, 0.0) / capital)


@dataclass
class PerformanceSummary:
    total_return: float
    cagr: float
    max_drawdown: float
    sharpe: float
    sortino: float
    volatility: float
    win_rate: float
    profit_factor: float
    premium_yield: float
    capital_efficiency: float
    calmar: float


def summarize(
    nav: pd.Series,
    cycle_pnls: pd.Series | list[float] | None,
    premium_collected: float,
    capital: float,
    risk_free: float = 0.0,
    max_capital_used: float | None = None,
) -> PerformanceSummary:
    series = pd.Series(nav, dtype=float).replace([np.inf, -np.inf], np.nan).ffill().dropna()
    returns = daily_returns(series)
    total = total_return(series)
    md = max_drawdown(series)
    growth = cagr(series)
    efficiency = total / max(md, 0.01) if total > 0 else 0.0
    premium_yield = premium_collected / capital if capital > 0 else 0.0
    return PerformanceSummary(
        total_return=total,
        cagr=growth,
        max_drawdown=md,
        sharpe=sharpe_ratio(returns, risk_free),
        sortino=sortino_ratio(returns, risk_free),
        volatility=annualized_volatility(returns),
        win_rate=win_rate(cycle_pnls),
        profit_factor=profit_factor(cycle_pnls),
        premium_yield=premium_yield,
        capital_efficiency=efficiency if math.isfinite(efficiency) else 0.0,
        calmar=(growth / md) if md > 1e-9 else 0.0,
    )


# ---------------------------------------------------------------------------
# Interactive stress-test scoring
# ---------------------------------------------------------------------------


@dataclass
class ScoreCard:
    score: int
    badge: str
    tagline: str
    breakdown: list[tuple[str, float, str]] = field(default_factory=list)


_BADGES = {
    "Yield Generator": "Your premium engine kept the book productive while keeping risk contained.",
    "Prudent Hedger": "You prioritised capital preservation and let the hedge do its job.",
    "Liquidated Speculator": "You cut a losing position. The lesson: the exit is part of the strategy.",
    "Volatility Architect": "You expressed a view on volatility and managed the exposure with intent.",
    "Basis Mechanic": "You harvested the carry and kept the directional risk neutralized.",
    "Risk Apprentice": "The market asked hard questions. Review the decisions and run it again.",
    "Steady Operator": "A balanced run: controlled risk, a modest edge, and no heroics.",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_game(
    total_return_pct: float,
    max_drawdown_pct: float,
    premium_yield_pct: float,
    *,
    strategy_key: str,
    reason: str,
    liquidated: bool = False,
    assigned: bool = False,
) -> ScoreCard:
    """Convert a game outcome into a 0-100 score and a thematic badge.

    All percentage arguments are expressed as rates (0.12 = 12%).
    """
    ret = _clamp(_finite(total_return_pct), -0.75, 0.75)
    dd = _clamp(abs(_finite(max_drawdown_pct)), 0.0, 1.0)
    premium = max(_finite(premium_yield_pct), 0.0)

    return_points = 38.0 * math.tanh(ret / 0.12)
    drawdown_points = 18.0 * (1.0 - min(dd / 0.20, 1.0))
    premium_points = 10.0 * math.tanh(premium / 0.02)
    score = 45.0 + return_points + drawdown_points + premium_points
    if liquidated:
        score -= 8.0
    if assigned:
        score -= 3.0
    score_int = int(round(_clamp(score, 0.0, 100.0)))

    if liquidated and ret < 0:
        badge = "Liquidated Speculator"
    elif strategy_key in {"long_straddle", "iron_condor"} and ret > 0.08:
        badge = "Volatility Architect"
    elif strategy_key == "basis_trade" and ret >= 0 and dd < 0.12:
        badge = "Basis Mechanic"
    elif premium > 0.002 and dd < 0.10 and ret >= 0:
        badge = "Yield Generator"
    elif dd < 0.06 and ret >= 0:
        badge = "Prudent Hedger"
    elif score_int < 50:
        badge = "Risk Apprentice"
    else:
        badge = "Steady Operator"

    breakdown = [
        ("Directional P&L", return_points, f"{ret * 100:+.1f}% total return"),
        ("Drawdown control", drawdown_points, f"{dd * 100:.1f}% maximum drawdown"),
        ("Premium efficiency", premium_points, f"{premium * 100:.2f}% premium yield"),
    ]
    if liquidated:
        breakdown.append(("Early exit penalty", -8.0, "Position liquidated before expiry"))
    if assigned:
        breakdown.append(("Assignment adjustment", -3.0, "Position ended in assignment"))
    return ScoreCard(score=score_int, badge=badge, tagline=_BADGES[badge], breakdown=breakdown)
