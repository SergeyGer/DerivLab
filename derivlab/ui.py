"""Streamlit interface for DerivLab.

The UI is intentionally explicit rather than "clever": every widget writes to a
plain session-state key, every simulation is cached, and every data failure has
a friendly fallback. That makes the demo reliable on any laptop.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import replace

import pandas as pd
import streamlit as st

from . import charts, theme
from .agents.arena import ArenaError, ArenaResult, default_model_stack, run_arena
from .agents.llm import (
    LOCAL_DECISION_MODEL,
    MODEL_RECOMMENDATIONS,
    LLMSettings,
)
from .agents.personas import AGENTS
from .backtest_engine import BacktestResult, run_backtest
from .config import (
    APP_NAME,
    APP_SUBTITLE,
    APP_TITLE,
    APP_VERSION,
    ASSET_SYMBOLS,
    ASSETS,
    DEFAULT_FEE_BPS,
    DEFAULT_LOOKBACK_YEARS,
    STRATEGY_EDU_DB,
    STRATEGY_META,
    STRATEGY_ORDER,
    TERM_DAYS,
    format_money,
    format_number,
    format_pct,
    get_asset,
    strike_presets,
    suggested_capital,
)
from .data_fetcher import MarketData, MarketDataService, RefreshReport
from .game_mode import (
    GameStartError,
    ScenarioGame,
    build_game,
    scenario_choices,
    scenario_frame,
)
from .strategies import (
    PositionPlan,
    StrategyConfig,
    build_position_plan,
    greeks_table,
)

LOGGER = logging.getLogger(__name__)

PAGE_KEYS = ("strategy", "backtest", "arena", "game", "data", "guide")
PAGE_LABELS = {
    "strategy": "◈  Strategy Deck",
    "backtest": "⌁  Backtest Lab",
    "arena": "✶  AI Arena",
    "game": "◉  Hold the Position",
    "data": "▤  Data Vault",
    "guide": "❖  Field Guide",
}

SOURCE_LABELS = {
    "cache": "Live cache",
    "seed": "Bundled seed",
    "synthetic": "Synthetic fallback",
}

# ---------------------------------------------------------------------------
# Cached services and simulations
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def get_service() -> MarketDataService:
    return MarketDataService()


@st.cache_data(show_spinner=False, ttl=900, max_entries=64)
def load_market_cached(symbol: str, revision: int) -> MarketData:
    return get_service().load(symbol)


@st.cache_data(show_spinner=False, ttl=300, max_entries=8)
def load_coverage_cached(revision: int) -> pd.DataFrame:
    return get_service().coverage()


@st.cache_data(show_spinner=False, ttl=600, max_entries=8)
def load_stats_cached(revision: int) -> dict:
    return get_service().stats()


@st.cache_data(show_spinner=False, ttl=3600, max_entries=96)
def run_backtest_cached(
    symbol: str,
    strategy_key: str,
    capital: float,
    tenor_days: int,
    strike_offset_pct: float,
    iv_multiplier: float,
    risk_free: float,
    fee_bps: float,
    basis_pct: float,
    wing_width_pct: float,
    lookback_years: int,
    revision: int,
) -> BacktestResult:
    market = load_market_cached(symbol, revision)
    config = StrategyConfig(
        strategy_key=strategy_key,
        asset_symbol=symbol,
        capital=float(capital),
        tenor_days=int(tenor_days),
        strike_offset_pct=float(strike_offset_pct),
        iv_multiplier=float(iv_multiplier),
        risk_free=float(risk_free),
        fee_bps=float(fee_bps),
        basis_pct=float(basis_pct),
        wing_width_pct=float(wing_width_pct),
        lookback_years=int(lookback_years),
    )
    return run_backtest(symbol, market.frame, config, lookback_years=lookback_years)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _init_state() -> None:
    defaults = {
        "page": "strategy",
        "active_strategy": "covered_call",
        "data_revision": 0,
        "game": None,
        "game_playing": False,
        "last_refresh": None,
        "arena_result": None,
        "run_variant": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.active_strategy not in STRATEGY_EDU_DB:
        st.session_state.active_strategy = "covered_call"
    if st.session_state.page not in PAGE_KEYS:
        st.session_state.page = "strategy"


def _sync_page() -> None:
    st.session_state.page = st.session_state.get("page_selector", "strategy")


def _goto(page: str) -> None:
    st.session_state.page = page
    st.session_state.page_selector = page


def _goto_button(page: str) -> Callable[[], None]:
    return lambda: _goto(page)


def _sync_strategy_key(source_key: str) -> None:
    value = st.session_state.get(source_key)
    if value in STRATEGY_EDU_DB:
        st.session_state.active_strategy = value


def _set_state(key: str, value: object) -> None:
    st.session_state[key] = value


def _ensure_default(key: str, value: object) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def _revision() -> int:
    return int(st.session_state.get("data_revision", 0))


def _money(value: float | None, asset, compact: bool = True) -> str:
    if value is None:
        return "Unlimited"
    return format_money(value, asset.currency, compact=compact)


def _plot(fig, key: str | None = None) -> None:
    st.plotly_chart(
        fig,
        use_container_width=True,
        theme=None,
        config={"displayModeBar": False, "responsive": True},
        key=key,
    )


def _metric_cards_result(result: BacktestResult) -> list[str]:
    asset = result.asset
    summary = result.summary
    bench = result.benchmark.iloc[-1] / result.initial_capital - 1.0 if len(result.benchmark) else 0.0
    cards = [
        theme.kpi_card(
            "Strategy return",
            format_pct(summary.total_return),
            f"Final NAV {_money(result.final_nav, asset)}",
            "green" if summary.total_return >= 0 else "pink",
        ),
        theme.kpi_card(
            "Buy & hold",
            format_pct(bench),
            f"{result.config.lookback_years}-year window",
            "green" if bench >= 0 else "pink",
        ),
        theme.kpi_card(
            "Max drawdown",
            f"{summary.max_drawdown * 100:.2f}%",
            "Peak-to-trough",
            "pink" if summary.max_drawdown > 0.1 else "amber",
        ),
        theme.kpi_card("Sharpe", format_number(summary.sharpe, 2), "Risk-adjusted return", "cyan"),
        theme.kpi_card("Sortino", format_number(summary.sortino, 2), "Downside-adjusted", "cyan"),
        theme.kpi_card(
            "Win rate",
            f"{summary.win_rate * 100:.1f}%",
            f"{len(result.cycles)} completed cycles",
            "green" if summary.win_rate >= 0.5 else "amber",
        ),
        theme.kpi_card(
            "Premium collected",
            _money(result.premium_collected, asset),
            "Gross short-option premium",
            "green" if result.premium_collected > 0 else "muted",
        ),
    ]
    return cards


def _metric_cards_plan(plan: PositionPlan) -> list[str]:
    asset = plan.asset
    be_text = " · ".join(f"{value:,.2f}" for value in plan.breakevens) if plan.breakevens else "None in range"
    max_profit = "Unlimited" if plan.max_profit is None else _money(plan.max_profit, asset)
    cards = [
        theme.kpi_card(
            "Net premium",
            _money(plan.net_premium, asset),
            "Credit received" if plan.net_premium >= 0 else "Debit paid",
            "green" if plan.net_premium >= 0 else "pink",
        ),
        theme.kpi_card("Max profit", max_profit, "At expiration", "green"),
        theme.kpi_card("Max loss", _money(plan.max_loss, asset), "At expiration", "pink"),
        theme.kpi_card("Break-even(s)", be_text, f"Spot {plan.spot:,.2f}", "amber"),
        theme.kpi_card(
            "Simulated lots",
            f"{plan.contracts:,}",
            f"{plan.units:,.0f} {asset.unit_label}",
            "cyan" if plan.contracts > 0 else "pink",
        ),
        theme.kpi_card("Synthetic IV", f"{plan.iv * 100:.1f}%", "30d HV × multiplier", "magenta"),
        theme.kpi_card("Capital at work", _money(plan.capital_used, asset), "Position footprint", "cyan"),
        theme.kpi_card("Entry costs", _money(plan.entry_fees, asset), "Fees and slippage", "muted"),
    ]
    return cards


# ---------------------------------------------------------------------------
# Sidebar and shell
# ---------------------------------------------------------------------------


def _render_sidebar() -> None:
    with st.sidebar:
        theme.sidebar_brand("Options & futures lab")
        theme.sidebar_label("Navigation")
        if "page_selector" not in st.session_state:
            st.session_state.page_selector = st.session_state.page
        elif st.session_state.page_selector != st.session_state.page:
            # Keep the radio in sync when a page CTA changed the page.
            st.session_state.page_selector = st.session_state.page
        st.radio(
            "Navigation",
            PAGE_KEYS,
            format_func=lambda key: PAGE_LABELS[key],
            key="page_selector",
            label_visibility="collapsed",
            on_change=_sync_page,
        )

        theme.sidebar_label("Data vault")
        try:
            stats = load_stats_cached(_revision())
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Could not read data status: %s", exc)
            stats = {}
        latest = stats.get("latest") or "—"
        source_counts = stats.get("sources", {})
        source_text = (
            f"{source_counts.get('cache', 0)} cache · {source_counts.get('seed', 0)} seed"
            if source_counts
            else "seed bundle"
        )
        theme.sidebar_status(
            [
                ("Assets", f"{stats.get('assets', 0)}/{len(ASSETS)}"),
                ("History rows", f"{stats.get('rows', 0):,}"),
                ("Latest", str(latest)),
                ("Origin", source_text),
            ]
        )
        if stats.get("synthetic"):
            st.caption(f"⚠ {stats['synthetic']} asset(s) use synthetic fallback data.")
        st.button("Open Data Vault", on_click=_goto_button("data"), use_container_width=True)

        theme.sidebar_label("AI desk")
        arena_settings = LLMSettings.from_env()
        theme.sidebar_status(
            [
                ("Mode", "LLM" if arena_settings.enabled else "Local core"),
                (
                    "Critic",
                    arena_settings.critic_model if arena_settings.enabled else "local-critic-v1",
                ),
                (
                    "News",
                    arena_settings.news_model if arena_settings.enabled else "local-newswire-v1",
                ),
            ]
        )
        st.button("Open AI Arena", on_click=_goto_button("arena"), use_container_width=True)

        theme.sidebar_label("Disclaimer")
        st.caption(
            "Educational simulator. Synthetic option chains, not executable quotes. "
            "Nothing here is investment advice."
        )
        st.caption(f"DerivLab v{APP_VERSION}")


def _render_footer() -> None:
    theme.footer()


# ---------------------------------------------------------------------------
# Page 1 - Strategy Deck
# ---------------------------------------------------------------------------


def render_strategy_deck() -> None:
    theme.hero(
        "Strategy deck · screen 01",
        "📈 Options & Futures Strategy Emulator",
        APP_SUBTITLE,
        chips=[
            ("14 instruments", "cyan"),
            ("5 strategies", "green"),
            ("5 years of history", "muted"),
            ("Black-Scholes synthetic chains", "magenta"),
        ],
    )
    left, right = st.columns([0.35, 0.65], gap="large")
    with left:
        theme.section_header("Navigator", "Choose your playbook", "Select a card to load its field guide.")
        if st.session_state.get("strategy_deck_radio") != st.session_state.active_strategy:
            st.session_state.strategy_deck_radio = st.session_state.active_strategy
        st.radio(
            "Strategy",
            STRATEGY_ORDER,
            format_func=lambda key: STRATEGY_EDU_DB[key]["label"],
            key="strategy_deck_radio",
            label_visibility="collapsed",
            on_change=lambda: _sync_strategy_key("strategy_deck_radio"),
        )
        theme.html_block("<div style='height:10px'></div>")
        st.button(
            "Configure & backtest →",
            type="primary",
            use_container_width=True,
            on_click=_goto_button("backtest"),
        )
        st.button(
            "Stress-test this position →",
            use_container_width=True,
            on_click=_goto_button("game"),
        )
        theme.note(
            "Screen 1 is the briefing. Screen 2 turns the selected strategy into a payoff "
            "profile and a historical equity curve. Hold the Position adds real-time decisions."
        )
    with right:
        theme.education_card(STRATEGY_EDU_DB[st.session_state.active_strategy])
        theme.html_block("<div style='height:8px'></div>")
        theme.section_header(
            "Quick comparison",
            "What changes between the five playbooks?",
            "Every strategy uses the same synthetic option engine, so comparisons stay fair.",
        )
        comparison = pd.DataFrame(
            [
                {
                    "Strategy": STRATEGY_EDU_DB[key]["short"],
                    "Premium style": STRATEGY_META[key]["premium_style"].title(),
                    "Risk": STRATEGY_EDU_DB[key]["risk_level"],
                    "Complexity": STRATEGY_EDU_DB[key]["complexity"],
                }
                for key in STRATEGY_ORDER
            ]
        )
        st.dataframe(comparison, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Page 2 - Backtest Lab
# ---------------------------------------------------------------------------


def _asset_format(symbol: str) -> str:
    asset = ASSETS[symbol]
    return f"{symbol} · {asset.short_name}  [{asset.asset_class}]"


def _render_sim_controls(
    symbol: str,
    strategy: str,
    asset,
    md: MarketData,
    prefix: str = "bt",
    include_lookback: bool = True,
) -> StrategyConfig:
    """Render strategy inputs and return the resulting configuration."""
    meta = STRATEGY_META[strategy]
    spot = md.latest_close
    anchor, anchor_text = asset.risk_free_anchor

    cap_key = f"{prefix}_capital_{symbol}"
    _ensure_default(cap_key, suggested_capital(spot, asset.multiplier))
    st.number_input(
        "Capital allocation",
        min_value=1_000,
        max_value=100_000_000,
        step=5_000,
        key=cap_key,
        format="%d",
        help=(
            "Account capital expressed in the instrument's quote currency. "
            "The engine sizes whole simulated lots from this figure."
        ),
    )

    tenor_key = f"{prefix}_tenor_{strategy}"
    _ensure_default(tenor_key, meta["default_tenor"])
    if st.session_state[tenor_key] not in TERM_DAYS:
        st.session_state[tenor_key] = meta["default_tenor"]
    st.selectbox(
        "Expiration window",
        list(TERM_DAYS),
        key=tenor_key,
        format_func=lambda days: f"{days} calendar days",
        help="Options are priced with ACT/365 time to expiry and settled on the first trading day after expiry.",
    )

    offset = 0.0
    wing = 5.0
    mode = meta["strike_mode"]
    if mode in {"call", "put", "straddle"}:
        presets = strike_presets(strategy)
        label_map = {value: label for label, value in presets}
        offset_key = f"{prefix}_offset_{strategy}"
        _ensure_default(offset_key, meta["default_offset"])
        if st.session_state[offset_key] not in label_map:
            st.session_state[offset_key] = meta["default_offset"]
        st.selectbox(
            "Strike selection",
            options=[value for _, value in presets],
            key=offset_key,
            format_func=lambda value: label_map.get(value, f"{value:+.0f}%"),
            help=(
                "Signed distance from spot. Positive values place the strike above spot; "
                "negative values place it below. OTM/ITM labels follow the option direction."
            ),
        )
        offset = float(st.session_state[offset_key])
    elif mode == "condor":
        _ensure_default(f"{prefix}_condor_distance", 5.0)
        _ensure_default(f"{prefix}_condor_wing", 5.0)
        st.slider(
            "Short strike distance (%)",
            min_value=2.0,
            max_value=20.0,
            step=0.5,
            key=f"{prefix}_condor_distance",
            help="Both short strikes are placed this far out of the money.",
        )
        st.slider(
            "Wing width (%)",
            min_value=1.0,
            max_value=10.0,
            step=0.5,
            key=f"{prefix}_condor_wing",
            help="The long wings cap the maximum loss on both sides.",
        )
        offset = float(st.session_state[f"{prefix}_condor_distance"])
        wing = float(st.session_state[f"{prefix}_condor_wing"])

    if strategy == "basis_trade":
        _ensure_default(f"{prefix}_basis_pct", 5.0)
        st.slider(
            "Annualized basis premium (%)",
            min_value=0.0,
            max_value=15.0,
            step=0.5,
            key=f"{prefix}_basis_pct",
            help="Extra contango on top of cost of carry. This is the yield the basis trade captures.",
        )

    with st.expander("Advanced parameters", expanded=False):
        _ensure_default(f"{prefix}_iv_mult", 1.0)
        st.slider(
            "Implied volatility multiplier",
            min_value=0.4,
            max_value=2.0,
            step=0.05,
            key=f"{prefix}_iv_mult",
            help="Synthetic IV = 30-day realized volatility × this multiplier.",
        )
        rf_key = f"{prefix}_rf_{symbol}"
        _ensure_default(rf_key, round(anchor * 100.0, 2))
        st.slider(
            "Risk-free rate (% p.a.)",
            min_value=0.0,
            max_value=10.0,
            step=0.05,
            key=rf_key,
            help=f"Indicative anchor: {anchor_text}. Editable for scenario analysis.",
        )
        _ensure_default(f"{prefix}_fees", DEFAULT_FEE_BPS)
        st.slider(
            "Transaction costs (bps)",
            min_value=0.0,
            max_value=50.0,
            step=1.0,
            key=f"{prefix}_fees",
            help="Applied to every leg's traded notional at entry, settlement, and roll.",
        )
        if include_lookback:
            _ensure_default(f"{prefix}_lookback", DEFAULT_LOOKBACK_YEARS)
            st.selectbox(
                "Historical window",
                [1, 3, 5],
                key=f"{prefix}_lookback",
                format_func=lambda years: f"{years} year{'s' if years > 1 else ''}",
                help="Daily closes from the local cache. Five years is the SRS default.",
            )

    basis_pct = float(st.session_state.get(f"{prefix}_basis_pct", 5.0))
    config = StrategyConfig(
        strategy_key=strategy,
        asset_symbol=symbol,
        capital=float(st.session_state[cap_key]),
        tenor_days=int(st.session_state[tenor_key]),
        strike_offset_pct=float(offset),
        iv_multiplier=float(st.session_state.get(f"{prefix}_iv_mult", 1.0)),
        risk_free=float(st.session_state.get(f"{prefix}_rf_{symbol}", anchor)) / 100.0,
        fee_bps=float(st.session_state.get(f"{prefix}_fees", DEFAULT_FEE_BPS)),
        basis_pct=basis_pct,
        wing_width_pct=float(wing),
        lookback_years=int(st.session_state.get(f"{prefix}_lookback", DEFAULT_LOOKBACK_YEARS)),
    )
    return config


def _capital_warning(plan: PositionPlan, config: StrategyConfig, cap_key: str) -> None:
    asset = plan.asset
    if plan.contracts > 0:
        st.caption(
            f"{plan.contracts} simulated lot(s) · 1 lot ≈ "
            f"{_money(plan.capital_used / max(plan.contracts, 1), asset)} · "
            f"{asset.one_lot_notional_text}"
        )
        return
    recommended = suggested_capital(plan.spot, asset.multiplier, lots=2.0)
    st.warning(
        "The allocation is below the cost of one simulated lot. "
        f"One lot needs roughly {_money(plan.spot * asset.multiplier, asset)}."
    )
    st.button(
        f"Set capital to {_money(recommended, asset)} (2 lots)",
        key=f"fit_{cap_key}",
        on_click=_set_state,
        args=(cap_key, recommended),
        use_container_width=True,
    )


def render_backtest() -> None:
    theme.hero(
        "Backtest lab · screen 02",
        "Configure the trade. Read the risk.",
        "Pick an instrument, tune the strike, expiry, and capital — then compare the payoff profile "
        "with a full historical simulation against buy & hold.",
        chips=[
            ("Interactive payoff", "green"),
            ("Backtrader event loop", "cyan"),
            ("Volatility-aware pricing", "magenta"),
        ],
    )

    if st.session_state.get("bt_strategy") != st.session_state.active_strategy:
        st.session_state.bt_strategy = st.session_state.active_strategy
    if "bt_asset" not in st.session_state:
        st.session_state.bt_asset = "AAPL"

    left, right = st.columns([0.30, 0.70], gap="large")
    with left:
        theme.section_header("Configuration", "Trade builder")
        st.selectbox(
            "Strategy",
            STRATEGY_ORDER,
            key="bt_strategy",
            format_func=lambda key: STRATEGY_EDU_DB[key]["label"],
            on_change=lambda: _sync_strategy_key("bt_strategy"),
        )
        st.selectbox(
            "Asset",
            ASSET_SYMBOLS,
            key="bt_asset",
            format_func=_asset_format,
        )
        strategy = st.session_state.bt_strategy
        symbol = st.session_state.bt_asset
        asset = get_asset(symbol)
        try:
            md = load_market_cached(symbol, _revision())
        except Exception:
            LOGGER.exception("Market data load failed for %s", symbol)
            st.error("Market data could not be loaded. Open the Data Vault and refresh the cache.")
            return
        if md.source == "synthetic":
            st.warning(
                "This asset is using the deterministic offline fallback. "
                "Open Data Vault → Refresh to load real Yahoo Finance history."
            )
        spot = md.latest_close
        hv = md.latest_hv()
        theme.html_block(f"""
            <div style="display:flex;gap:18px;flex-wrap:wrap;margin:2px 0 14px 0;
                        font-family:monospace;">
                <span style="color:#8B93A7;font-size:0.7rem;">SPOT <b style="color:#F5F5F5;">{spot:,.2f}</b></span>
                <span style="color:#8B93A7;font-size:0.7rem;">HV30 <b style="color:#FFD166;">{hv * 100:.1f}%</b></span>
                <span style="color:#8B93A7;font-size:0.7rem;">DATA <b style="color:#00E576;">{md.source.upper()}</b></span>
            </div>
            """)
        config = _render_sim_controls(symbol, strategy, asset, md, prefix="bt")
        plan = build_position_plan(config, spot, hv, md.end)
        cap_key = f"bt_capital_{symbol}"
        _capital_warning(plan, config, cap_key)
        theme.html_block("<div style='height:4px'></div>")
        theme.note(
            "The payoff is a what-if opened at the latest close. The historical backtest "
            "sizes its lots at the first bar of the selected window.",
        )
        theme.html_block("""
            <div class="dl-mini" style="margin-top:10px;">
                <div class="m-label">Model assumptions</div>
                <div class="m-value">Black-Scholes with a flat IV (HV30 × multiplier) · ACT/365 time ·
                editable risk-free rate · bps costs on every leg · whole simulated lots only.</div>
            </div>
            """)

    with right:
        theme.status_bar(
            [
                ("Asset", f"{asset.symbol} · {asset.asset_class}"),
                ("Source", SOURCE_LABELS.get(md.source, md.source)),
                ("Latest bar", md.end.date().isoformat()),
                ("Window", f"{config.lookback_years}Y"),
                ("Fees", f"{config.fee_bps:.0f} bps"),
            ],
            live="SIMULATION READY",
        )
        try:
            result = run_backtest_cached(
                symbol,
                strategy,
                float(config.capital),
                int(config.tenor_days),
                float(config.strike_offset_pct),
                float(config.iv_multiplier),
                float(config.risk_free),
                float(config.fee_bps),
                float(config.basis_pct),
                float(config.wing_width_pct),
                int(config.lookback_years),
                _revision(),
            )
        except Exception as exc:
            LOGGER.exception("Backtest failed for %s/%s", symbol, strategy)
            st.error(
                "This configuration could not be simulated. Try a different asset, strike, "
                "or expiration window."
            )
            with st.expander("Technical details"):
                st.code(f"{type(exc).__name__}: {exc}")
            return

        chart_left, chart_right = st.columns(2, gap="medium")
        with chart_left:
            theme.section_header("Payoff profile", "Expiration P&L")
            _plot(charts.payoff_figure(plan, height=400), key=f"payoff_{symbol}_{strategy}")
            st.caption(
                "Silver dashed = spot · amber dotted = short strike · green dotted = long strike · "
                "amber diamonds = break-even."
            )
        with chart_right:
            theme.section_header("Historical", "Equity vs buy & hold")
            _plot(charts.equity_figure(result, height=400), key=f"equity_{symbol}_{strategy}")

    theme.kpi_grid(_metric_cards_result(result))

    if result.warnings:
        for warning in result.warnings:
            st.info(warning)
    if result.engine != "backtrader":
        st.caption(f"Engine: {result.engine}. Backtrader is the primary event loop.")

    tabs = st.tabs(["Position blueprint", "Performance", "Trade ledger", "Volatility lab"])
    with tabs[0]:
        theme.section_header(
            "Blueprint",
            "What the latest snapshot would open",
            "Sized with today's spot. The historical simulation may have used a different lot count.",
        )
        theme.kpi_grid(_metric_cards_plan(plan))
        if plan.warnings:
            for warning in plan.warnings:
                st.warning(warning)
        if plan.payoff_note:
            theme.note(plan.payoff_note)
        greeks = greeks_table(plan)
        if not greeks.empty:
            display = greeks.copy()
            display["IV"] = display["IV"].apply(
                lambda value: f"{float(value) * 100:.1f}%" if value not in {None, "—"} else "—"
            )
            display["Premium"] = display["Premium"].apply(lambda value: f"{float(value):,.2f}")
            display["Strike"] = display["Strike"].apply(lambda value: f"{float(value):,.2f}")
            for column in ("Delta", "Theta / day", "Vega / pt", "Notional"):
                display[column] = display[column].apply(lambda value: f"{float(value):,.1f}")
            st.dataframe(display, hide_index=True, use_container_width=True)
        theme.note(
            "Delta is unit spot exposure, theta is P&L per calendar day, and vega is P&L per "
            "one volatility point. Values are aggregated across all simulated lots.",
        )
    with tabs[1]:
        theme.section_header("Performance", "Historical metrics", "Daily NAV, marked to market at each close.")
        summary = result.summary
        perf_cards = [
            theme.kpi_card("Total return", format_pct(summary.total_return), f"Final {_money(result.final_nav, asset)}", "green" if summary.total_return >= 0 else "pink"),
            theme.kpi_card("CAGR", format_pct(summary.cagr), "Annualized", "cyan"),
            theme.kpi_card("Max drawdown", f"{summary.max_drawdown * 100:.2f}%", "Peak-to-trough", "pink"),
            theme.kpi_card("Sharpe", format_number(summary.sharpe, 2), "252-day annualized", "cyan"),
            theme.kpi_card("Sortino", format_number(summary.sortino, 2), "Downside-adjusted", "cyan"),
            theme.kpi_card("Win rate", f"{summary.win_rate * 100:.1f}%", "Per closed cycle", "green"),
            theme.kpi_card("Profit factor", format_number(summary.profit_factor, 2), "Gains / losses", "amber"),
            theme.kpi_card("Calmar", format_number(summary.calmar, 2), "CAGR / max DD", "cyan"),
        ]
        theme.kpi_grid(perf_cards)
        if strategy == "basis_trade":
            theme.note(
                "The basis trade uses an idealized, frictionless convergence hedge. Its Sharpe and "
                "Sortino ratios are therefore an upper bound; real carry trades carry funding, margin, "
                "and counterparty risk.",
                tone="amber",
            )
        _plot(charts.cycle_pnl_figure(result, height=290), key=f"cycles_{symbol}_{strategy}")
    with tabs[2]:
        theme.section_header("Trade ledger", "Cycles and executions", "Every synthetic fill, fee, and expiration.")
        if result.cycles.empty:
            st.info("No cycles were completed in this window.")
        else:
            cycles = result.cycles.copy()
            cycles["start"] = pd.to_datetime(cycles["start"]).dt.date
            cycles["end"] = pd.to_datetime(cycles["end"]).dt.date
            cycles["pnl"] = cycles["pnl"].apply(lambda value: f"{float(value):,.2f}")
            cycles["return"] = cycles["return"].apply(lambda value: f"{float(value) * 100:+.2f}%")
            st.dataframe(cycles, hide_index=True, use_container_width=True)
        if result.trades.empty:
            st.info("No trades were executed.")
        else:
            trades = result.trades.copy()
            trades["as_of"] = pd.to_datetime(trades["as_of"]).dt.date
            for column in ("price", "cash_flow", "fees"):
                trades[column] = trades[column].apply(lambda value: f"{float(value):,.2f}")
            trades["quantity"] = trades["quantity"].apply(lambda value: f"{float(value):,.1f}")
            st.dataframe(
                trades.rename(
                    columns={
                        "as_of": "Date",
                        "action": "Action",
                        "instrument": "Instrument",
                        "quantity": "Qty",
                        "price": "Price",
                        "cash_flow": "Cash flow",
                        "fees": "Fees",
                        "note": "Note",
                    }
                ),
                hide_index=True,
                use_container_width=True,
                height=360,
            )
    with tabs[3]:
        theme.section_header("Volatility lab", "Realized volatility becomes synthetic IV", "IV is recomputed each day from the trailing 30-day HV series.")
        _plot(charts.volatility_figure(result, height=280), key=f"iv_{symbol}_{strategy}")
        st.caption(
            "The engine does not use a live option chain. At each step it calculates HV30 from "
            "daily log returns, applies the IV multiplier, and prices the synthetic chain with Black-Scholes."
        )
        theme.kpi_grid(
            [
                theme.kpi_card("Current IV", f"{plan.iv * 100:.1f}%", "Synthetic", "magenta"),
                theme.kpi_card("HV window", "30 days", "Daily log returns", "muted"),
                theme.kpi_card("Risk-free", f"{config.risk_free * 100:.2f}%", asset.currency, "cyan"),
                theme.kpi_card("Dividend yield", f"{asset.dividend_yield * 100:.2f}%", "Continuous q", "muted"),
            ]
        )


# ---------------------------------------------------------------------------
# Page 3 - Hold the Position
# ---------------------------------------------------------------------------


def _game_setup() -> None:
    left, right = st.columns([0.40, 0.60], gap="large")
    with left:
        theme.section_header("Scenario setup", "Build the live position")
        if st.session_state.get("game_strategy") != st.session_state.active_strategy:
            st.session_state.game_strategy = st.session_state.active_strategy
        st.selectbox(
            "Strategy",
            STRATEGY_ORDER,
            key="game_strategy",
            format_func=lambda key: STRATEGY_EDU_DB[key]["label"],
            on_change=lambda: _sync_strategy_key("game_strategy"),
        )
        if "game_asset" not in st.session_state:
            st.session_state.game_asset = st.session_state.get("bt_asset", "AAPL")
        st.selectbox(
            "Asset",
            ASSET_SYMBOLS,
            key="game_asset",
            format_func=_asset_format,
        )
        symbol = st.session_state.game_asset
        strategy = st.session_state.game_strategy
        asset = get_asset(symbol)
        try:
            md = load_market_cached(symbol, _revision())
        except Exception:
            LOGGER.exception("Game market data load failed")
            st.error("Market data could not be loaded. Open the Data Vault and refresh the cache.")
            return

        choices = scenario_choices(md)
        if not choices:
            st.error("No historical scenario has enough data for this asset.")
            return
        choice_ids = [choice["id"] for choice in choices]
        if st.session_state.get("game_scenario") not in choice_ids:
            st.session_state.game_scenario = choice_ids[0]
        st.selectbox(
            "Historical scenario",
            choice_ids,
            key="game_scenario",
            format_func=lambda cid: next(
                (f"{choice['label']} · {choice['days']} days" for choice in choices if choice["id"] == cid),
                cid,
            ),
        )
        scenario = next(choice for choice in choices if choice["id"] == st.session_state.game_scenario)
        st.caption(scenario.get("blurb", ""))

        config = _render_sim_controls(
            symbol, strategy, asset, md, prefix="game", include_lookback=False
        )
        frame = scenario_frame(md, scenario)
        if frame.empty:
            st.error("This scenario has no usable bars in the current cache.")
            return
        start_ts = frame.index[0]
        hv_series = md.hv_series()
        try:
            hv0 = float(hv_series.loc[start_ts])
        except (KeyError, TypeError, ValueError):
            hv0 = md.latest_hv()
        if not math.isfinite(hv0) or hv0 <= 0:
            hv0 = asset.base_iv
        preview = build_position_plan(config, float(frame["Close"].iloc[0]), hv0, start_ts)
        theme.html_block("<div style='height:4px'></div>")
        theme.note(
            "Playback advances one trading day per second. Risk alerts pause the tape and "
            "unlock the roll / hold / liquidate decision panel."
        )
        if preview.contracts == 0:
            st.warning(
                "The allocation cannot open one simulated lot at the scenario start. "
                "Increase capital in the builder above."
            )
        start_disabled = preview.contracts == 0
        if st.button(
            "▶ Launch scenario",
            type="primary",
            use_container_width=True,
            disabled=start_disabled,
            key="game_launch",
        ):
            try:
                game = build_game(md, config, scenario)
            except GameStartError as exc:
                st.warning(str(exc))
            except Exception as exc:
                LOGGER.exception("Could not start game")
                st.error("The scenario could not be started. Adjust the parameters and try again.")
                with st.expander("Technical details"):
                    st.code(f"{type(exc).__name__}: {exc}")
            else:
                st.session_state.game = game
                st.session_state.game_playing = False
                st.rerun()

    with right:
        theme.section_header("Mission briefing", "What you are about to trade", "A tactical management drill, not a static backtest.")
        theme.kpi_grid(
            [
                theme.kpi_card("Scenario start", f"{frame.index[0].date()}", f"{len(frame)} trading days", "cyan"),
                theme.kpi_card("Opening spot", f"{frame['Close'].iloc[0]:,.2f}", asset.currency, "green"),
                theme.kpi_card("Simulated lots", f"{preview.contracts:,}", f"{preview.units:,.0f} {asset.unit_label}", "cyan"),
                theme.kpi_card(
                    "Net premium",
                    _money(preview.net_premium, asset),
                    "Credit" if preview.net_premium >= 0 else "Debit",
                    "green" if preview.net_premium >= 0 else "pink",
                ),
                theme.kpi_card("Max loss", _money(preview.max_loss, asset), "At expiration", "pink"),
                theme.kpi_card("Risk-free", f"{config.risk_free * 100:.2f}%", asset.currency, "muted"),
            ]
        )
        theme.html_block("""
            <div class="dl-mini-grid" style="margin-top:14px;">
                <div class="dl-mini">
                    <div class="m-label">01 · Playback</div>
                    <div class="m-value">One simulated trading day per real-world second. Use Step or Fast-forward for a quicker demo.</div>
                </div>
                <div class="dl-mini">
                    <div class="m-label">02 · Risk alerts</div>
                    <div class="m-value">Strike breaches and drawdown thresholds pause the tape and open the decision terminal.</div>
                </div>
                <div class="dl-mini">
                    <div class="m-label">03 · Decisions</div>
                    <div class="m-value">Roll the option legs, hold to expiration, or liquidate the whole strategy.</div>
                </div>
                <div class="dl-mini">
                    <div class="m-label">04 · Debrief</div>
                    <div class="m-value">A performance score and a thematic profile badge summarise the run.</div>
                </div>
            </div>
            """)
        theme.note(
            "The score blends final P&L, maximum drawdown, and premium efficiency. Losing runs "
            "are part of the lesson: the badge describes behaviour, not a recommendation.",
            tone="amber",
        )


def _game_status_items(game: ScenarioGame) -> list[tuple[str, str]]:
    return [
        ("Date", game.current_date.date().isoformat()),
        ("Spot", f"{game.current_spot:,.2f}"),
        ("NAV", _money(game.nav(), game.asset)),
        ("P&L", _money(game.pnl, game.asset)),
        ("Drawdown", f"{game.current_drawdown * 100:.2f}%"),
        ("Premium", _money(game.premium_collected, game.asset)),
    ]


def _game_kpis(game: ScenarioGame) -> list[str]:
    asset = game.asset
    live_nav = game.final_nav if game.is_finished else game.nav()
    return [
        theme.kpi_card("Portfolio NAV", _money(live_nav, asset), "Marked to market", "cyan"),
        theme.kpi_card(
            "Unrealized P&L",
            _money(live_nav - game.initial_capital, asset),
            f"Return {format_pct(game.total_return)}",
            "green" if live_nav >= game.initial_capital else "pink",
        ),
        theme.kpi_card("Max drawdown", f"{game.max_drawdown * 100:.2f}%", "So far", "pink"),
        theme.kpi_card("Premium collected", _money(game.premium_collected, asset), "Gross", "green"),
        theme.kpi_card("Rolls", f"{game.rolls}", "Tactical adjustments", "amber"),
        theme.kpi_card("Holds", f"{game.holds}", "Let it ride", "muted"),
        theme.kpi_card("Tape", f"{game.days_elapsed}/{game.days_total}", f"{game.progress * 100:.0f}% complete", "cyan"),
    ]


def _game_events_expander(game: ScenarioGame) -> None:
    events = game.event_frame()
    if events.empty:
        return
    with st.expander("Decision log and market events", expanded=False):
        display = events.tail(30).copy()
        display["date"] = pd.to_datetime(display["date"]).dt.date
        st.dataframe(display, hide_index=True, use_container_width=True)


def _render_game_alert_area(game: ScenarioGame, running: bool, playing: bool) -> None:
    """Render the paused decision area without forcing a full-app rerun.

    All state changes are picked up by the always-on fragment timer (1 s), so
    playback continues smoothly and the DOM tree is not torn down mid-update.
    """
    if game.state == "alert" and game.active_alert is not None:
        alert = game.active_alert
        theme.risk_alert(
            alert.title,
            alert.message,
            [
                ("Date", alert.as_of.date().isoformat()),
                ("Spot", f"{alert.spot:,.2f}"),
                ("NAV", _money(alert.nav, game.asset)),
                ("Drawdown", f"{alert.drawdown * 100:.1f}%"),
                ("Leg", alert.leg or "Portfolio"),
            ],
            severity=alert.severity,
        )
        can_roll, roll_reason = game.can_roll()
        theme.html_block("""
            <div class="dl-decision">
                <h3>Decision terminal</h3>
                <p>Playback is paused. Choose how to manage the position. The score is calculated at the end of the scenario.</p>
            </div>
            """)
        decision = st.columns(3)
        if decision[0].button(
            "⟳ Roll Position",
            key="decision_roll",
            type="primary",
            disabled=not can_roll,
            use_container_width=True,
            help=roll_reason,
        ):
            if game.roll():
                st.session_state.game_playing = True
            else:
                st.error(game.last_action_message or "The roll could not be executed.")
        if decision[1].button(
            "Hold / Do Nothing",
            key="decision_hold",
            use_container_width=True,
            help="Let the contract ride toward expiration. Holding suppresses this alert until the condition clears.",
        ):
            game.hold()
            st.session_state.game_playing = True
        if decision[2].button(
            "Liquidate / Close",
            key="decision_liquidate",
            use_container_width=True,
            help="Close the underlying and every derivative leg immediately.",
        ):
            game.liquidate()
            st.session_state.game_playing = False
        if not can_roll:
            st.caption(f"Roll unavailable: {roll_reason}")
    elif running:
        if playing:
            st.caption("Playback is live: one simulated trading day per second.")
        else:
            st.caption("Playback paused. Press Play, Step, or Fast-forward to continue.")


def _render_game_live(game: ScenarioGame) -> None:
    theme.status_bar(_game_status_items(game), live=game.latest_status())
    st.progress(
        min(max(game.progress, 0.0), 1.0),
        text=f"Tape {game.days_elapsed}/{game.days_total} · {game.current_date.date()} · "
        f"{game.scenario_label}",
    )

    running = game.state == "running"
    playing = bool(st.session_state.get("game_playing"))
    _render_game_alert_area(game, running, playing)
    # A stable key lets Plotly update the same React node every second instead of
    # replacing the chart on each tick. This is what prevents the frontend
    # "removeChild" DOM error during long auto-play sessions.
    _plot(charts.price_path_figure(game, height=470), key="game_live_chart")
    theme.kpi_grid(_game_kpis(game))

    controls = st.columns([1, 1, 1.2, 1.2, 1])
    if controls[0].button("▶ Play", key="game_play", type="primary", disabled=(not running or playing), use_container_width=True):
        st.session_state.game_playing = True
    if controls[1].button("Pause", key="game_pause", disabled=(not playing), use_container_width=True):
        st.session_state.game_playing = False
    if controls[2].button("Step +1 day", key="game_step", disabled=not running, use_container_width=True):
        game.advance()
        st.session_state.game_playing = False
    if controls[3].button(
        "Fast-forward → alert",
        key="game_fast",
        disabled=not running,
        use_container_width=True,
        help="Run the tape at full speed until the next alert or the end of the scenario.",
    ):
        for _ in range(min(game.days_total, 400)):
            if game.state != "running":
                break
            game.advance()
        st.session_state.game_playing = False
    if controls[4].button("New scenario", key="game_reset", use_container_width=True):
        st.session_state.game = None
        st.session_state.game_playing = False
        st.rerun()

    _game_events_expander(game)


OUTCOME_LABELS = {
    "period_end": "Complete",
    "liquidated": "Liquidated",
    "assigned": "Assigned",
    "called_away": "Called away",
    "capital_exhausted": "Capital out",
}


def _outcome_label(reason: str) -> str:
    return OUTCOME_LABELS.get(reason, "Complete")


def _render_game_results(game: ScenarioGame) -> None:
    score = game.score_card
    left, right = st.columns([0.62, 0.38], gap="large")
    with left:
        if score is not None:
            theme.badge_card(score)
        theme.kpi_grid(
            [
                theme.kpi_card("Final NAV", _money(game.final_nav, game.asset), "Marked at scenario end", "cyan"),
                theme.kpi_card(
                    "Total return",
                    format_pct(game.total_return),
                    f"P&L {_money(game.final_nav - game.initial_capital, game.asset)}",
                    "green" if game.total_return >= 0 else "pink",
                ),
                theme.kpi_card("Max drawdown", f"{game.max_drawdown * 100:.2f}%", "Peak-to-trough", "pink"),
                theme.kpi_card("Premium collected", _money(game.premium_collected, game.asset), "Gross", "green"),
                theme.kpi_card("Final outcome", _outcome_label(game.finish_reason), game.ended_at.date().isoformat() if game.ended_at else "—", "amber"),
                theme.kpi_card("Decisions", f"{game.rolls + game.holds}", f"{game.rolls} rolls · {game.holds} holds", "cyan"),
                theme.kpi_card("Fees", _money(game.fees_paid, game.asset), "Total costs", "muted"),
                theme.kpi_card("Tape", f"{game.days_elapsed}/{game.days_total}", "Trading days", "muted"),
            ]
        )
        _plot(charts.price_path_figure(game, height=460), key="game_result_chart")
        _game_events_expander(game)
    with right:
        if score is not None:
            _plot(charts.score_bar_figure(score.score), key="score_gauge")
            theme.section_header("Score breakdown", "How the run was graded")
            breakdown = pd.DataFrame(
                [
                    {"Component": name, "Points": f"{points:+.1f}", "Why": why}
                    for name, points, why in score.breakdown
                ]
            )
            st.dataframe(breakdown, hide_index=True, use_container_width=True)
            st.caption(
                "The score is educational: it rewards return, drawdown control, and premium "
                "efficiency, while penalising an early forced exit."
            )
        theme.html_block("<div style='height:8px'></div>")
        if st.button("↺ Run another scenario", key="game_again", type="primary", use_container_width=True):
            st.session_state.game = None
            st.session_state.game_playing = False
            st.rerun()
        if st.button("Back to Strategy Deck", key="game_to_deck", use_container_width=True):
            _goto("strategy")
            st.rerun()
        theme.note(
            "This debrief is a teaching aid, not a forecast. Re-run the same scenario with a "
            "different decision style to compare the outcome."
        )


def render_game() -> None:
    theme.hero(
        "Tactical mode · gamification",
        "Hold the Position.",
        "Run a historical scenario one day at a time. When the market breaches a risk trigger, "
        "the tape pauses and you decide: roll, hold, or liquidate.",
        chips=[
            ("1 simulated day / second", "green"),
            ("Interactive risk alerts", "pink"),
            ("Performance scoring", "amber"),
        ],
    )
    game = st.session_state.get("game")
    if game is None:
        _game_setup()
        return
    if not isinstance(game, ScenarioGame):
        st.session_state.game = None
        st.rerun()
        return

    st.caption(
        f"{game.asset.symbol} · {game.strategy_name} · {game.scenario_label} · "
        f"{game.days_total} trading days"
    )

    # Keep the fragment mounted for the whole game with a constant timer. The
    # timer advances only while the user is playing; alerts, decisions, debriefs,
    # and play/pause changes no longer call st.rerun() inside the fragment.
    @st.fragment(run_every=1.0)
    def _game_fragment() -> None:
        live_game = st.session_state.get("game")
        if not isinstance(live_game, ScenarioGame):
            st.rerun()
            return
        if live_game.state == "running" and st.session_state.get("game_playing"):
            live_game.advance()
        if live_game.state == "finished":
            _render_game_results(live_game)
        else:
            _render_game_live(live_game)

    _game_fragment()


# ---------------------------------------------------------------------------
# Page 3b - AI Arena
# ---------------------------------------------------------------------------


def _arena_stack(
    settings: LLMSettings,
    use_llm: bool,
    use_llm_decisions: bool,
) -> list[dict[str, object]]:
    effective = settings if (settings.enabled and use_llm) else LLMSettings.local()
    return default_model_stack(
        effective,
        use_llm_decisions=bool(use_llm and use_llm_decisions),
    )


def _arena_desk_cards(
    settings: LLMSettings,
    use_llm: bool,
    use_llm_decisions: bool,
) -> list[dict[str, object]]:
    llm_decides = bool(settings.enabled and use_llm and use_llm_decisions)
    model = settings.decision_model if llm_decides else LOCAL_DECISION_MODEL
    source = "llm" if llm_decides else "policy"
    return [
        {
            "key": agent.key,
            "name": agent.name,
            "avatar": agent.avatar,
            "role": agent.role,
            "color": agent.color,
            "mandate": agent.mandate,
            "model": model,
            "source": source,
        }
        for agent in AGENTS
    ]


def _arena_leaderboard_view(result: ArenaResult) -> pd.DataFrame:
    frame = result.leaderboard.copy()
    frame["Return"] = frame["Return"].map(lambda value: f"{float(value) * 100:+.1f}%")
    frame["Max Drawdown"] = frame["Max Drawdown"].map(lambda value: f"{float(value) * 100:.1f}%")
    frame["Sharpe"] = frame["Sharpe"].map(lambda value: f"{float(value):.2f}")
    frame["Sortino"] = frame["Sortino"].map(lambda value: f"{float(value):.2f}")
    frame["Win Rate"] = frame["Win Rate"].map(lambda value: f"{float(value) * 100:.0f}%")
    frame["Premium"] = frame["Premium"].map(
        lambda value: format_money(float(value), result.asset.currency, compact=True)
    )
    frame["Score"] = frame["Score"].map(lambda value: f"{float(value):.1f}")
    frame["Model"] = frame["Model"].astype(str).str.slice(0, 64)
    return frame[
        ["Rank", "Desk", "Strategy", "Model", "Return", "Max Drawdown", "Sharpe", "Premium", "Score"]
    ]


def _arena_kpis(result: ArenaResult) -> list[str]:
    user = result.user
    alpha = result.alpha
    winner = result.winner
    winner_label = "You" if winner.is_user else winner.name.replace(" AI", "")
    return [
        theme.kpi_card(
            "User rank",
            f"#{result.user_rank}/4",
            f"{user.score:.1f} / 100 score",
            "green" if result.user_rank == 1 else "amber",
        ),
        theme.kpi_card("Cycle winner", winner_label, f"{winner.score:.1f} / 100", "green"),
        theme.kpi_card(
            "Your return",
            format_pct(user.return_pct),
            f"Max DD {user.max_dd_pct * 100:.1f}%",
            "green" if user.return_pct >= 0 else "pink",
        ),
        theme.kpi_card(
            "AlphaVanguard",
            format_pct(alpha.return_pct),
            f"Sharpe {alpha.sharpe:.2f}",
            "green" if alpha.return_pct >= 0 else "pink",
        ),
        theme.kpi_card(
            "Gap vs Alpha",
            f"{result.alpha_gap * 100:+.1f} pp",
            "Return difference",
            "green" if result.alpha_gap >= 0 else "pink",
        ),
        theme.kpi_card(
            "Critical triggers",
            f"{len(result.triggers)}",
            "Breach / assignment / IV",
            "pink" if result.triggers else "muted",
        ),
    ]


def _render_arena_result(result: ArenaResult) -> None:
    theme.status_bar(
        [
            ("Asset", f"{result.asset.symbol} · {result.asset.asset_class}"),
            ("Scenario", result.scenario),
            ("Winner", result.winner.name),
            ("Your rank", f"#{result.user_rank}/4"),
            ("Use LLM", "yes" if result.use_llm else "no"),
        ],
        live="AI ARENA · CYCLE COMPLETE",
    )
    decision_models = {entry.model for entry in result.agents}
    theme.ai_status(
        [
            (
                "Trade models",
                ", ".join(sorted(decision_models)) if len(decision_models) > 1 else next(iter(decision_models)),
                "green",
            ),
            ("Critic model", result.report.model, "cyan"),
            ("News model", result.news.model, "magenta"),
        ]
    )
    theme.kpi_grid(_arena_kpis(result))

    theme.section_header("Desk race", "Four mandates, one historical tape")
    _plot(charts.arena_equity_figure(result, height=430), key="arena_equity")
    st.caption(
        "All four desks start with the same capital and the same historical window. "
        "The user desk is the dashed white line; AI mandates are solid."
    )

    theme.section_header("Leaderboard", "Composite score", "Return + drawdown + Sharpe + premium efficiency.")
    st.dataframe(
        _arena_leaderboard_view(result),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Model": st.column_config.TextColumn("Model", width="large"),
            "Desk": st.column_config.TextColumn("Desk", width="medium"),
            "Score": st.column_config.TextColumn("Score", width="small"),
        },
    )
    theme.note(
        "The score is a teaching device, not an investment rating. The table shows the exact "
        "decision model for every desk; open the Model stack tab for critic/news roles and latency.",
        tone="amber",
    )

    theme.section_header(
        "AlphaVanguard AI · rival fund manager",
        "Tactical performance review",
        f"Critic model: {result.report.model} · source: {result.report.source}",
    )
    with st.container(border=True):
        st.markdown(result.report.markdown)
    if result.report.source == "local" and result.settings.enabled and result.use_llm:
        st.caption(f"LLM fallback: {result.report.error or 'local deterministic critic used.'}")
    else:
        st.caption(
            "This report is generated against the supplied metrics and critical triggers; "
            "it is educational commentary, not investment advice."
        )

    theme.section_header(
        "NewsWire · cyberpunk market wire",
        "After-hours transmissions",
        f"News model: {result.news.model} · source: {result.news.source}",
    )
    theme.news_grid(result.news.items)
    if result.news.error:
        st.caption(f"Wire fallback: {result.news.error}")

    tabs = st.tabs(["Agent mandates", "Trigger timeline", "Model stack", "Market context"])
    with tabs[0]:
        theme.section_header("Mandates", "How each rival desk played the cycle")
        decisions = {entry.key: entry.decision for entry in result.agents if entry.decision}
        theme.agent_cards(result.agents, decisions=decisions)
        mandate_rows = [
            {
                "Desk": entry.name,
                "Model": entry.model,
                "Strategy": entry.strategy_name,
                "Tenor": f"{entry.decision.tenor_days}d" if entry.decision else "—",
                "Strike offset": f"{entry.decision.strike_offset_pct:+.1f}%" if entry.decision else "—",
                "Rationale": entry.decision.rationale if entry.decision else "—",
            }
            for entry in result.agents
        ]
        st.dataframe(pd.DataFrame(mandate_rows), hide_index=True, use_container_width=True)
        if result.warnings:
            for warning in result.warnings:
                st.warning(warning)
    with tabs[1]:
        theme.section_header("Triggers", "What the critic saw", "Strike breaches, assignments, IV spikes, and drawdowns.")
        if result.triggers:
            trigger_rows = pd.DataFrame(
                [
                    {
                        "Date": item.get("date"),
                        "Type": str(item.get("kind", "")).replace("_", " ").title(),
                        "Event": item.get("title"),
                        "Detail": item.get("detail"),
                        "Severity": item.get("severity"),
                    }
                    for item in result.triggers
                ]
            )
            st.dataframe(trigger_rows, hide_index=True, use_container_width=True)
        else:
            st.info("No critical trigger was recorded for the user desk in this scenario.")
    with tabs[2]:
        theme.section_header("Model stack", "Active models and recommendations")
        theme.model_stack(result.model_stack, MODEL_RECOMMENDATIONS)
        llm_rows = []
        status = result.llm_status
        decision = status.get("decision_result")
        llm_rows.append(
            {
                "Stage": "Agent trade decisions",
                "Model": decision.get("model") if isinstance(decision, dict) else LOCAL_DECISION_MODEL,
                "Source": decision.get("source") if isinstance(decision, dict) else "local",
                "Latency ms": decision.get("latency_ms") if isinstance(decision, dict) else 0,
                "Error": decision.get("error") if isinstance(decision, dict) else "",
            }
        )
        llm_rows.append(
            {
                "Stage": "AlphaVanguard critic",
                "Model": result.report.model,
                "Source": result.report.source,
                "Latency ms": result.report.latency_ms,
                "Error": result.report.error,
            }
        )
        llm_rows.append(
            {
                "Stage": "NewsWire",
                "Model": result.news.model,
                "Source": result.news.source,
                "Latency ms": result.news.latency_ms,
                "Error": result.news.error,
            }
        )
        st.dataframe(pd.DataFrame(llm_rows), hide_index=True, use_container_width=True)
        st.caption(
            "Set DERIVLAB_LLM_PROVIDER, DERIVLAB_LLM_MODEL, and DERIVLAB_LLM_API_KEY to use "
            "a live LLM. Without a key, every output is deterministic and local."
        )
    with tabs[3]:
        theme.section_header("Pre-simulation context", "What the agents knew before the first bar")
        context = result.context
        theme.kpi_grid(
            [
                theme.kpi_card("HV30", f"{context.hv30 * 100:.1f}%", "Pre-scenario", "magenta"),
                theme.kpi_card("HV percentile", f"{context.hv_percentile * 100:.0f}%", "Trailing regime", "cyan"),
                theme.kpi_card("Trend 20d", format_pct(context.trend20), context.trend_label, "green" if context.trend20 >= 0 else "pink"),
                theme.kpi_card("Trend 60d", format_pct(context.trend60), "Structural drift", "green" if context.trend60 >= 0 else "pink"),
                theme.kpi_card("Drawdown 120d", format_pct(context.drawdown120), "Prior peak", "pink"),
                theme.kpi_card("Vol ratio", f"{context.vol_ratio:.2f}×", "HV / trailing mean", "amber"),
                theme.kpi_card("Regime", context.regime.title(), context.trend_label.title(), "cyan"),
                theme.kpi_card("Capital", _money(context.capital, result.asset), "Per desk", "muted"),
            ]
        )
        st.caption(
            "The context is computed strictly before the scenario start; no future bars are "
            "visible to the autonomous desks."
        )

    if st.button("↺ Clear AI results", key="arena_clear", use_container_width=True):
        st.session_state.arena_result = None
        st.rerun()


def render_arena() -> None:
    theme.hero(
        "AI Arena · institutional simulation",
        "Trade against the machine.",
        "Three autonomous desks read the regime, choose their own mandates, and trade the same "
        "historical tape as you. AlphaVanguard AI reviews the cycle; NewsWire prints the wire.",
        chips=[
            ("3 autonomous desks", "green"),
            ("LLM optional", "cyan"),
            ("Cyberpunk news wire", "magenta"),
            ("Local fallback", "amber"),
        ],
    )

    settings = LLMSettings.from_env()
    if "arena_asset" not in st.session_state:
        st.session_state.arena_asset = st.session_state.get("bt_asset", "AAPL")
    if st.session_state.get("arena_strategy") not in STRATEGY_EDU_DB:
        st.session_state.arena_strategy = st.session_state.active_strategy

    left, right = st.columns([0.34, 0.66], gap="large")
    with left:
        theme.section_header("User mandate", "Your desk")
        if st.session_state.get("arena_strategy") != st.session_state.active_strategy:
            st.session_state.arena_strategy = st.session_state.active_strategy
        st.selectbox(
            "Strategy",
            STRATEGY_ORDER,
            key="arena_strategy",
            format_func=lambda key: STRATEGY_EDU_DB[key]["label"],
            on_change=lambda: _sync_strategy_key("arena_strategy"),
        )
        st.selectbox(
            "Asset",
            ASSET_SYMBOLS,
            key="arena_asset",
            format_func=_asset_format,
        )
        strategy = st.session_state.arena_strategy
        symbol = st.session_state.arena_asset
        asset = get_asset(symbol)
        try:
            md = load_market_cached(symbol, _revision())
        except Exception:
            LOGGER.exception("AI Arena market load failed")
            st.error("Market data could not be loaded. Open the Data Vault and refresh the cache.")
            return

        choices = scenario_choices(md)
        if not choices:
            st.error("No historical scenario has enough data for the AI Arena.")
            return
        choice_ids = [choice["id"] for choice in choices]
        if st.session_state.get("arena_scenario") not in choice_ids:
            st.session_state.arena_scenario = "rate_shock_2022" if "rate_shock_2022" in choice_ids else choice_ids[0]
        st.selectbox(
            "Historical scenario",
            choice_ids,
            key="arena_scenario",
            format_func=lambda cid: next(
                (f"{choice['label']} · {choice['days']} days" for choice in choices if choice["id"] == cid),
                cid,
            ),
        )
        scenario = next(choice for choice in choices if choice["id"] == st.session_state.arena_scenario)
        st.caption(scenario.get("blurb", ""))
        frame = scenario_frame(md, scenario)
        if frame.empty:
            st.error("This scenario has no usable bars in the current cache.")
            return

        user_config = replace(
            _render_sim_controls(symbol, strategy, asset, md, prefix="arena", include_lookback=False),
            lookback_years=10,
        )
        cap_key = f"arena_capital_{symbol}"
        start_ts = frame.index[0]
        try:
            hv0 = float(md.hv_series().loc[start_ts])
        except (KeyError, TypeError, ValueError):
            hv0 = md.latest_hv()
        if not math.isfinite(hv0) or hv0 <= 0:
            hv0 = asset.base_iv
        preview = build_position_plan(
            user_config,
            float(frame["Close"].iloc[0]),
            hv0,
            start_ts,
        )
        _capital_warning(preview, user_config, cap_key)

        use_llm = False
        use_llm_decisions = False
        if settings.enabled:
            use_llm = st.checkbox(
                "Use configured LLM for critique and news",
                value=True,
                key="arena_use_llm",
                help="One critic call and one news call per cycle; results are cached in session state.",
            )
            use_llm_decisions = st.checkbox(
                "Let the LLM choose the three agent mandates",
                value=False,
                key="arena_use_llm_decisions",
                help=(
                    "Off = deterministic, reproducible policies. On = one JSON decision call for "
                    "all three desks, with local fallback for invalid outputs."
                ),
            )
        else:
            theme.note(
                "No LLM credentials detected. The arena runs with the deterministic local quant "
                "core and local critic/newswire. Configure DERIVLAB_LLM_API_KEY to enable live "
                "models; everything still works offline.",
                tone="amber",
            )
        stack = _arena_stack(settings, use_llm, use_llm_decisions)
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
        run_disabled = preview.contracts == 0
        if st.button(
            "▶ Run AI showdown",
            type="primary",
            use_container_width=True,
            disabled=run_disabled,
            key="arena_run",
        ):
            with st.spinner("Four desks are trading. AlphaVanguard is writing the review..."):
                try:
                    result = run_arena(
                        md,
                        scenario,
                        user_config,
                        settings=settings,
                        use_llm=use_llm,
                        use_llm_decisions=use_llm_decisions,
                    )
                except ArenaError as exc:
                    st.warning(str(exc))
                except Exception as exc:
                    LOGGER.exception("AI Arena failed")
                    st.error(
                        "The AI Arena could not complete this cycle. Try another scenario or capital "
                        "allocation; the cached data is safe."
                    )
                    with st.expander("Diagnostics"):
                        st.code(f"{type(exc).__name__}: {exc}")
                else:
                    st.session_state.arena_result = result
                    st.rerun()
        if st.session_state.get("arena_result") is not None:
            st.button(
                "Clear AI results",
                key="arena_clear_setup",
                on_click=_set_state,
                args=("arena_result", None),
                use_container_width=True,
            )
        st.caption(
            "The user desk and all three agents start with the same capital and the same "
            "historical window. Agent context is computed strictly before the first bar."
        )

    with right:
        theme.status_bar(
            [
                ("Asset", f"{asset.symbol} · {asset.asset_class}"),
                ("Scenario", scenario.get("label", "—")),
                ("Capital", _money(user_config.capital, asset)),
                ("AI mode", "LLM" if settings.enabled and use_llm else "Local core"),
                ("Decision", "LLM" if settings.enabled and use_llm and use_llm_decisions else "Policy"),
            ],
            live="AI DESK READY",
        )
        theme.section_header(
            "Rival roster",
            "Three autonomous mandates",
            "Each desk sees the same pre-simulation regime and chooses independently.",
        )
        theme.agent_cards(_arena_desk_cards(settings, use_llm, use_llm_decisions))
        theme.section_header("Model stack", "Name tags for the machines")
        theme.model_stack(stack)
        with st.expander("Recommended models for each role", expanded=False):
            theme.model_stack([], MODEL_RECOMMENDATIONS)
            st.caption(
                "The app always displays the active model names. Without an API key, the "
                "deterministic local models are used and every output remains reproducible."
            )
        theme.note(
            "The LLM is optional. The autonomous desks, the three-section critic report, and "
            "the NewsWire all have deterministic local implementations, so the sandbox works "
            "offline and never exposes technical errors when an API is unavailable.",
        )
        if st.session_state.get("arena_result") is not None:
            last = st.session_state.arena_result
            if isinstance(last, ArenaResult):
                st.success(
                    f"Last cycle: {last.winner.name} won · your rank #{last.user_rank}/4 · "
                    f"critic {last.report.model}."
                )

    result = st.session_state.get("arena_result")
    if isinstance(result, ArenaResult):
        _render_arena_result(result)


# ---------------------------------------------------------------------------
# Page 4 - Data Vault
# ---------------------------------------------------------------------------


def _coverage_display(coverage: pd.DataFrame) -> pd.DataFrame:
    if coverage.empty:
        return coverage
    display = coverage.copy()
    display["Source"] = display["Source"].map(lambda value: SOURCE_LABELS.get(value, value))
    display["Status"] = display["Status"].map(lambda value: str(value))
    display["HV 30d"] = pd.to_numeric(display["HV 30d"], errors="coerce") * 100.0
    display["Last"] = pd.to_numeric(display["Last"], errors="coerce")
    columns = ["Symbol", "Name", "Class", "Region", "Currency", "Source", "Rows", "Start", "End", "Last", "HV 30d", "Status"]
    return display[columns]


def render_data_vault() -> None:
    theme.hero(
        "Data vault · module 01",
        "Real history. Local first.",
        "Five years of daily OHLCV data for every SRS instrument, cached as Parquet. "
        "A bundled seed keeps the demo alive when the network is not.",
        chips=[
            ("yfinance source", "cyan"),
            ("Parquet cache", "green"),
            ("Offline seed", "amber"),
        ],
    )
    revision = _revision()
    try:
        coverage = load_coverage_cached(revision)
        stats = load_stats_cached(revision)
    except Exception:
        LOGGER.exception("Data coverage failed")
        st.error("The local market-data cache could not be read. Check the data directory permissions.")
        return

    ready = int((coverage["Rows"] > 0).sum()) if not coverage.empty else 0
    synthetic = int((coverage["Source"] == "synthetic").sum()) if not coverage.empty else 0
    latest = stats.get("latest") or "—"
    theme.kpi_grid(
        [
            theme.kpi_card("Instruments", f"{ready}/{len(ASSETS)}", "SRS universe", "green"),
            theme.kpi_card("Cached rows", f"{int(stats.get('rows', 0)):,}", "Daily bars", "cyan"),
            theme.kpi_card("Latest bar", str(latest), "Across the universe", "amber"),
            theme.kpi_card("Offline fallbacks", f"{synthetic}", "Synthetic assets", "pink" if synthetic else "muted"),
            theme.kpi_card(
                "Seed files",
                f"{len(list(get_service().seed_dir.glob('*.parquet')))}",
                "Bundled with the repo",
                "green",
            ),
            theme.kpi_card(
                "Runtime files",
                f"{len(list(get_service().cache_dir.glob('*.parquet')))}",
                "Downloaded locally",
                "cyan",
            ),
        ]
    )

    if synthetic:
        st.warning(
            "Some instruments are using deterministic synthetic fallback data. "
            "Refresh them here to replace the fallback with real Yahoo Finance history."
        )

    theme.section_header("Refresh", "Update the local cache", "Network access is optional. Existing files are never deleted on failure.")
    refresh_cols = st.columns([2.2, 1, 1])
    with refresh_cols[0]:
        selected = st.multiselect(
            "Symbols to refresh",
            ASSET_SYMBOLS,
            default=["AAPL"],
            format_func=_asset_format,
            key="dv_symbols",
        )
    if refresh_cols[1].button("Refresh selected", key="dv_refresh_selected", use_container_width=True):
        if not selected:
            st.warning("Select at least one symbol first.")
        else:
            with st.spinner("Contacting Yahoo Finance..."):
                report = get_service().refresh(selected, years=5, retries=3)
            _finish_refresh(report)
    if refresh_cols[2].button("Refresh all (5Y)", key="dv_refresh_all", type="primary", use_container_width=True):
        with st.spinner("Downloading five years for the full universe. This can take a minute..."):
            report = get_service().refresh(list(ASSET_SYMBOLS), years=5, retries=3)
        _finish_refresh(report)

    last_refresh = st.session_state.get("last_refresh")
    if last_refresh:
        with st.expander("Last refresh report", expanded=False):
            rows = [
                {
                    "Symbol": item["symbol"],
                    "Result": "OK" if item["ok"] else "FAILED",
                    "Detail": item["message"],
                    "Rows": item.get("rows", 0),
                }
                for item in last_refresh
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        if any(not item["ok"] for item in last_refresh):
            st.warning(
                "Some downloads failed. Cached and bundled seed files remain in use, so the "
                "simulator stays available offline."
            )

    theme.section_header("Inventory", "What is inside the vault", "The freshest local copy wins; seed files are the fallback.")
    display = _coverage_display(coverage)
    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Rows": st.column_config.NumberColumn("Rows", format="%d"),
            "Last": st.column_config.NumberColumn("Last", format="%.2f"),
            "HV 30d": st.column_config.NumberColumn("HV 30d", format="%.1f%%"),
            "Symbol": st.column_config.TextColumn("Symbol", width="small"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
        },
        height=520,
    )
    st.download_button(
        "⬇ Download inventory CSV",
        data=coverage.to_csv(index=False).encode("utf-8"),
        file_name="derivlab_data_inventory.csv",
        mime="text/csv",
        key="dv_download",
    )

    theme.section_header("Pipeline", "From raw prices to synthetic chains")
    cols = st.columns(4)
    pipeline = [
        ("01 · Fetch", "yfinance downloads five years of adjusted daily OHLCV for all 14 instruments."),
        ("02 · Cache", "Normalized Parquet files live in data/cache; data/seed ships with the repository."),
        ("03 · Measure", "Trailing 30-day historical volatility is computed from daily log returns."),
        ("04 · Price", "Black-Scholes turns spot, strike, time, rate, and IV into synthetic calls, puts, and Greeks."),
    ]
    for col, (title, body) in zip(cols, pipeline, strict=False):
        with col:
            theme.html_block(f"""
                <div class="dl-mini" style="min-height:118px;">
                    <div class="m-label">{title}</div>
                    <div class="m-value">{body}</div>
                </div>
                """)
    theme.note(
        "Yahoo Finance is a free data source and can rate-limit or fail. DerivLab treats that as a "
        "normal condition: it keeps the last good cache, falls back to the bundled seed, and only "
        "uses synthetic prices as a clearly labelled last resort.",
        tone="amber",
    )


def _finish_refresh(report: RefreshReport) -> None:
    st.session_state.last_refresh = [
        {
            "symbol": result.symbol,
            "ok": result.ok,
            "message": result.message,
            "rows": result.rows,
        }
        for result in report.results
    ]
    st.cache_data.clear()
    st.session_state.arena_result = None
    st.session_state.data_revision = _revision() + 1
    st.rerun()


# ---------------------------------------------------------------------------
# Page 5 - Field Guide
# ---------------------------------------------------------------------------


def _glossary_grid() -> None:
    items = [
        ("Delta (Δ)", "Spot exposure. A delta of 100 behaves like owning 100 shares; a short call has negative delta."),
        ("Gamma (Γ)", "How fast delta changes when spot moves. High gamma makes short-dated short options twitchy."),
        ("Theta (Θ)", "Time decay per calendar day. Long options pay it; short options collect it."),
        ("Vega (ν)", "Sensitivity to implied volatility. Long options are long vega; short options are short vega."),
        ("Historical volatility", "Backward-looking standard deviation of daily log returns, annualized over 30 days."),
        ("Implied volatility", "The volatility input that makes a Black-Scholes price match a market price. Here it is synthesized from HV."),
        ("Contango", "Futures trade above spot because of carry and expectations. The basis trade harvests convergence."),
        ("Assignment", "The short option is exercised. A put assignment buys shares at the strike; a call assignment sells them."),
        ("Roll", "Close an expiring option and open a new one with a different strike or expiry, usually to avoid assignment."),
        ("Max drawdown", "The deepest peak-to-trough decline in portfolio value."),
        ("Sharpe ratio", "Excess return divided by total volatility, annualized. Higher is better."),
        ("Sortino ratio", "Like Sharpe, but only downside volatility is penalised."),
    ]
    cards = "".join(
        f'<div class="dl-mini"><div class="m-label">{name}</div><div class="m-value">{body}</div></div>'
        for name, body in items
    )
    theme.html_block(f'<div class="dl-mini-grid">{cards}</div>')


def render_field_guide() -> None:
    theme.hero(
        "Field guide",
        "The vocabulary behind the terminal.",
        "A compact reference for the Greeks, the data pipeline, the scoring model, and the "
        "simplifications that make this educational engine fast and safe.",
        chips=[
            ("Greeks", "cyan"),
            ("Methodology", "green"),
            ("Limitations", "pink"),
        ],
    )
    theme.section_header("Reference", "Greeks and core terms")
    _glossary_grid()

    theme.section_header("Method", "How a simulation is assembled")
    theme.html_block("""
        <div class="dl-mini-grid">
            <div class="dl-mini">
                <div class="m-label">Data</div>
                <div class="m-value">Adjusted daily OHLCV from Yahoo Finance is cached locally. The simulator never
                fetches during the backtest loop, which keeps runs deterministic and fast.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Option chain</div>
                <div class="m-value">At each bar the engine computes 30-day HV, applies the IV multiplier, and prices
                calls and puts with Black-Scholes. Futures are priced with cost of carry plus an explicit basis.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Execution</div>
                <div class="m-value">Backtrader drives the daily event loop. A private ledger tracks cash, shares,
                synthetic options, and futures; transaction costs are charged per leg.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Settlement</div>
                <div class="m-value">Options settle at intrinsic value on the first trading day after expiry.
                Covered calls record assignment; cash-secured puts buy shares and stop writing puts.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Sizing</div>
                <div class="m-value">Capital allocation buys whole simulated lots. One lot is a simulation unit,
                not an exchange contract specification.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Currencies</div>
                <div class="m-value">All prices, capital, and P&L are in the instrument's quote currency. No FX
                conversion is applied across assets, which keeps each simulation internally consistent.</div>
            </div>
        </div>
        """)

    theme.section_header("Scoring", "How the Hold-the-Position badge works")
    theme.html_block("""
        <div class="dl-mini-grid">
            <div class="dl-mini">
                <div class="m-label">Directional P&L · ±38 points</div>
                <div class="m-value">A tanh curve rewards positive final return and penalises losses, with diminishing
                sensitivity beyond ±12%.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Drawdown control · 18 points</div>
                <div class="m-value">Full points at zero drawdown; the reward shrinks to zero at a 20% peak-to-trough decline.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Premium efficiency · 10 points</div>
                <div class="m-value">Rewards gross premium collected relative to allocated capital, saturating at 2%.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Behaviour badges</div>
                <div class="m-value">Yield Generator, Prudent Hedger, Liquidated Speculator, Volatility Architect,
                Basis Mechanic, Steady Operator, or Risk Apprentice.</div>
            </div>
        </div>
        """)

    theme.section_header("Honest limits", "What this simulator does not model")
    theme.html_block("""
        <div class="dl-mini-grid">
            <div class="dl-mini">
                <div class="m-label">Synthetic chains</div>
                <div class="m-value">Synthetic Black-Scholes prices are not executable quotes. There is no bid-ask spread,
                no real open interest, and no volatility surface across strikes.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Simplified frictions</div>
                <div class="m-value">Costs are a flat bps charge per leg. Margin calls, borrow costs, taxes, dividends
                timing, and early exercise of American options are simplified or omitted.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Flat smile</div>
                <div class="m-value">A single at-the-money IV is applied to every strike. Real puts often trade at a
                premium to calls, so real condor credits and CSP economics can differ.</div>
            </div>
            <div class="dl-mini">
                <div class="m-label">Educational intent</div>
                <div class="m-value">The app is a teaching and demonstration tool. It is not investment advice, a
                trading system, or a production risk engine.</div>
            </div>
        </div>
        """)
    theme.note(
        "Data source: Yahoo Finance via yfinance. The bundled seed is a point-in-time snapshot so the app "
        "remains demonstrable offline. Refresh from the Data Vault when the network is available."
    )


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title=f"{APP_NAME} · {APP_TITLE}",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    theme.inject_theme()
    theme.disable_browser_translation()
    _init_state()
    _render_sidebar()
    page = st.session_state.get("page", "strategy")
    try:
        if page == "strategy":
            render_strategy_deck()
        elif page == "backtest":
            render_backtest()
        elif page == "arena":
            render_arena()
        elif page == "game":
            render_game()
        elif page == "data":
            render_data_vault()
        elif page == "guide":
            render_field_guide()
        else:
            st.session_state.page = "strategy"
            st.rerun()
    except Exception as exc:
        LOGGER.exception("Unhandled UI error on page %s", page)
        st.error(
            "The terminal hit an unexpected condition. Your cached data is safe. "
            "Return to the Strategy Deck and try a different configuration."
        )
        if st.button("Return to Strategy Deck", key="fatal_home"):
            _goto("strategy")
            st.rerun()
        with st.expander("Diagnostics"):
            st.code(f"{type(exc).__name__}: {exc}")
    _render_footer()
