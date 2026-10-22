"""Event-driven backtester for synthetic option strategies.

Backtrader supplies the event loop, the data feed, and the expiration clock.
Option legs are priced by the Black-Scholes engine at every bar; the portfolio
ledger tracks cash, spot, synthetic options, and synthetic futures explicitly.
A direct-loop fallback keeps the demo alive even if a future Backtrader release
breaks compatibility.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date

import backtrader as bt
import pandas as pd

from .config import (
    DEFAULT_LOOKBACK_YEARS,
    HV_WINDOW,
    STRATEGY_EDU_DB,
    Asset,
    get_asset,
)
from .data_fetcher import _normalize_frame, compute_hv_series
from .metrics import PerformanceSummary, summarize
from .option_math import (
    black_scholes_metrics,
    estimate_iv,
    intrinsic_value,
    synthetic_futures_price,
)
from .strategies import (
    LegQuote,
    PositionPlan,
    StrategyConfig,
    build_position_plan,
)

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Portfolio primitives
# ---------------------------------------------------------------------------


@dataclass
class LiveOption:
    kind: str
    strike: float
    expiry: date
    qty: int
    contracts: int
    multiplier: float
    entry_price: float
    entry_date: date
    entry_iv: float
    label: str

    @property
    def signed_units(self) -> float:
        return float(self.qty * self.contracts * self.multiplier)

    def value_at(self, price: float) -> float:
        return self.signed_units * float(price)


@dataclass
class LiveFuture:
    qty_units: float
    entry_price: float
    expiry: date
    entry_date: date
    label: str = "Short synthetic future"

    def value_at(self, current_price: float) -> float:
        return self.qty_units * (float(current_price) - self.entry_price)


@dataclass
class TradeRecord:
    as_of: pd.Timestamp
    action: str
    instrument: str
    quantity: float
    price: float
    cash_flow: float
    fees: float
    note: str = ""


@dataclass
class PortfolioLedger:
    cash: float
    spot_units: float = 0.0
    gross_premium: float = 0.0
    fees_paid: float = 0.0
    trades: list[TradeRecord] = field(default_factory=list)

    def _record(
        self,
        as_of: pd.Timestamp,
        action: str,
        instrument: str,
        quantity: float,
        price: float,
        cash_flow: float,
        fees: float,
        note: str = "",
    ) -> None:
        self.trades.append(
            TradeRecord(
                as_of=pd.Timestamp(as_of),
                action=action,
                instrument=instrument,
                quantity=float(quantity),
                price=float(price),
                cash_flow=float(cash_flow),
                fees=float(fees),
                note=note,
            )
        )

    def open_option(self, leg: LegQuote, contracts: int, multiplier: float, fee_rate: float, as_of: pd.Timestamp) -> LiveOption:
        signed_units = float(leg.qty * contracts * multiplier)
        gross = -signed_units * leg.premium
        fee = abs(gross) * fee_rate
        self.cash += gross - fee
        self.fees_paid += fee
        if gross > 0:
            self.gross_premium += gross
        self._record(
            as_of,
            "SELL" if leg.qty < 0 else "BUY",
            leg.label,
            float(contracts),
            leg.premium,
            gross,
            fee,
            "Open synthetic option",
        )
        return LiveOption(
            kind=leg.kind,
            strike=leg.strike,
            expiry=leg.expiry,
            qty=leg.qty,
            contracts=int(contracts),
            multiplier=float(multiplier),
            entry_price=leg.premium,
            entry_date=pd.Timestamp(as_of).date(),
            entry_iv=leg.iv,
            label=leg.label,
        )

    def settle_option(self, live: LiveOption, spot: float, fee_rate: float, as_of: pd.Timestamp, note: str = "Expired") -> float:
        intrinsic = intrinsic_value(live.kind, spot, live.strike)
        gross = live.value_at(intrinsic)
        fee = abs(gross) * fee_rate
        self.cash += gross - fee
        self.fees_paid += fee
        self._record(
            as_of,
            "EXPIRE" if intrinsic <= 0 else "SETTLE",
            live.label,
            float(live.contracts),
            intrinsic,
            gross,
            fee,
            note,
        )
        return gross

    def close_option(self, live: LiveOption, price: float, fee_rate: float, as_of: pd.Timestamp, note: str = "Closed") -> float:
        gross = live.value_at(price)
        fee = abs(gross) * fee_rate
        self.cash += gross - fee
        self.fees_paid += fee
        self._record(
            as_of,
            "BUY TO CLOSE" if live.qty < 0 else "SELL TO CLOSE",
            live.label,
            float(live.contracts),
            price,
            gross,
            fee,
            note,
        )
        return gross

    def buy_spot(self, units: float, price: float, fee_rate: float, as_of: pd.Timestamp, note: str = "Buy spot") -> None:
        gross = -float(units) * float(price)
        fee = abs(gross) * fee_rate
        self.cash += gross - fee
        self.fees_paid += fee
        self.spot_units += float(units)
        self._record(as_of, "BUY", "Spot underlying", float(units), price, gross, fee, note)

    def sell_spot(self, units: float, price: float, fee_rate: float, as_of: pd.Timestamp, note: str = "Sell spot") -> None:
        units = min(float(units), self.spot_units)
        if units <= 0:
            return
        gross = units * float(price)
        fee = abs(gross) * fee_rate
        self.cash += gross - fee
        self.fees_paid += fee
        self.spot_units -= units
        self._record(as_of, "SELL", "Spot underlying", units, price, gross, fee, note)

    def open_future(self, qty_units: float, price: float, fee_rate: float, as_of: pd.Timestamp, expiry: date) -> LiveFuture:
        fee = abs(float(qty_units) * float(price)) * fee_rate
        self.cash -= fee
        self.fees_paid += fee
        self._record(
            as_of,
            "SHORT FUTURE" if qty_units < 0 else "LONG FUTURE",
            "Synthetic future",
            abs(float(qty_units)),
            price,
            0.0,
            fee,
            f"Expiry {expiry.isoformat()}",
        )
        return LiveFuture(
            qty_units=float(qty_units),
            entry_price=float(price),
            expiry=expiry,
            entry_date=pd.Timestamp(as_of).date(),
        )

    def settle_future(self, live: LiveFuture, settlement: float, fee_rate: float, as_of: pd.Timestamp) -> float:
        gross = live.value_at(settlement)
        fee = abs(float(live.qty_units) * float(settlement)) * fee_rate
        self.cash += gross - fee
        self.fees_paid += fee
        self._record(
            as_of,
            "SETTLE FUTURE",
            "Synthetic future",
            abs(live.qty_units),
            settlement,
            gross,
            fee,
            "Convergence at expiration",
        )
        return gross

    def close_future(self, live: LiveFuture, price: float, fee_rate: float, as_of: pd.Timestamp, note: str = "Future closed") -> float:
        gross = live.value_at(price)
        fee = abs(float(live.qty_units) * float(price)) * fee_rate
        self.cash += gross - fee
        self.fees_paid += fee
        self._record(
            as_of,
            "CLOSE FUTURE",
            "Synthetic future",
            abs(live.qty_units),
            price,
            gross,
            fee,
            note,
        )
        return gross


@dataclass
class BacktestResult:
    strategy_key: str
    asset: Asset
    config: StrategyConfig
    start: pd.Timestamp
    end: pd.Timestamp
    initial_capital: float
    final_nav: float
    nav: pd.DataFrame
    benchmark: pd.Series
    cycles: pd.DataFrame
    trades: pd.DataFrame
    events: pd.DataFrame
    summary: PerformanceSummary
    contracts: int
    premium_collected: float
    fees_paid: float
    assignments: int
    engine: str
    initial_plan: PositionPlan
    warnings: list[str] = field(default_factory=list)
    open_cycle_pnl: float = 0.0
    max_capital_used: float = 0.0

    @property
    def strategy_name(self) -> str:
        return STRATEGY_EDU_DB.get(self.strategy_key, {}).get("short", self.strategy_key)

    @property
    def currency(self) -> str:
        return self.asset.currency


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class BacktestController:
    """State machine that opens, marks, settles, and rolls strategy cycles."""

    def __init__(self, asset: Asset, config: StrategyConfig, frame: pd.DataFrame, hv_series: pd.Series) -> None:
        self.asset = asset
        self.config = config
        self.frame = frame
        self.hv_series = hv_series.reindex(frame.index).ffill()
        self.ledger = PortfolioLedger(cash=float(config.capital))
        self.initial_capital = float(config.capital)
        self.contracts: int | None = None
        self.initial_contracts = 0
        self.open_legs: list[LiveOption] = []
        self.open_future: LiveFuture | None = None
        self.cycle_start_nav = float(config.capital)
        self.cycle_start_date: pd.Timestamp | None = None
        self.cycle_expiry: date | None = None
        self.cycle_index = 0
        self.cycles: list[dict] = []
        self.events: list[dict] = []
        self.nav_rows: list[dict] = []
        self.peak = float(config.capital)
        self.assignments = 0
        self.started = False
        self.finished = False
        self.stop_new_cycles = False
        self.initial_plan: PositionPlan | None = None
        self.current_plan: PositionPlan | None = None
        self.warnings: list[str] = []
        self.max_capital_used = 0.0
        self.open_cycle_pnl = 0.0
        self.last_date: pd.Timestamp | None = None
        self.last_spot: float = 0.0

    # -- pricing -----------------------------------------------------------
    def _hv_at(self, ts: pd.Timestamp) -> float:
        try:
            value = float(self.hv_series.loc[pd.Timestamp(ts)])
        except (KeyError, TypeError, ValueError):
            value = float("nan")
        if not math.isfinite(value) or value <= 0:
            value = self.asset.base_iv
        return value

    def _option_price(self, live: LiveOption, ts: pd.Timestamp, spot: float) -> float:
        remaining = (live.expiry - pd.Timestamp(ts).date()).days
        if remaining <= 0:
            return intrinsic_value(live.kind, spot, live.strike)
        metrics = black_scholes_metrics(
            kind=live.kind,
            spot=spot,
            strike=live.strike,
            years=remaining / 365.0,
            rate=self.config.risk_free,
            sigma=live.entry_iv,
            dividend_yield=self.asset.dividend_yield,
        )
        return metrics.price

    def _future_price(self, ts: pd.Timestamp, spot: float) -> float:
        if self.open_future is None:
            return spot
        remaining = max((self.open_future.expiry - pd.Timestamp(ts).date()).days, 0)
        return synthetic_futures_price(
            spot,
            remaining / 365.0,
            self.config.risk_free,
            self.asset.dividend_yield,
            max(self.config.basis_pct, 0.0) / 100.0,
        )

    def nav(self, ts: pd.Timestamp, spot: float) -> float:
        option_value = sum(live.value_at(self._option_price(live, ts, spot)) for live in self.open_legs)
        future_value = self.open_future.value_at(self._future_price(ts, spot)) if self.open_future else 0.0
        return float(
            self.ledger.cash
            + self.ledger.spot_units * spot
            + option_value
            + future_value
        )

    def _record(self, ts: pd.Timestamp, spot: float) -> None:
        nav = self.nav(ts, spot)
        self.peak = max(self.peak, nav)
        dd = nav / self.peak - 1.0 if self.peak > 0 else 0.0
        row = {
            "date": pd.Timestamp(ts),
            "nav": nav,
            "cash": self.ledger.cash,
            "spot_value": self.ledger.spot_units * spot,
            "option_value": sum(live.value_at(self._option_price(live, ts, spot)) for live in self.open_legs),
            "futures_value": self.open_future.value_at(self._future_price(ts, spot)) if self.open_future else 0.0,
            "drawdown": dd,
            "iv": estimate_iv(self._hv_at(ts), self.config.iv_multiplier),
            "contracts": self.contracts or 0,
        }
        if self.nav_rows and self.nav_rows[-1]["date"] == row["date"]:
            self.nav_rows[-1] = row
        else:
            self.nav_rows.append(row)

    # -- lifecycle ---------------------------------------------------------
    def _add_event(self, ts: pd.Timestamp, kind: str, title: str, detail: str) -> None:
        self.events.append(
            {"date": pd.Timestamp(ts), "kind": kind, "title": title, "detail": detail}
        )

    def _build_plan(self, ts: pd.Timestamp, spot: float, contracts: int | None = None) -> PositionPlan:
        plan = build_position_plan(
            self.config,
            spot=spot,
            historical_volatility=self._hv_at(ts),
            as_of=pd.Timestamp(ts).date(),
            contracts=contracts,
        )
        return plan

    def _affordable_contracts(self, plan: PositionPlan, spot: float) -> int:
        """Reduce size when cash cannot support another cycle (never go negative)."""
        cash = max(self.ledger.cash, 0.0)
        multiplier = plan.multiplier
        strategy = self.config.strategy_key
        per_lot = 0.0
        if strategy == "cash_secured_put" and plan.legs:
            per_lot = plan.legs[0].strike * multiplier
        elif strategy == "long_straddle" and plan.contracts > 0:
            per_lot = max(-plan.net_premium / plan.contracts, 0.0)
        elif strategy == "iron_condor" and plan.contracts > 0:
            per_lot = max(abs(plan.max_loss) / plan.contracts, 0.0)
        elif strategy in {"covered_call", "basis_trade"} and self.ledger.spot_units <= 0:
            per_lot = spot * multiplier
        if per_lot <= 0:
            return plan.contracts
        affordable = int(math.floor(cash / (per_lot * (1.0 + self.config.fee_rate)) + 1e-9))
        return int(max(min(plan.contracts, affordable), 0))

    def _open_cycle(self, ts: pd.Timestamp, spot: float) -> bool:
        if self.stop_new_cycles:
            return False
        plan = self._build_plan(ts, spot, contracts=self.contracts)
        if self.contracts is None:
            self.contracts = plan.contracts
            self.initial_contracts = plan.contracts
        affordable = self._affordable_contracts(plan, spot)
        if affordable < plan.contracts:
            if affordable <= 0:
                self.stop_new_cycles = True
                self.warnings.append(
                    "Simulation stopped opening new cycles: available cash is below the "
                    "cost of one additional lot."
                )
                self._add_event(
                    ts,
                    "warning",
                    "Capital exhausted",
                    "No new cycle was opened because cash no longer covers one lot.",
                )
                return False
            plan = self._build_plan(ts, spot, contracts=affordable)
            self.contracts = affordable

        if plan.contracts <= 0:
            self.stop_new_cycles = True
            self._add_event(
                ts,
                "warning",
                "Capital below one lot",
                "Increase the capital allocation to open a position.",
            )
            return False

        if self.initial_plan is None:
            self.initial_plan = plan
        self.cycle_start_nav = self.nav(ts, spot)
        self.cycle_start_date = pd.Timestamp(ts)
        self.cycle_index += 1
        self.max_capital_used = max(self.max_capital_used, plan.capital_used)

        if self.config.strategy_key == "covered_call":
            if self.ledger.spot_units < plan.stock_units:
                units = plan.stock_units - self.ledger.spot_units
                self.ledger.buy_spot(units, spot, self.config.fee_rate, ts, "Establish covered shares")
        elif self.config.strategy_key == "basis_trade":
            if self.ledger.spot_units <= 0:
                self.ledger.buy_spot(plan.units, spot, self.config.fee_rate, ts, "Buy spot leg")
            if self.open_future is None and plan.futures_entry is not None and plan.futures_expiry is not None:
                self.open_future = self.ledger.open_future(
                    -plan.units,
                    plan.futures_entry,
                    self.config.fee_rate,
                    ts,
                    plan.futures_expiry,
                )

        for leg in plan.legs:
            self.open_legs.append(
                self.ledger.open_option(leg, plan.contracts, plan.multiplier, self.config.fee_rate, ts)
            )

        self.cycle_expiry = plan.expiry
        self.current_plan = plan
        self._add_event(
            ts,
            "open",
            f"Opened {STRATEGY_EDU_DB.get(self.config.strategy_key, {}).get('short', 'strategy')}",
            (
                f"{plan.contracts} lot(s) at spot {spot:,.2f}; "
                f"net premium {plan.net_premium:,.2f} {plan.currency}."
            ),
        )
        return True

    def _close_cycle(self, ts: pd.Timestamp, spot: float) -> None:
        if self.cycle_expiry is None:
            return
        status = "expired"
        assigned = False

        for live in list(self.open_legs):
            intrinsic = intrinsic_value(live.kind, spot, live.strike)
            if self.config.strategy_key == "cash_secured_put" and live.kind == "put" and intrinsic > 0:
                units = live.contracts * live.multiplier
                self.ledger.buy_spot(
                    units,
                    live.strike,
                    self.config.fee_rate,
                    ts,
                    f"Assignment at strike {live.strike:,.2f}",
                )
                self.open_legs.remove(live)
                self.assignments += 1
                assigned = True
                status = "assigned"
                self._add_event(
                    ts,
                    "assignment",
                    "Put assigned",
                    (
                        f"Bought {units:,.0f} units at the strike after spot closed at "
                        f"{spot:,.2f}. The reserved cash was deployed; no new puts are written."
                    ),
                )
            else:
                self.ledger.settle_option(live, spot, self.config.fee_rate, ts)
                self.open_legs.remove(live)
                if self.config.strategy_key == "covered_call" and live.kind == "call" and intrinsic > 0:
                    self.assignments += 1
                    self._add_event(
                        ts,
                        "assignment",
                        "Call finished in the money",
                        (
                            f"Spot {spot:,.2f} closed above the {live.strike:,.2f} strike. "
                            "The synthetic engine cash-settles the call and keeps the shares; "
                            "economically this matches being called away and re-buying."
                        ),
                    )

        if self.open_future is not None:
            self.ledger.settle_future(self.open_future, spot, self.config.fee_rate, ts)
            self.open_future = None
            status = "rolled"

        nav_after = self.nav(ts, spot)
        pnl = nav_after - self.cycle_start_nav
        cycle_return = pnl / self.cycle_start_nav if self.cycle_start_nav > 0 else 0.0
        self.cycles.append(
            {
                "cycle": self.cycle_index,
                "start": self.cycle_start_date,
                "end": pd.Timestamp(ts),
                "pnl": pnl,
                "return": cycle_return,
                "status": status,
            }
        )
        self._add_event(
            ts,
            "cycle",
            f"Cycle {self.cycle_index} closed",
            f"P&L {pnl:,.2f} {self.asset.currency} ({cycle_return * 100:+.2f}%) - {status}.",
        )
        self.cycle_start_nav = nav_after
        self.cycle_expiry = None
        self.current_plan = None
        if assigned:
            self.stop_new_cycles = True

    def on_bar(self, ts: pd.Timestamp, spot: float) -> None:
        ts = pd.Timestamp(ts)
        if not math.isfinite(spot) or spot <= 0:
            return
        self.last_date = ts
        self.last_spot = float(spot)
        if not self.started:
            self.started = True
            self._open_cycle(ts, spot)
            self._record(ts, spot)
            return
        if self.cycle_expiry is not None and ts.date() >= self.cycle_expiry:
            self._close_cycle(ts, spot)
            if not self.stop_new_cycles:
                self._open_cycle(ts, spot)
        self._record(ts, spot)

    def finalize(self) -> None:
        if self.finished:
            return
        self.finished = True
        if self.last_date is not None:
            self._record(self.last_date, self.last_spot)
        if self.cycle_start_date is not None and self.cycle_expiry is not None and self.cycle_start_nav != 0:
            open_pnl = self.nav(self.last_date, self.last_spot) - self.cycle_start_nav if self.last_date is not None else 0.0
            self.open_cycle_pnl = open_pnl


# ---------------------------------------------------------------------------
# Backtrader integration
# ---------------------------------------------------------------------------


class _ControllerStrategy(bt.Strategy):
    params = (("controller", None),)

    def __init__(self) -> None:
        self.controller: BacktestController = self.p.controller

    def next(self) -> None:
        ts = pd.Timestamp(self.datas[0].datetime.date(0))
        spot = float(self.datas[0].close[0])
        self.controller.on_bar(ts, spot)

    def stop(self) -> None:
        self.controller.finalize()


def _prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    clean = _normalize_frame(frame)
    if not isinstance(clean.index, pd.DatetimeIndex):
        clean.index = pd.to_datetime(clean.index)
    clean.index = pd.to_datetime(clean.index).tz_localize(None) if getattr(clean.index, "tz", None) is not None else clean.index
    return clean


def _slice_history(frame: pd.DataFrame, years: int) -> pd.DataFrame:
    years = int(min(max(years, 1), 20))
    cutoff = frame.index.max() - pd.DateOffset(years=years)
    sliced = frame[frame.index >= cutoff]
    if len(sliced) < 60:
        return frame.tail(min(len(frame), 260))
    return sliced


def _build_result(
    controller: BacktestController,
    frame: pd.DataFrame,
    config: StrategyConfig,
    asset: Asset,
    engine: str,
) -> BacktestResult:
    if controller.initial_plan is None:
        plan = build_position_plan(
            config,
            frame["Close"].iloc[0],
            asset.base_iv,
            frame.index[0],
        )
        controller.initial_plan = plan
    nav_df = pd.DataFrame(controller.nav_rows)
    if nav_df.empty:
        raise RuntimeError("The simulation produced no NAV observations.")
    nav_df = nav_df.drop_duplicates(subset=["date"], keep="last").set_index("date").sort_index()
    nav_df["equity_index"] = nav_df["nav"] / float(config.capital) * 100.0

    benchmark = frame["Close"].reindex(nav_df.index).ffill()
    if benchmark.isna().any():
        benchmark = benchmark.bfill()
    benchmark_nav = benchmark / benchmark.iloc[0] * float(config.capital)
    nav_df["benchmark"] = benchmark_nav

    trades = pd.DataFrame(
        [t.__dict__ for t in controller.ledger.trades],
        columns=["as_of", "action", "instrument", "quantity", "price", "cash_flow", "fees", "note"],
    )
    if not trades.empty:
        trades = trades.sort_values("as_of").reset_index(drop=True)

    cycles = pd.DataFrame(
        controller.cycles,
        columns=["cycle", "start", "end", "pnl", "return", "status"],
    )
    if not cycles.empty:
        cycles = cycles.sort_values("cycle").reset_index(drop=True)

    events = pd.DataFrame(controller.events, columns=["date", "kind", "title", "detail"])
    if not events.empty:
        events = events.sort_values("date").reset_index(drop=True)

    cycle_pnls = cycles["pnl"] if not cycles.empty else pd.Series(dtype=float)
    summary = summarize(
        nav_df["nav"],
        cycle_pnls,
        controller.ledger.gross_premium,
        float(config.capital),
        risk_free=0.0,
        max_capital_used=controller.max_capital_used,
    )
    warnings = list(dict.fromkeys(controller.warnings))
    return BacktestResult(
        strategy_key=config.strategy_key,
        asset=asset,
        config=config,
        start=nav_df.index.min(),
        end=nav_df.index.max(),
        initial_capital=float(config.capital),
        final_nav=float(nav_df["nav"].iloc[-1]),
        nav=nav_df,
        benchmark=benchmark_nav,
        cycles=cycles,
        trades=trades,
        events=events,
        summary=summary,
        contracts=int(controller.contracts or 0),
        premium_collected=float(controller.ledger.gross_premium),
        fees_paid=float(controller.ledger.fees_paid),
        assignments=int(controller.assignments),
        engine=engine,
        initial_plan=controller.initial_plan,
        warnings=warnings,
        open_cycle_pnl=float(controller.open_cycle_pnl),
        max_capital_used=float(controller.max_capital_used),
    )


def _run_with_backtrader(asset: Asset, frame: pd.DataFrame, config: StrategyConfig) -> tuple[BacktestController, str]:
    hv_series = compute_hv_series(frame["Close"], window=HV_WINDOW).fillna(asset.base_iv)
    controller = BacktestController(asset, config, frame, hv_series)
    cerebro = bt.Cerebro(stdstats=False, maxcpus=1, runonce=False)
    feed = bt.feeds.PandasData(
        dataname=frame,
        datetime=None,
        open="Open",
        high="High",
        low="Low",
        close="Close",
        volume="Volume",
        openinterest=-1,
    )
    cerebro.adddata(feed, name=asset.symbol)
    cerebro.addstrategy(_ControllerStrategy, controller=controller)
    cerebro.broker.setcash(float(config.capital))
    cerebro.broker.setcommission(commission=0.0)
    cerebro.run()
    controller.finalize()
    return controller, "backtrader"


def run_backtest(
    asset_symbol: str,
    frame: pd.DataFrame,
    config: StrategyConfig,
    lookback_years: int | None = None,
) -> BacktestResult:
    """Run a full historical simulation for one strategy configuration."""
    asset = get_asset(asset_symbol)
    if config.asset_symbol != asset_symbol:
        config = StrategyConfig(**{**config.__dict__, "asset_symbol": asset_symbol})
    if config.strategy_key not in STRATEGY_EDU_DB:
        raise ValueError(f"Unknown strategy: {config.strategy_key}")
    clean = _prepare_frame(frame)
    years = int(lookback_years or config.lookback_years or DEFAULT_LOOKBACK_YEARS)
    sliced = _slice_history(clean, years)
    if len(sliced) < 30:
        raise ValueError("Not enough market history for a meaningful backtest (need 30+ rows).")

    try:
        controller, engine = _run_with_backtrader(asset, sliced, config)
        return _build_result(controller, sliced, config, asset, engine)
    except Exception as exc:
        LOGGER.exception("Backtrader run failed; using the direct event loop: %s", exc)
        hv_series = compute_hv_series(sliced["Close"], window=HV_WINDOW).fillna(asset.base_iv)
        controller = BacktestController(asset, config, sliced, hv_series)
        for ts, row in sliced.iterrows():
            controller.on_bar(pd.Timestamp(ts), float(row["Close"]))
        controller.finalize()
        result = _build_result(controller, sliced, config, asset, "direct-fallback")
        result.warnings.append(
            "Backtrader was unavailable in this environment; the built-in direct "
            "event loop produced the same simulation."
        )
        return result
