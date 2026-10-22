"""Black-Scholes pricing engine and option Greeks.

The engine is deliberately defensive: every public function accepts plausible
edge-case inputs (expired option, zero volatility, missing spot) and returns a
finite number instead of raising. Historical option chains do not exist in the
free data source, so the simulator synthesizes them at each simulation step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.stats import norm

from .config import IV_CAP, IV_FLOOR

_MIN_T = 1e-8
_MIN_SIGMA = 1e-6
_YEAR_DAYS = 365.0


@dataclass(frozen=True)
class Greeks:
    """Greeks normalized for a trading dashboard.

    delta: change in option price for a 1.00 move in spot.
    gamma: change in delta for a 1.00 move in spot.
    theta: change in option price per calendar day.
    vega: change in option price for a 1 volatility-point move (1%).
    rho: change in option price for a 1% move in the risk-free rate.
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


@dataclass(frozen=True)
class OptionMetrics:
    """Full theoretical snapshot for a single option contract."""

    kind: str
    spot: float
    strike: float
    years: float
    rate: float
    dividend_yield: float
    sigma: float
    price: float
    intrinsic: float
    time_value: float
    d1: float
    d2: float
    greeks: Greeks


def clamp_sigma(sigma: float) -> float:
    """Clamp a volatility input into the simulator's supported range."""
    try:
        value = float(sigma)
    except (TypeError, ValueError):
        return IV_FLOOR
    if not math.isfinite(value):
        return IV_FLOOR
    return float(min(max(value, IV_FLOOR), IV_CAP))


def estimate_iv(historical_volatility: float, multiplier: float = 1.0) -> float:
    """Convert a 30-day realized volatility into a synthetic implied volatility."""
    try:
        base = float(historical_volatility)
    except (TypeError, ValueError):
        base = IV_FLOOR
    if not math.isfinite(base) or base <= 0:
        base = IV_FLOOR
    return clamp_sigma(base * max(float(multiplier), 0.0))


def years_between(start: date, end: date) -> float:
    """ACT/365 year fraction; never negative."""
    return max((end - start).days / _YEAR_DAYS, 0.0)


def intrinsic_value(kind: str, spot: float, strike: float) -> float:
    """Intrinsic value of a call or put, floored at zero."""
    if spot <= 0 or strike <= 0:
        return max(strike - spot, 0.0) if str(kind).lower() == "put" else max(spot - strike, 0.0)
    if str(kind).lower() == "put":
        return max(float(strike) - float(spot), 0.0)
    return max(float(spot) - float(strike), 0.0)


def _d1_d2(spot: float, strike: float, years: float, rate: float, sigma: float, dividend_yield: float) -> tuple[float, float]:
    vol = max(float(sigma), _MIN_SIGMA)
    vad = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * vol * vol) * years) / vad
    return d1, d1 - vad


def black_scholes_metrics(
    kind: str,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    sigma: float,
    dividend_yield: float = 0.0,
) -> OptionMetrics:
    """Price one option and compute its Greeks.

    Inputs are sanitized; expired or degenerate contracts fall back to their
    deterministic intrinsic value. This keeps every GUI combination safe.
    """
    kind = "put" if str(kind).lower().startswith("p") else "call"
    try:
        spot = float(spot)
        strike = float(strike)
        years = float(years)
        rate = float(rate)
        sigma = float(sigma)
        dividend_yield = float(dividend_yield)
    except (TypeError, ValueError):
        spot, strike, years, rate, sigma, dividend_yield = 0.0, 0.0, 0.0, 0.0, IV_FLOOR, 0.0

    if not math.isfinite(spot) or spot <= 0 or not math.isfinite(strike) or strike <= 0:
        intrinsic = intrinsic_value(kind, max(spot, 0.0), max(strike, 0.0))
        return OptionMetrics(
            kind=kind,
            spot=max(spot, 0.0),
            strike=max(strike, 0.0),
            years=max(years, 0.0),
            rate=rate if math.isfinite(rate) else 0.0,
            dividend_yield=dividend_yield if math.isfinite(dividend_yield) else 0.0,
            sigma=clamp_sigma(sigma),
            price=intrinsic,
            intrinsic=intrinsic,
            time_value=0.0,
            d1=0.0,
            d2=0.0,
            greeks=Greeks(0.0, 0.0, 0.0, 0.0, 0.0),
        )

    if not math.isfinite(years) or years <= _MIN_T:
        intrinsic = intrinsic_value(kind, spot, strike)
        moneyness = 1.0 if spot > strike else (-1.0 if spot < strike else 0.0)
        if kind == "call":
            delta = 1.0 if moneyness > 0 else (0.5 if moneyness == 0 else 0.0)
        else:
            delta = -1.0 if moneyness < 0 else (-0.5 if moneyness == 0 else 0.0)
        return OptionMetrics(
            kind=kind,
            spot=spot,
            strike=strike,
            years=0.0,
            rate=rate,
            dividend_yield=dividend_yield,
            sigma=clamp_sigma(sigma),
            price=intrinsic,
            intrinsic=intrinsic,
            time_value=0.0,
            d1=0.0,
            d2=0.0,
            greeks=Greeks(delta, 0.0, 0.0, 0.0, 0.0),
        )

    rate = rate if math.isfinite(rate) else 0.0
    dividend_yield = dividend_yield if math.isfinite(dividend_yield) else 0.0
    sigma = clamp_sigma(sigma)
    d1, d2 = _d1_d2(spot, strike, years, rate, sigma, dividend_yield)
    discount_r = math.exp(-rate * years)
    discount_q = math.exp(-dividend_yield * years)
    sqrt_t = math.sqrt(years)
    pdf_d1 = float(norm.pdf(d1))
    cdf_d1 = float(norm.cdf(d1))
    cdf_d2 = float(norm.cdf(d2))

    if kind == "call":
        price = spot * discount_q * cdf_d1 - strike * discount_r * cdf_d2
        delta = discount_q * cdf_d1
        theta_annual = (
            -spot * discount_q * pdf_d1 * sigma / (2.0 * sqrt_t)
            - rate * strike * discount_r * cdf_d2
            + dividend_yield * spot * discount_q * cdf_d1
        )
        rho_annual = strike * years * discount_r * cdf_d2
    else:
        price = strike * discount_r * float(norm.cdf(-d2)) - spot * discount_q * float(norm.cdf(-d1))
        delta = -discount_q * float(norm.cdf(-d1))
        theta_annual = (
            -spot * discount_q * pdf_d1 * sigma / (2.0 * sqrt_t)
            + rate * strike * discount_r * float(norm.cdf(-d2))
            - dividend_yield * spot * discount_q * float(norm.cdf(-d1))
        )
        rho_annual = -strike * years * discount_r * float(norm.cdf(-d2))

    price = max(float(price), 0.0)
    intrinsic = intrinsic_value(kind, spot, strike)
    gamma = discount_q * pdf_d1 / max(spot * sigma * sqrt_t, 1e-12)
    vega = spot * discount_q * pdf_d1 * sqrt_t / 100.0
    greeks = Greeks(
        delta=float(delta),
        gamma=float(gamma),
        theta=float(theta_annual / _YEAR_DAYS),
        vega=float(vega),
        rho=float(rho_annual / 100.0),
    )
    return OptionMetrics(
        kind=kind,
        spot=spot,
        strike=strike,
        years=years,
        rate=rate,
        dividend_yield=dividend_yield,
        sigma=sigma,
        price=price,
        intrinsic=intrinsic,
        time_value=max(price - intrinsic, 0.0),
        d1=d1,
        d2=d2,
        greeks=greeks,
    )


def bs_price(
    kind: str,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    sigma: float,
    dividend_yield: float = 0.0,
) -> float:
    """Convenience wrapper returning only the theoretical price."""
    return black_scholes_metrics(kind, spot, strike, years, rate, sigma, dividend_yield).price


def bs_greeks(
    kind: str,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    sigma: float,
    dividend_yield: float = 0.0,
) -> Greeks:
    """Convenience wrapper returning only the Greeks."""
    return black_scholes_metrics(kind, spot, strike, years, rate, sigma, dividend_yield).greeks


def synthetic_futures_price(
    spot: float,
    years: float,
    rate: float,
    dividend_yield: float = 0.0,
    basis: float = 0.0,
) -> float:
    """Synthetic futures price using cost-of-carry plus an explicit basis.

    ``basis`` is an annualized decimal premium (for example 0.05 for 5%).
    It represents the extra contango observed in the futures market beyond
    pure financing. Positive values create a tradable basis for the demo.
    """
    try:
        spot = float(spot)
        years = max(float(years), 0.0)
        rate = float(rate)
        dividend_yield = float(dividend_yield)
        basis = float(basis)
    except (TypeError, ValueError):
        return max(float(spot) if spot else 0.0, 0.0)
    if not math.isfinite(spot) or spot <= 0:
        return 0.0
    exponent = rate - dividend_yield + basis
    exponent = float(np.clip(exponent, -1.0, 1.0))
    return float(spot * math.exp(exponent * years))


def implied_volatility(
    price: float,
    kind: str,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    dividend_yield: float = 0.0,
    lower: float = 0.001,
    upper: float = 5.0,
) -> float | None:
    """Invert the Black-Scholes price using Brent's method.

    Returns ``None`` when the price is outside the no-arbitrage bounds. The
    solver is not required by the demo screens, but it is useful for tests and
    for future "market-implied" extensions.
    """
    from scipy.optimize import brentq

    intrinsic = intrinsic_value(kind, spot, strike) * math.exp(-max(rate, 0.0) * years)
    if not math.isfinite(price) or price <= intrinsic + 1e-10:
        return None
    target = float(price)

    def objective(sigma: float) -> float:
        return bs_price(kind, spot, strike, years, rate, sigma, dividend_yield) - target

    try:
        if objective(lower) > 0:
            return lower
        if objective(upper) < 0:
            return upper
        return float(brentq(objective, lower, upper, maxiter=100, xtol=1e-8))
    except (ValueError, RuntimeError):
        return None
