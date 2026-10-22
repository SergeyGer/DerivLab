"""Hold-the-Position interactive stress-test engine.

The user starts a historical scenario with a live position. Time advances one
trading day at a time (one day per second by default in the UI). When a risk
trigger fires, playback pauses and the user chooses to roll, hold, or liquidate.
At the end, a score and a thematic badge summarise the decisions.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .backtest_engine import LiveFuture, LiveOption, PortfolioLedger
from .config import GAME_SCENARIOS, STRATEGY_EDU_DB, Asset, get_asset
from .data_fetcher import MarketData, compute_hv_series
from .metrics import ScoreCard, max_drawdown, score_game
from .option_math import black_scholes_metrics, intrinsic_value, synthetic_futures_price
from .strategies import PositionPlan, StrategyConfig, build_position_plan

LOGGER = logging.getLogger(__name__)

REASON_TITLES = {
    "period_end": "Scenario complete",
    "liquidated": "Position liquidated",
    "assigned": "Assigned on the put",
    "called_away": "Called away on the call",
    "capital_exhausted": "Capital exhausted",
    "expired": "Expired",
}

TRIGGER_THRESHOLDS = {
    "basis_trade": {"drawdown": 0.04, "move": 0.08},
    "covered_call": {"drawdown": 0.10, "move": 0.10},
    "cash_secured_put": {"drawdown": 0.10, "move": 0.10},
    "long_straddle": {"drawdown": 0.12, "move": 0.07},
    "iron_condor": {"drawdown": 0.10, "move": 0.08},
}


class GameStartError(RuntimeError):
    """Raised when a scenario cannot be started with the supplied parameters."""


@dataclass
class RiskAlert:
    key: str
    title: str
    message: str
    severity: str
    as_of: pd.Timestamp
    spot: float
    nav: float
    drawdown: float
    leg: str = ""


@dataclass
class ScenarioGame:
    asset: Asset
    config: StrategyConfig
    frame: pd.DataFrame
    scenario_label: str

    def __post_init__(self) -> None:
        self.asset = get_asset(self.asset.symbol) if not isinstance(self.asset, Asset) else self.asset
        self.frame = frame_reset(self.frame)
        self.hv_series = compute_hv_series(self.frame["Close"]).reindex(self.frame.index).ffill().fillna(self.asset.base_iv)
        self.ledger = PortfolioLedger(cash=float(self.config.capital))
        self.initial_capital = float(self.config.capital)
        self.contracts = 0
        self.open_legs: list[LiveOption] = []
        self.open_future: LiveFuture | None = None
        self.cycle_expiry: date | None = None
        self.cycle_entry_spot = 0.0
        self.entry_spot = 0.0
        self.entry_plan: PositionPlan | None = None
        self.entry_plan = None
        self.index = 0
        self.state = "ready"
        self.active_alert: RiskAlert | None = None
        self.suppressed: set[str] = set()
        self.peak = float(self.config.capital)
        self.nav_rows: list[dict] = []
        self.events: list[dict] = []
        self.rolls = 0
        self.holds = 0
        self.assignments = 0
        self.called_away = False
        self.assigned = False
        self.liquidated = False
        self.finish_reason = ""
        self.final_nav = float(self.config.capital)
        self.score_card: ScoreCard | None = None
        self.started_at: pd.Timestamp | None = None
        self.ended_at: pd.Timestamp | None = None
        self.start_date = self.frame.index.min()
        self.end_date = self.frame.index.max()
        self.cycle_pnls: list[float] = []
        self.cycle_start_nav = float(self.config.capital)
        self.cycle_start_date: pd.Timestamp | None = None
        self.current_plan: PositionPlan | None = None
        self.last_action_message = ""
        self.max_contracts = 0
        self.warnings: list[str] = []

    # -- convenience -------------------------------------------------------
    @property
    def strategy_key(self) -> str:
        return self.config.strategy_key

    @property
    def strategy_name(self) -> str:
        return STRATEGY_EDU_DB.get(self.strategy_key, {}).get("short", self.strategy_key)

    @property
    def current_date(self) -> pd.Timestamp:
        return self.frame.index[min(self.index, len(self.frame) - 1)]

    @property
    def current_spot(self) -> float:
        return float(self.frame["Close"].iloc[min(self.index, len(self.frame) - 1)])

    @property
    def progress(self) -> float:
        return self.index / max(len(self.frame) - 1, 1)

    @property
    def days_total(self) -> int:
        return len(self.frame)

    @property
    def days_elapsed(self) -> int:
        return self.index + 1

    @property
    def is_finished(self) -> bool:
        return self.state == "finished"

    @property
    def is_alert(self) -> bool:
        return self.state == "alert"

    @property
    def is_running(self) -> bool:
        return self.state in {"running", "alert"}

    @property
    def pnl(self) -> float:
        return self.final_nav - self.initial_capital if self.is_finished else self.nav() - self.initial_capital

    @property
    def current_drawdown(self) -> float:
        nav = self.final_nav if self.is_finished else self.nav()
        if self.peak <= 0:
            return 0.0
        return min(nav / self.peak - 1.0, 0.0)

    @property
    def premium_collected(self) -> float:
        return float(self.ledger.gross_premium)

    @property
    def fees_paid(self) -> float:
        return float(self.ledger.fees_paid)

    @property
    def total_return(self) -> float:
        nav = self.final_nav if self.is_finished else self.nav()
        return nav / self.initial_capital - 1.0 if self.initial_capital > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        if self.is_finished:
            nav = self.nav_series()
            return max_drawdown(nav) if len(nav) else 0.0
        nav = pd.Series([row["nav"] for row in self.nav_rows], dtype=float)
        return max_drawdown(nav) if len(nav) else 0.0

    @property
    def premium_yield(self) -> float:
        return self.premium_collected / self.initial_capital if self.initial_capital > 0 else 0.0

    def nav_series(self) -> pd.Series:
        if not self.nav_rows:
            return pd.Series(dtype=float)
        rows = pd.DataFrame(self.nav_rows).drop_duplicates("date", keep="last").set_index("date").sort_index()
        return rows["nav"]

    def path_frame(self) -> pd.DataFrame:
        if not self.nav_rows:
            return pd.DataFrame(columns=["date", "spot", "nav", "drawdown", "equity_index"])
        frame = pd.DataFrame(self.nav_rows).drop_duplicates("date", keep="last").set_index("date").sort_index()
        return frame

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
            live.kind,
            spot,
            live.strike,
            remaining / 365.0,
            self.config.risk_free,
            live.entry_iv,
            self.asset.dividend_yield,
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

    def nav(self, ts: pd.Timestamp | None = None, spot: float | None = None) -> float:
        ts = ts or self.current_date
        spot = self.current_spot if spot is None else float(spot)
        option_value = sum(live.value_at(self._option_price(live, ts, spot)) for live in self.open_legs)
        future_value = self.open_future.value_at(self._future_price(ts, spot)) if self.open_future else 0.0
        return float(self.ledger.cash + self.ledger.spot_units * spot + option_value + future_value)

    # -- setup -------------------------------------------------------------
    def start(self) -> ScenarioGame:
        if self.frame is None or len(self.frame) < 30:
            raise GameStartError("The selected scenario has fewer than 30 trading days.")
        ts = self.current_date
        spot = self.current_spot
        if not self._open_cycle(ts, spot, initial=True):
            raise GameStartError(
                "The allocation is too small to open one simulated lot for this strategy. "
                "Increase capital or choose a cheaper instrument."
            )
        self.started_at = ts
        self.entry_spot = spot
        self.peak = self.nav(ts, spot)
        self.cycle_start_nav = self.peak
        self.cycle_start_date = ts
        self.state = "running"
        self._record(ts, spot)
        self._add_event(ts, "start", "Scenario started", f"{self.strategy_name} opened at {spot:,.2f}.")
        return self

    def _open_cycle(self, ts: pd.Timestamp, spot: float, initial: bool = False) -> bool:
        plan = build_position_plan(
            self.config,
            spot=spot,
            historical_volatility=self._hv_at(ts),
            as_of=pd.Timestamp(ts).date(),
            contracts=self.contracts if self.contracts else None,
        )
        if initial and plan.contracts == 0:
            return False
        if plan.contracts <= 0:
            return False
        # Defensive resizing: never open a cycle that requires more cash than available.
        strategy = self.strategy_key
        multiplier = plan.multiplier
        cash = max(self.ledger.cash, 0.0)
        affordable = plan.contracts
        if strategy == "cash_secured_put" and plan.legs:
            per_lot = plan.legs[0].strike * multiplier
            affordable = min(affordable, int(cash // max(per_lot, 1e-9)))
        elif strategy == "long_straddle" and plan.contracts:
            per_lot = max(-plan.net_premium / plan.contracts, 0.0) * (1 + self.config.fee_rate)
            affordable = min(affordable, int(cash // max(per_lot, 1e-9)))
        elif strategy == "iron_condor" and plan.contracts:
            per_lot = max(abs(plan.max_loss) / plan.contracts, 0.0) * (1 + self.config.fee_rate)
            affordable = min(affordable, int(cash // max(per_lot, 1e-9)))
        elif strategy in {"covered_call", "basis_trade"} and self.ledger.spot_units <= 0:
            per_lot = spot * multiplier * (1 + self.config.fee_rate)
            affordable = min(affordable, int(cash // max(per_lot, 1e-9)))
        if affordable < plan.contracts:
            if affordable <= 0:
                return False
            plan = build_position_plan(
                self.config,
                spot=spot,
                historical_volatility=self._hv_at(ts),
                as_of=pd.Timestamp(ts).date(),
                contracts=affordable,
            )
        if plan.contracts <= 0:
            return False
        self.contracts = plan.contracts
        self.max_contracts = max(self.max_contracts, plan.contracts)
        if self.entry_plan is None:
            self.entry_plan = plan
        self.current_plan = plan

        if strategy == "covered_call":
            if self.ledger.spot_units < plan.stock_units:
                units = plan.stock_units - self.ledger.spot_units
                self.ledger.buy_spot(units, spot, self.config.fee_rate, ts, "Establish covered shares")
        elif strategy == "basis_trade":
            if self.ledger.spot_units <= 0:
                self.ledger.buy_spot(plan.units, spot, self.config.fee_rate, ts, "Buy spot leg")
            if plan.futures_entry is not None and plan.futures_expiry is not None:
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
        self.cycle_entry_spot = spot
        self.cycle_start_nav = self.nav(ts, spot)
        self.cycle_start_date = ts
        self._add_event(
            ts,
            "open",
            "Position opened" if initial else "Position rolled",
            f"{plan.contracts} lot(s); net premium {plan.net_premium:,.2f} {plan.currency}.",
        )
        return True

    # -- time progression --------------------------------------------------
    def advance(self) -> None:
        if self.state != "running":
            return
        if self.index >= len(self.frame) - 1:
            self._finish("period_end")
            return
        self.index += 1
        ts = self.current_date
        spot = self.current_spot

        if self.cycle_expiry is not None and ts.date() >= self.cycle_expiry:
            self._settle_cycle(ts, spot)
            if self.state == "finished":
                self._record(ts, spot)
                return
            if not self._open_cycle(ts, spot):
                self._finish("capital_exhausted")
                self._record(ts, spot)
                return

        alert = self._find_alert(ts, spot)
        self._record(ts, spot)
        if alert is not None:
            self.active_alert = alert
            self.state = "alert"
            self._add_event(ts, "alert", alert.title, alert.message)
            return
        if self.index >= len(self.frame) - 1:
            self._finish("period_end")

    def advance_days(self, n: int = 1) -> None:
        for _ in range(max(int(n), 1)):
            if self.state != "running":
                break
            self.advance()

    # -- alerts ------------------------------------------------------------
    def _condition_map(self, ts: pd.Timestamp, spot: float) -> dict[str, RiskAlert]:
        thresholds = TRIGGER_THRESHOLDS.get(self.strategy_key, {"drawdown": 0.10, "move": 0.08})
        nav = self.nav(ts, spot)
        dd = min(nav / self.peak - 1.0, 0.0) if self.peak > 0 else 0.0
        conditions: dict[str, RiskAlert] = {}

        for idx, live in enumerate(self.open_legs):
            if live.qty >= 0:
                continue
            if live.kind == "call" and spot > live.strike * 1.002:
                breach = spot / live.strike - 1.0
                conditions[f"short_call_{idx}"] = RiskAlert(
                    key=f"short_call_{idx}",
                    title="Upside breach",
                    message=(
                        f"Spot closed at {spot:,.2f}, {breach * 100:+.1f}% above your short call "
                        f"strike of {live.strike:,.2f}. Assignment risk is rising."
                    ),
                    severity="high",
                    as_of=ts,
                    spot=spot,
                    nav=nav,
                    drawdown=dd,
                    leg=live.label,
                )
            elif live.kind == "put" and spot < live.strike * 0.998:
                breach = spot / live.strike - 1.0
                conditions[f"short_put_{idx}"] = RiskAlert(
                    key=f"short_put_{idx}",
                    title="Downside breach",
                    message=(
                        f"Spot closed at {spot:,.2f}, {breach * 100:+.1f}% below your short put "
                        f"strike of {live.strike:,.2f}. Assignment risk is rising."
                    ),
                    severity="high",
                    as_of=ts,
                    spot=spot,
                    nav=nav,
                    drawdown=dd,
                    leg=live.label,
                )

        if dd < -thresholds["drawdown"]:
            conditions["drawdown"] = RiskAlert(
                key="drawdown",
                title="Drawdown threshold",
                message=(
                    f"Portfolio drawdown reached {dd * 100:.1f}% from the peak. "
                    "The position is asking for a tactical decision."
                ),
                severity="medium",
                as_of=ts,
                spot=spot,
                nav=nav,
                drawdown=dd,
            )
        if self.cycle_entry_spot > 0:
            move = spot / self.cycle_entry_spot - 1.0
            if abs(move) > thresholds["move"]:
                conditions["price_move"] = RiskAlert(
                    key="price_move",
                    title="Large move in progress",
                    message=(
                        f"Spot moved {move * 100:+.1f}% since the current position was opened. "
                        "Check the risk profile before letting it ride."
                    ),
                    severity="medium",
                    as_of=ts,
                    spot=spot,
                    nav=nav,
                    drawdown=dd,
                )
        if nav < self.initial_capital * 0.5:
            conditions["capital"] = RiskAlert(
                key="capital",
                title="Capital preservation alert",
                message="More than half of the allocated capital has been lost. Consider cutting the risk.",
                severity="critical",
                as_of=ts,
                spot=spot,
                nav=nav,
                drawdown=dd,
            )
        return conditions

    def _find_alert(self, ts: pd.Timestamp, spot: float) -> RiskAlert | None:
        conditions = self._condition_map(ts, spot)
        # Re-arm a trigger only after its condition has cleared.
        self.suppressed = {key for key in self.suppressed if key in conditions}
        for key in ("capital", "short_call_0", "short_put_0", "drawdown", "price_move", "short_call_1", "short_put_1"):
            if key in conditions and key not in self.suppressed:
                return conditions[key]
        for key, alert in conditions.items():
            if key not in self.suppressed:
                return alert
        return None

    # -- expiry / settlements ---------------------------------------------
    def _settle_cycle(self, ts: pd.Timestamp, spot: float) -> None:
        strategy = self.strategy_key
        status = "expired"
        assigned = False
        called_away = False

        if strategy == "covered_call":
            call = next((leg for leg in self.open_legs if leg.kind == "call" and leg.qty < 0), None)
            if call is not None:
                intrinsic = max(spot - call.strike, 0.0)
                if intrinsic > 0:
                    units = call.contracts * call.multiplier
                    self.ledger.sell_spot(units, call.strike, self.config.fee_rate, ts, f"Called away at {call.strike:,.2f}")
                    self.open_legs.remove(call)
                    self.called_away = True
                    self.assignments += 1
                    called_away = True
                    status = "called_away"
                    self._add_event(
                        ts,
                        "assignment",
                        "Shares called away",
                        (
                            f"Spot {spot:,.2f} finished above the {call.strike:,.2f} strike. "
                            "Your shares were sold at the strike and the position is closed."
                        ),
                    )
                else:
                    self.ledger.settle_option(call, spot, self.config.fee_rate, ts)
                    self.open_legs.remove(call)
        elif strategy == "cash_secured_put":
            put = next((leg for leg in self.open_legs if leg.kind == "put" and leg.qty < 0), None)
            if put is not None:
                intrinsic = max(put.strike - spot, 0.0)
                if intrinsic > 0:
                    units = put.contracts * put.multiplier
                    self.ledger.buy_spot(units, put.strike, self.config.fee_rate, ts, f"Assigned at {put.strike:,.2f}")
                    self.open_legs.remove(put)
                    self.assigned = True
                    self.assignments += 1
                    assigned = True
                    status = "assigned"
                    self._add_event(
                        ts,
                        "assignment",
                        "Put assigned",
                        (
                            f"Spot {spot:,.2f} finished below the {put.strike:,.2f} strike. "
                            "You now own the asset at the strike, less the premium received."
                        ),
                    )
                else:
                    self.ledger.settle_option(put, spot, self.config.fee_rate, ts)
                    self.open_legs.remove(put)
        else:
            for live in list(self.open_legs):
                intrinsic = intrinsic_value(live.kind, spot, live.strike)
                self.ledger.settle_option(live, spot, self.config.fee_rate, ts)
                self.open_legs.remove(live)
            if self.open_future is not None:
                self.ledger.settle_future(self.open_future, spot, self.config.fee_rate, ts)
                self.open_future = None
                status = "rolled"

        nav_after = self.nav(ts, spot)
        cycle_pnl = nav_after - self.cycle_start_nav
        self.cycle_pnls.append(cycle_pnl)
        self._add_event(
            ts,
            "cycle",
            "Cycle closed",
            f"P&L {cycle_pnl:,.2f} {self.asset.currency} ({status}).",
        )
        self.cycle_start_nav = nav_after
        self.cycle_expiry = None
        self.current_plan = None

        if called_away:
            self._finish("called_away", ts, spot)
            return
        if assigned:
            self._finish("assigned", ts, spot)
            return

    # -- decisions ---------------------------------------------------------
    def _close_all_legs(self, ts: pd.Timestamp, spot: float, note: str) -> float:
        cash_before = self.ledger.cash
        for live in list(self.open_legs):
            price = self._option_price(live, ts, spot)
            self.ledger.close_option(live, price, self.config.fee_rate, ts, note)
            self.open_legs.remove(live)
        if self.open_future is not None:
            price = self._future_price(ts, spot)
            self.ledger.close_future(self.open_future, price, self.config.fee_rate, ts, note)
            self.open_future = None
        return self.ledger.cash - cash_before

    def can_roll(self) -> tuple[bool, str]:
        if self.active_alert is None:
            return False, "A roll is available when a risk alert is active."
        ts, spot = self.current_date, self.current_spot
        cash_after = self.ledger.cash
        for live in self.open_legs:
            gross = live.value_at(self._option_price(live, ts, spot))
            cash_after += gross - abs(gross) * self.config.fee_rate
        if self.open_future is not None:
            gross = self.open_future.value_at(self._future_price(ts, spot))
            cash_after += gross - abs(gross) * self.config.fee_rate
        plan = build_position_plan(
            self.config,
            spot=spot,
            historical_volatility=self._hv_at(ts),
            as_of=ts.date(),
            contracts=self.contracts,
        )
        if plan.contracts <= 0:
            return False, "The current capital does not support another lot."
        if self.strategy_key == "cash_secured_put" and plan.legs:
            required = plan.legs[0].strike * plan.units
            if cash_after < required:
                return False, "Available cash after closing the put cannot secure the new strike."
        if self.strategy_key == "long_straddle":
            required = max(-plan.net_premium, 0.0) * (1 + self.config.fee_rate)
            if cash_after < required:
                return False, "Available cash cannot fund the new straddle debit."
        if self.strategy_key == "iron_condor":
            required = max(abs(plan.max_loss), 0.0) * (1 + self.config.fee_rate)
            if cash_after < required:
                return False, "Available cash does not cover the new condor's maximum loss."
        return True, "Roll the option legs to a fresh strike and expiration."

    def roll(self) -> bool:
        if self.state not in {"alert", "running"} or self.active_alert is None:
            return False
        ok, reason = self.can_roll()
        if not ok:
            self.last_action_message = f"Roll unavailable: {reason}"
            return False
        ts, spot = self.current_date, self.current_spot
        alert_key = self.active_alert.key
        self._close_all_legs(ts, spot, "Roll: close current legs")
        # For a covered call the shares remain; every other strategy is flat between legs.
        if not self._open_cycle(ts, spot):
            self._finish("capital_exhausted", ts, spot)
            self.last_action_message = "Roll failed: the new position could not be funded."
            return False
        self.rolls += 1
        self.suppressed.add(alert_key)
        self.active_alert = None
        self.state = "running"
        self.peak = max(self.peak, self.nav(ts, spot))
        self._record(ts, spot)
        self._add_event(ts, "decision", "Position rolled", "New strikes and expiration are in place.")
        self.last_action_message = "Position rolled. Playback can continue."
        return True

    def liquidate(self) -> bool:
        if self.state not in {"alert", "running"}:
            return False
        ts, spot = self.current_date, self.current_spot
        self._close_all_legs(ts, spot, "Liquidate strategy")
        if self.ledger.spot_units > 0:
            self.ledger.sell_spot(self.ledger.spot_units, spot, self.config.fee_rate, ts, "Liquidate spot")
        self.liquidated = True
        self._finish("liquidated", ts, spot)
        self._record(ts, spot)
        self.last_action_message = "Position liquidated. The scenario is closed."
        return True

    def hold(self) -> bool:
        if self.state not in {"alert", "running"} or self.active_alert is None:
            return False
        ts, spot = self.current_date, self.current_spot
        # Holding suppresses every condition visible today, so the user is not
        # immediately interrupted by a second alert for the same market state.
        self.suppressed.update(self._condition_map(ts, spot).keys())
        self.suppressed.add(self.active_alert.key)
        self.holds += 1
        self.active_alert = None
        self.state = "running"
        self._record(ts, spot)
        self._add_event(ts, "decision", "Held the position", "The contract rides toward expiration.")
        self.last_action_message = "Holding. Playback can continue."
        return True

    # -- recording and finishing ------------------------------------------
    def _record(self, ts: pd.Timestamp, spot: float) -> None:
        nav = self.nav(ts, spot)
        self.peak = max(self.peak, nav)
        dd = nav / self.peak - 1.0 if self.peak > 0 else 0.0
        row = {
            "date": pd.Timestamp(ts),
            "spot": float(spot),
            "nav": nav,
            "drawdown": dd,
            "cash": self.ledger.cash,
            "spot_value": self.ledger.spot_units * spot,
            "option_value": sum(live.value_at(self._option_price(live, ts, spot)) for live in self.open_legs),
            "futures_value": self.open_future.value_at(self._future_price(ts, spot)) if self.open_future else 0.0,
            "equity_index": nav / self.initial_capital * 100.0,
            "state": self.state,
        }
        if self.nav_rows and self.nav_rows[-1]["date"] == row["date"]:
            self.nav_rows[-1] = row
        else:
            self.nav_rows.append(row)

    def _finish(self, reason: str, ts: pd.Timestamp | None = None, spot: float | None = None) -> None:
        if self.state == "finished":
            return
        ts = ts or self.current_date
        spot = spot if spot is not None else self.current_spot
        self.state = "finished"
        self.finish_reason = reason
        self.ended_at = ts
        self.final_nav = self.nav(ts, spot)
        self.peak = max(self.peak, self.final_nav)
        self._record(ts, spot)
        nav = self.nav_series()
        dd = max_drawdown(nav) if len(nav) else 0.0
        self.score_card = score_game(
            self.total_return,
            dd,
            self.premium_yield,
            strategy_key=self.strategy_key,
            reason=reason,
            liquidated=reason == "liquidated",
            assigned=reason in {"assigned", "called_away"},
        )
        self._add_event(
            ts,
            "finish",
            REASON_TITLES.get(reason, "Scenario finished"),
            (
                f"Final NAV {self.final_nav:,.2f} {self.asset.currency}; "
                f"score {self.score_card.score}/100 ({self.score_card.badge})."
            ),
        )

    def _add_event(self, ts: pd.Timestamp, kind: str, title: str, detail: str) -> None:
        self.events.append({"date": pd.Timestamp(ts), "kind": kind, "title": title, "detail": detail})

    # -- result helpers ----------------------------------------------------
    @property
    def reason_title(self) -> str:
        return REASON_TITLES.get(self.finish_reason, "Running")

    def latest_status(self) -> str:
        if self.state == "alert":
            return "PAUSED · decision required"
        if self.state == "finished":
            return self.reason_title
        if self.state == "running":
            return "LIVE · playback"
        return "READY"

    def event_frame(self) -> pd.DataFrame:
        if not self.events:
            return pd.DataFrame(columns=["date", "kind", "title", "detail"])
        return pd.DataFrame(self.events).sort_values("date").reset_index(drop=True)

    def metrics_snapshot(self) -> dict:
        nav = self.nav_series()
        dd = max_drawdown(nav) if len(nav) else 0.0
        return {
            "nav": self.final_nav if self.is_finished else self.nav(),
            "pnl": self.pnl,
            "return": self.total_return,
            "drawdown": dd,
            "premium": self.premium_collected,
            "premium_yield": self.premium_yield,
            "fees": self.fees_paid,
            "rolls": self.rolls,
            "holds": self.holds,
        }


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------


def frame_reset(frame: pd.DataFrame) -> pd.DataFrame:
    clean = frame.copy()
    clean.index = pd.to_datetime(clean.index)
    if getattr(clean.index, "tz", None) is not None:
        clean.index = clean.index.tz_localize(None)
    clean = clean[~clean.index.duplicated(keep="last")].sort_index()
    return clean


def scenario_frame(market: MarketData, scenario: dict) -> pd.DataFrame:
    """Slice a cached asset history to a named game scenario."""
    frame = frame_reset(market.frame)
    lookback_bars = scenario.get("lookback_bars")
    if lookback_bars:
        sliced = frame.tail(min(int(lookback_bars), len(frame)))
    elif scenario.get("start"):
        start = pd.Timestamp(scenario["start"])
        end = pd.Timestamp(scenario.get("end") or frame.index.max())
        sliced = frame[(frame.index >= start) & (frame.index <= end)]
        if len(sliced) < 30:
            return frame.iloc[0:0]
    else:
        sliced = frame
    if len(sliced) < 30:
        # Graceful fallback for lookback/full-history scenarios only.
        sliced = frame.tail(min(len(frame), 120))
    return sliced


def scenario_choices(market: MarketData) -> list[dict]:
    """Return scenarios that have enough data in the current cache."""
    available: list[dict] = []
    for scenario in GAME_SCENARIOS:
        frame = scenario_frame(market, scenario)
        if len(frame) >= 30:
            copy = dict(scenario)
            copy["days"] = int(len(frame))
            available.append(copy)
    return available


def build_game(
    market: MarketData,
    config: StrategyConfig,
    scenario: dict,
) -> ScenarioGame:
    frame = scenario_frame(market, scenario)
    if len(frame) < 30:
        raise GameStartError("This scenario does not have enough history in the local data cache.")
    game = ScenarioGame(
        asset=market.asset,
        config=config,
        frame=frame,
        scenario_label=scenario.get("label", "Custom scenario"),
    )
    game.start()
    return game


def game_result_payload(game: ScenarioGame) -> dict:
    return {
        "asset": game.asset.symbol,
        "strategy": game.strategy_name,
        "scenario": game.scenario_label,
        "reason": game.finish_reason,
        "return": game.total_return,
        "drawdown": game.max_drawdown,
        "premium": game.premium_collected,
        "score": game.score_card.score if game.score_card else 0,
        "badge": game.score_card.badge if game.score_card else "",
    }
