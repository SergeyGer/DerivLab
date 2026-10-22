"""Strategy definitions, synthetic option-chain construction, and payoff maths.

Each strategy is reduced to a small set of synthetic legs. The same plan object
is used by the payoff chart, the historical backtester, and the interactive
stress-test game, so all screens stay economically consistent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import (
    DEFAULT_FEE_BPS,
    DEFAULT_TENOR_DAYS,
    IV_CAP,
    IV_FLOOR,
    MAX_CONTRACTS,
    STRATEGY_EDU_DB,
    STRATEGY_META,
    Asset,
    get_asset,
)
from .option_math import (
    OptionMetrics,
    black_scholes_metrics,
    estimate_iv,
    synthetic_futures_price,
)


@dataclass(frozen=True)
class StrategyConfig:
    """All user-controlled inputs needed to build and simulate a strategy."""

    strategy_key: str
    asset_symbol: str
    capital: float
    tenor_days: int = DEFAULT_TENOR_DAYS
    strike_offset_pct: float = 5.0
    iv_multiplier: float = 1.0
    risk_free: float = 0.04
    fee_bps: float = DEFAULT_FEE_BPS
    basis_pct: float = 5.0
    wing_width_pct: float = 5.0
    lookback_years: int = 5
    contracts: int | None = None

    @property
    def asset(self) -> Asset:
        return get_asset(self.asset_symbol)

    @property
    def fee_rate(self) -> float:
        return max(float(self.fee_bps), 0.0) / 10_000.0

    @property
    def tenor(self) -> int:
        return int(min(max(int(self.tenor_days), 7), 365))

    def with_contracts(self, contracts: int) -> StrategyConfig:
        return StrategyConfig(
            strategy_key=self.strategy_key,
            asset_symbol=self.asset_symbol,
            capital=float(self.capital),
            tenor_days=self.tenor_days,
            strike_offset_pct=self.strike_offset_pct,
            iv_multiplier=self.iv_multiplier,
            risk_free=self.risk_free,
            fee_bps=self.fee_bps,
            basis_pct=self.basis_pct,
            wing_width_pct=self.wing_width_pct,
            lookback_years=self.lookback_years,
            contracts=int(contracts),
        )


@dataclass(frozen=True)
class LegQuote:
    """One synthetic option leg, quoted per underlying unit."""

    kind: str
    qty: int
    strike: float
    expiry: date
    premium: float
    iv: float
    label: str
    metrics: OptionMetrics = field(repr=False, compare=False)

    @property
    def side(self) -> str:
        return "Long" if self.qty > 0 else "Short"


@dataclass
class PositionPlan:
    """A complete, sized position blueprint at a single market snapshot."""

    strategy_key: str
    asset: Asset
    config: StrategyConfig
    as_of: date
    spot: float
    iv: float
    contracts: int
    multiplier: float
    expiry: date
    legs: list[LegQuote]
    stock_units: float = 0.0
    futures_entry: float | None = None
    futures_expiry: date | None = None
    net_premium: float = 0.0
    entry_fees: float = 0.0
    entry_cash_flow: float = 0.0
    capital_used: float = 0.0
    max_profit: float | None = 0.0
    max_loss: float = 0.0
    breakevens: list[float] = field(default_factory=list)
    payoff_note: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def units(self) -> float:
        return float(self.contracts) * float(self.multiplier)

    @property
    def is_credit(self) -> bool:
        return self.net_premium > 0

    @property
    def option_value(self) -> float:
        return sum(leg.qty * leg.premium * self.multiplier * self.contracts for leg in self.legs)

    @property
    def net_delta(self) -> float:
        delta = self.stock_units
        for leg in self.legs:
            delta += leg.qty * leg.metrics.greeks.delta * self.multiplier * self.contracts
        return delta

    @property
    def net_theta(self) -> float:
        return sum(leg.qty * leg.metrics.greeks.theta * self.multiplier * self.contracts for leg in self.legs)

    @property
    def net_vega(self) -> float:
        return sum(leg.qty * leg.metrics.greeks.vega * self.multiplier * self.contracts for leg in self.legs)

    @property
    def net_gamma(self) -> float:
        return sum(leg.qty * leg.metrics.greeks.gamma * self.multiplier * self.contracts for leg in self.legs)

    @property
    def currency(self) -> str:
        return self.asset.currency

    def short_legs(self) -> list[LegQuote]:
        return [leg for leg in self.legs if leg.qty < 0]

    def long_legs(self) -> list[LegQuote]:
        return [leg for leg in self.legs if leg.qty > 0]


# ---------------------------------------------------------------------------
# Strikes and sizing
# ---------------------------------------------------------------------------


def _safe_offset(value: float, low: float = -80.0, high: float = 200.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return float(np.clip(value, low, high))


def _clamp(value: float, low: float, high: float) -> float:
    try:
        return float(np.clip(float(value), low, high))
    except (TypeError, ValueError):
        return low


def config_snapshot_key(config: StrategyConfig) -> tuple:
    """Hashable cache key for a strategy configuration."""
    return (
        config.strategy_key,
        config.asset_symbol,
        round(float(config.capital), 2),
        int(config.tenor_days),
        round(float(config.strike_offset_pct), 4),
        round(float(config.iv_multiplier), 4),
        round(float(config.risk_free), 5),
        round(float(config.fee_bps), 3),
        round(float(config.basis_pct), 4),
        round(float(config.wing_width_pct), 4),
        int(config.lookback_years),
        config.contracts,
    )


def _expiry_date(as_of: date, tenor_days: int) -> date:
    return as_of + timedelta(days=int(tenor_days))


def _quote_leg(
    kind: str,
    qty: int,
    strike: float,
    as_of: date,
    tenor_days: int,
    spot: float,
    rate: float,
    dividend_yield: float,
    iv: float,
    label: str,
) -> LegQuote:
    expiry = _expiry_date(as_of, tenor_days)
    metrics = black_scholes_metrics(
        kind=kind,
        spot=spot,
        strike=max(float(strike), 0.01),
        years=max(tenor_days, 1) / 365.0,
        rate=rate,
        sigma=iv,
        dividend_yield=dividend_yield,
    )
    return LegQuote(
        kind=kind,
        qty=int(qty),
        strike=float(max(strike, 0.01)),
        expiry=expiry,
        premium=float(metrics.price),
        iv=float(metrics.sigma),
        label=label,
        metrics=metrics,
    )


def _per_contract_credit(legs: list[LegQuote], multiplier: float) -> float:
    """Net cash received per simulated lot at inception (negative = debit)."""
    # Position quantity is signed: a short leg has qty=-1, and selling it
    # *receives* cash. Hence the negative sign on the signed position value.
    return float(-sum(leg.qty * leg.premium for leg in legs) * multiplier)


def _entry_fees(legs: list[LegQuote], contracts: int, multiplier: float, fee_rate: float) -> float:
    option_notional = sum(abs(leg.qty) * leg.premium for leg in legs) * contracts * multiplier
    return float(option_notional * fee_rate)


def size_position(
    strategy_key: str,
    capital: float,
    spot: float,
    multiplier: float,
    *,
    collateral_per_unit: float | None = None,
    debit_per_unit: float = 0.0,
    max_loss_per_unit: float = 0.0,
) -> int:
    """Convert a capital allocation into a whole number of simulated lots."""
    try:
        capital = max(float(capital), 0.0)
        spot = max(float(spot), 0.0)
        multiplier = max(float(multiplier), 1.0)
    except (TypeError, ValueError):
        return 0
    if capital <= 0 or spot <= 0:
        return 0

    unit_notional = max(float(collateral_per_unit or spot), 0.01) * multiplier
    lots = int(math.floor(capital / unit_notional + 1e-9))

    if strategy_key == "long_straddle" and debit_per_unit > 0:
        affordable = int(math.floor(capital / max(debit_per_unit * multiplier, 1e-9)))
        lots = min(lots, affordable)
    if strategy_key == "iron_condor" and max_loss_per_unit > 0:
        affordable = int(math.floor(capital / max(max_loss_per_unit * multiplier, 1e-9)))
        lots = min(lots, affordable)
    return int(min(max(lots, 0), MAX_CONTRACTS))


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------


def build_position_plan(
    config: StrategyConfig,
    spot: float,
    historical_volatility: float,
    as_of: date | pd.Timestamp,
    contracts: int | None = None,
) -> PositionPlan:
    """Build the full synthetic position for a strategy snapshot.

    The function is intentionally total: bad or missing inputs degrade into a
    zero-lot plan with a warning rather than an exception.
    """
    asset = config.asset
    as_of_date = pd.Timestamp(as_of).date() if not isinstance(as_of, date) else as_of
    spot = float(max(spot, 0.0))
    iv = estimate_iv(historical_volatility, config.iv_multiplier)
    rate = _clamp(config.risk_free, -0.02, 0.30)
    tenor = config.tenor
    offset_pct = _safe_offset(config.strike_offset_pct, -50.0, 50.0)
    offset = offset_pct / 100.0
    q = float(asset.dividend_yield)
    warnings: list[str] = []

    strategy = config.strategy_key
    if strategy not in STRATEGY_META:
        strategy = "covered_call"
    legs: list[LegQuote] = []
    stock_units = 0.0
    futures_entry: float | None = None
    futures_expiry: date | None = None
    expiry = _expiry_date(as_of_date, tenor)
    collateral_per_unit = spot
    debit_per_unit = 0.0
    max_loss_per_unit = 0.0
    payoff_note = ""

    if spot <= 0:
        warnings.append("No valid spot price is available for this snapshot.")

    if strategy == "basis_trade":
        basis = _clamp(config.basis_pct, 0.0, 30.0) / 100.0
        collateral_per_unit = spot
        futures_entry = synthetic_futures_price(spot, tenor / 365.0, rate, q, basis)
        futures_expiry = expiry
    elif strategy == "covered_call":
        strike = max(spot * (1.0 + offset), 0.01)
        legs = [
            _quote_leg("call", -1, strike, as_of_date, tenor, spot, rate, q, iv, f"Short call {strike:,.2f}")
        ]
        collateral_per_unit = spot
    elif strategy == "cash_secured_put":
        strike = max(spot * (1.0 + offset), 0.01)
        legs = [
            _quote_leg("put", -1, strike, as_of_date, tenor, spot, rate, q, iv, f"Short put {strike:,.2f}")
        ]
        collateral_per_unit = max(strike, spot * 0.5)
    elif strategy == "long_straddle":
        strike = max(spot * (1.0 + offset), 0.01)
        metrics_call = black_scholes_metrics("call", spot, strike, tenor / 365.0, rate, iv, q)
        metrics_put = black_scholes_metrics("put", spot, strike, tenor / 365.0, rate, iv, q)
        debit_per_unit = metrics_call.price + metrics_put.price
        legs = [
            _quote_leg("call", 1, strike, as_of_date, tenor, spot, rate, q, iv, f"Long call {strike:,.2f}"),
            _quote_leg("put", 1, strike, as_of_date, tenor, spot, rate, q, iv, f"Long put {strike:,.2f}"),
        ]
    elif strategy == "iron_condor":
        distance = _clamp(abs(offset_pct), 2.0, 40.0) / 100.0
        wing = _clamp(config.wing_width_pct, 1.0, 20.0) / 100.0
        if distance + wing > 0.9:
            wing = max(0.01, 0.9 - distance)
            warnings.append("Wing width was reduced to keep strikes above zero.")
        put_short_strike = max(spot * (1.0 - distance), 0.01)
        put_long_strike = max(spot * (1.0 - distance - wing), 0.01)
        call_short_strike = spot * (1.0 + distance)
        call_long_strike = spot * (1.0 + distance + wing)
        legs = [
            _quote_leg("put", -1, put_short_strike, as_of_date, tenor, spot, rate, q, iv, f"Short put {put_short_strike:,.2f}"),
            _quote_leg("put", 1, put_long_strike, as_of_date, tenor, spot, rate, q, iv, f"Long put wing {put_long_strike:,.2f}"),
            _quote_leg("call", -1, call_short_strike, as_of_date, tenor, spot, rate, q, iv, f"Short call {call_short_strike:,.2f}"),
            _quote_leg("call", 1, call_long_strike, as_of_date, tenor, spot, rate, q, iv, f"Long call wing {call_long_strike:,.2f}"),
        ]
        # A condor's capital at risk is the widest wing minus the credit.
        width = max(put_short_strike - put_long_strike, call_long_strike - call_short_strike)
        credit_per_unit = _per_contract_credit(legs, 1.0)
        max_loss_per_unit = max(width - credit_per_unit, 0.0)
        debit_per_unit = max(-credit_per_unit, 0.0)
        collateral_per_unit = spot

    # -- size the position -------------------------------------------------
    if contracts is None:
        contracts = config.contracts
    if contracts is None:
        sizing_collateral = collateral_per_unit
        if strategy in {"covered_call", "basis_trade"}:
            sizing_collateral = spot * (1.0 + config.fee_rate)
        elif strategy in {"cash_secured_put", "iron_condor"}:
            sizing_collateral = collateral_per_unit * (1.0 + config.fee_rate)
        contracts = size_position(
            strategy,
            config.capital,
            spot,
            asset.multiplier,
            collateral_per_unit=sizing_collateral,
            debit_per_unit=debit_per_unit * (1.0 + config.fee_rate),
            max_loss_per_unit=max_loss_per_unit * (1.0 + config.fee_rate),
        )
    contracts = int(min(max(int(contracts), 0), MAX_CONTRACTS))
    if contracts == 0:
        warnings.append(
            "The allocated capital is below the cost of one simulated lot. "
            "Increase capital to open a position."
        )

    units = contracts * asset.multiplier
    if strategy == "covered_call":
        stock_units = units

    net_premium = _per_contract_credit(legs, asset.multiplier) * contracts
    if strategy in {"covered_call", "basis_trade"}:
        capital_used = units * spot
    elif strategy == "cash_secured_put" and legs:
        capital_used = units * legs[0].strike
    elif strategy == "long_straddle":
        capital_used = units * debit_per_unit
    elif strategy == "iron_condor":
        capital_used = units * max_loss_per_unit
    else:
        capital_used = 0.0
    fees = _entry_fees(legs, contracts, asset.multiplier, config.fee_rate)
    if strategy == "covered_call":
        fees += stock_units * spot * config.fee_rate
    if strategy == "basis_trade":
        fees += units * spot * config.fee_rate

    entry_cash_flow = net_premium - stock_units * spot - fees
    if strategy == "basis_trade":
        entry_cash_flow = -units * spot - fees

    # -- payoff summary ----------------------------------------------------
    max_profit: float | None = 0.0
    max_loss = 0.0
    breakevens: list[float] = []
    if strategy == "basis_trade" and futures_entry is not None:
        locked = (futures_entry - spot) * units - fees
        max_profit = locked
        max_loss = min(locked, 0.0)
        collateral_per_unit = spot
        payoff_note = (
            "The payoff is flat at expiration: spot gains are offset by the "
            "short future. The profit is the captured basis, net of costs."
        )
    elif strategy == "covered_call" and legs:
        strike = legs[0].strike
        credit_unit = -legs[0].qty * legs[0].premium
        max_profit = ((strike - spot) + credit_unit) * units - fees
        max_loss = (credit_unit - spot) * units - fees
        breakevens = [spot - credit_unit] if spot - credit_unit > 0 else []
        payoff_note = "Upside is capped at the strike; downside follows the shares."
    elif strategy == "cash_secured_put" and legs:
        strike = legs[0].strike
        credit_unit = -legs[0].qty * legs[0].premium
        max_profit = credit_unit * units - fees
        max_loss = (credit_unit - strike) * units - fees
        breakevens = [strike - credit_unit] if strike - credit_unit > 0 else []
        payoff_note = "Below the strike you own the asset at the strike, less the premium."
    elif strategy == "long_straddle" and legs:
        debit_unit = sum(leg.qty * leg.premium for leg in legs)
        max_profit = None
        max_loss = -debit_unit * units - fees
        strike = legs[0].strike
        if debit_unit > 0:
            breakevens = [strike - debit_unit, strike + debit_unit]
        payoff_note = "Upside is unlimited; the debit paid is the defined maximum loss."
    elif strategy == "iron_condor" and len(legs) == 4:
        credit_unit = sum(-leg.qty * leg.premium if leg.qty < 0 else leg.premium for leg in legs)
        # Recompute explicitly for readability.
        credit_unit = (
            legs[0].premium - legs[1].premium + legs[2].premium - legs[3].premium
        )
        width = max(legs[0].strike - legs[1].strike, legs[3].strike - legs[2].strike)
        max_profit = credit_unit * units - fees
        max_loss = (credit_unit - width) * units - fees
        breakevens = []
        lower = legs[0].strike - credit_unit
        upper = legs[2].strike + credit_unit
        if credit_unit < width:
            breakevens = [lower, upper]
        payoff_note = "Profit inside the short strikes; loss capped by the long wings."
        collateral_per_unit = max(width, 0.01)

    plan = PositionPlan(
        strategy_key=strategy,
        asset=asset,
        config=config,
        as_of=as_of_date,
        spot=spot,
        iv=iv,
        contracts=contracts,
        multiplier=asset.multiplier,
        expiry=expiry,
        legs=legs,
        stock_units=stock_units,
        futures_entry=futures_entry,
        futures_expiry=futures_expiry,
        net_premium=float(net_premium),
        entry_fees=float(fees),
        entry_cash_flow=float(entry_cash_flow),
        capital_used=float(capital_used),
        max_profit=max_profit,
        max_loss=float(max_loss),
        breakevens=[float(b) for b in breakevens if math.isfinite(b) and b > 0],
        payoff_note=payoff_note,
        warnings=warnings,
    )
    return plan


# ---------------------------------------------------------------------------
# Payoff curve
# ---------------------------------------------------------------------------


def payoff_curve(plan: PositionPlan, points: int = 241, low_mult: float = 0.35, high_mult: float = 1.65) -> pd.DataFrame:
    """P&L at expiration across a range of terminal spot prices."""
    if plan.spot <= 0:
        empty = pd.DataFrame(columns=["price", "pnl", "unit_pnl", "spot_leg", "option_leg", "futures_leg"])
        return empty
    low = max(plan.spot * low_mult, 0.0)
    high = plan.spot * high_mult
    if plan.strategy_key == "long_straddle":
        high = plan.spot * 2.1
    prices = np.linspace(low, high, max(int(points), 25))
    spot = plan.spot
    units = plan.units
    fees = plan.entry_fees
    pnl = np.zeros_like(prices)
    spot_leg = np.zeros_like(prices)
    option_leg = np.zeros_like(prices)
    futures_leg = np.zeros_like(prices)

    if plan.strategy_key == "covered_call" and plan.legs:
        credit = -plan.legs[0].qty * plan.legs[0].premium
        spot_leg = (prices - spot) * units
        option_leg = -np.maximum(prices - plan.legs[0].strike, 0.0) * units + credit * units
        pnl = spot_leg + option_leg - fees
    elif plan.strategy_key == "cash_secured_put" and plan.legs:
        credit = -plan.legs[0].qty * plan.legs[0].premium
        option_leg = credit * units - np.maximum(plan.legs[0].strike - prices, 0.0) * units
        pnl = option_leg - fees
    elif plan.strategy_key == "long_straddle" and len(plan.legs) >= 2:
        debit = sum(leg.qty * leg.premium for leg in plan.legs)
        strike = plan.legs[0].strike
        option_leg = (np.maximum(prices - strike, 0.0) + np.maximum(strike - prices, 0.0) - debit) * units
        pnl = option_leg - fees
    elif plan.strategy_key == "iron_condor" and len(plan.legs) == 4:
        short_put, long_put, short_call, long_call = plan.legs
        credit = short_put.premium - long_put.premium + short_call.premium - long_call.premium
        option_leg = (
            credit
            - np.maximum(short_put.strike - prices, 0.0)
            + np.maximum(long_put.strike - prices, 0.0)
            - np.maximum(prices - short_call.strike, 0.0)
            + np.maximum(prices - long_call.strike, 0.0)
        ) * units
        pnl = option_leg - fees
    elif plan.strategy_key == "basis_trade" and plan.futures_entry is not None:
        spot_leg = (prices - spot) * units
        futures_leg = (plan.futures_entry - prices) * units
        pnl = spot_leg + futures_leg - fees
        # Option leg intentionally zero.
    else:
        pnl = np.zeros_like(prices) - fees

    return pd.DataFrame(
        {
            "price": prices,
            "pnl": pnl,
            "spot_leg": spot_leg,
            "option_leg": option_leg,
            "futures_leg": futures_leg,
        }
    )


def greeks_table(plan: PositionPlan) -> pd.DataFrame:
    """Human-readable Greek exposure table for the selected position."""
    rows: list[dict] = []
    if plan.stock_units:
        rows.append(
            {
                "Leg": f"Long shares ({plan.stock_units:,.0f})",
                "Type": "Spot",
                "Qty": plan.stock_units,
                "Strike": plan.spot,
                "Expiry": "—",
                "Premium": plan.spot,
                "IV": "—",
                "Delta": plan.stock_units,
                "Theta / day": 0.0,
                "Vega / pt": 0.0,
                "Notional": plan.stock_units * plan.spot,
            }
        )
    for leg in plan.legs:
        mult = plan.multiplier * plan.contracts
        rows.append(
            {
                "Leg": leg.label,
                "Type": leg.kind.capitalize(),
                "Qty": leg.qty * plan.contracts,
                "Strike": leg.strike,
                "Expiry": leg.expiry.isoformat(),
                "Premium": leg.premium,
                "IV": leg.iv,
                "Delta": leg.qty * leg.metrics.greeks.delta * mult,
                "Theta / day": leg.qty * leg.metrics.greeks.theta * mult,
                "Vega / pt": leg.qty * leg.metrics.greeks.vega * mult,
                "Notional": abs(leg.qty) * leg.premium * mult,
            }
        )
    if plan.strategy_key == "basis_trade" and plan.futures_entry is not None:
        rows.append(
            {
                "Leg": "Short synthetic future",
                "Type": "Futures",
                "Qty": -plan.contracts,
                "Strike": plan.futures_entry,
                "Expiry": plan.futures_expiry.isoformat() if plan.futures_expiry else "—",
                "Premium": plan.futures_entry,
                "IV": "—",
                "Delta": -plan.units,
                "Theta / day": 0.0,
                "Vega / pt": 0.0,
                "Notional": plan.units * plan.futures_entry,
            }
        )
        rows.insert(
            0,
            {
                "Leg": "Long spot",
                "Type": "Spot",
                "Qty": plan.units,
                "Strike": plan.spot,
                "Expiry": "—",
                "Premium": plan.spot,
                "IV": "—",
                "Delta": plan.units,
                "Theta / day": 0.0,
                "Vega / pt": 0.0,
                "Notional": plan.units * plan.spot,
            },
        )
    return pd.DataFrame(rows)


def strategy_label(key: str) -> str:
    return STRATEGY_EDU_DB.get(key, {}).get("label", key)


def strategy_short(key: str) -> str:
    return STRATEGY_EDU_DB.get(key, {}).get("short", key)


def derive_snapshot_iv(asset: Asset, hv: float, multiplier: float = 1.0) -> float:
    return min(max(estimate_iv(hv, multiplier), IV_FLOOR), IV_CAP)
