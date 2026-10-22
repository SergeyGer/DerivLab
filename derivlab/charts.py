"""Plotly figures styled for the dark financial-terminal interface."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .config import COLORS, FONT_MONO, FONT_SANS
from .game_mode import ScenarioGame
from .strategies import PositionPlan, payoff_curve


def _base_layout(fig: go.Figure, height: int = 420, margin: dict | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=margin or dict(l=58, r=22, t=44, b=44),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_SANS, color=COLORS["silver"], size=12),
        hoverlabel=dict(
            bgcolor="#0C0D10",
            bordercolor=COLORS["border"],
            font=dict(family=FONT_MONO, color=COLORS["text"], size=12),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11, color=COLORS["muted"]),
        ),
        hovermode="x unified",
    )
    fig.update_xaxes(
        automargin=True,
        gridcolor=COLORS["grid"],
        zerolinecolor=COLORS["border"],
        linecolor=COLORS["border"],
        tickfont=dict(family=FONT_MONO, size=10, color=COLORS["muted"]),
        title_font=dict(size=11, color=COLORS["muted"]),
    )
    fig.update_yaxes(
        automargin=True,
        gridcolor=COLORS["grid"],
        zerolinecolor=COLORS["border"],
        linecolor=COLORS["border"],
        tickfont=dict(family=FONT_MONO, size=10, color=COLORS["muted"]),
        title_font=dict(size=11, color=COLORS["muted"]),
    )
    return fig


def _money_hover(currency_symbol: str) -> str:
    return f"{currency_symbol}%{{y:,.2f}}"


def payoff_figure(plan: PositionPlan, height: int = 430) -> go.Figure:
    """Expiration P&L profile with breakevens and strike markers."""
    curve = payoff_curve(plan)
    fig = go.Figure()
    symbol = plan.asset.currency_symbol
    if curve.empty:
        _base_layout(fig, height)
        fig.add_annotation(
            text="No payoff available for this configuration.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color=COLORS["muted"], size=13),
        )
        return fig

    x = curve["price"]
    pnl = curve["pnl"]
    positive = np.clip(pnl, 0, None)
    negative = np.clip(pnl, None, 0)

    fig.add_trace(
        go.Scatter(
            x=x,
            y=positive,
            mode="lines",
            line=dict(color=COLORS["green"], width=2.4),
            fill="tozeroy",
            fillcolor="rgba(0, 230, 118, 0.12)",
            name="Profit zone",
            hovertemplate="Price " + symbol + "%{x:,.2f}<br>P&L " + _money_hover(symbol) + "<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=negative,
            mode="lines",
            line=dict(color=COLORS["pink"], width=2.4),
            fill="tozeroy",
            fillcolor="rgba(255, 23, 68, 0.12)",
            name="Loss zone",
            hovertemplate="Price " + symbol + "%{x:,.2f}<br>P&L " + _money_hover(symbol) + "<extra></extra>",
        )
    )

    if plan.strategy_key == "basis_trade":
        if curve["spot_leg"].abs().sum() > 0:
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=curve["spot_leg"],
                    mode="lines",
                    line=dict(color=COLORS["cyan"], width=1.2, dash="dot"),
                    name="Long spot leg",
                    hovertemplate="Spot leg " + _money_hover(symbol) + "<extra></extra>",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=curve["futures_leg"],
                    mode="lines",
                    line=dict(color=COLORS["magenta"], width=1.2, dash="dot"),
                    name="Short future leg",
                    hovertemplate="Future leg " + _money_hover(symbol) + "<extra></extra>",
                )
            )

    fig.add_hline(y=0, line=dict(color=COLORS["silver"], width=1))
    fig.add_vline(
        x=plan.spot,
        line=dict(color=COLORS["silver"], width=1, dash="dash"),
    )
    seen_strikes: set[float] = set()
    for leg in plan.legs:
        if leg.strike in seen_strikes:
            continue
        seen_strikes.add(leg.strike)
        fig.add_vline(
            x=leg.strike,
            line=dict(color=COLORS["amber"] if leg.qty < 0 else COLORS["green"], width=1, dash="dot"),
        )
    for be in plan.breakevens:
        fig.add_trace(
            go.Scatter(
                x=[be],
                y=[0],
                mode="markers+text",
                marker=dict(color=COLORS["amber"], size=8, symbol="diamond"),
                text=["BE"],
                textposition="bottom center",
                textfont=dict(color=COLORS["amber"], size=9),
                name="Break-even",
                hovertemplate="Break-even " + symbol + "%{x:,.2f}<extra></extra>",
                showlegend=False,
            )
        )

    if plan.contracts == 0:
        fig.add_annotation(
            text="Capital below one lot - no position is sized.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color=COLORS["pink"], size=13),
            bgcolor="rgba(18,18,18,0.8)",
        )

    price_tickformat = ",.3f" if plan.spot < 10 else (",.1f" if plan.spot < 100 else ",.0f")
    _base_layout(fig, height, margin=dict(l=58, r=22, t=34, b=82))
    fig.update_xaxes(
        title_text=f"Underlying price at expiration ({symbol})",
        tickformat=price_tickformat,
        title_standoff=20,
    )
    fig.update_yaxes(title_text=f"Profit / loss ({plan.asset.currency})", tickprefix=symbol, tickformat=",.0f")
    fig.update_layout(hovermode="x")
    return fig


def equity_figure(result, height: int = 470) -> go.Figure:
    """Strategy equity index versus buy-and-hold, plus the drawdown pane."""
    nav = result.nav
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.72, 0.28],
    )
    strategy_index = nav["nav"] / result.initial_capital * 100.0
    benchmark_index = result.benchmark / result.initial_capital * 100.0

    fig.add_trace(
        go.Scatter(
            x=nav.index,
            y=strategy_index,
            mode="lines",
            name=result.strategy_name,
            line=dict(color=COLORS["green"], width=2.2),
            fill="tozeroy",
            fillcolor="rgba(0, 230, 118, 0.06)",
            hovertemplate="%{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=nav.index,
            y=benchmark_index,
            mode="lines",
            name="Buy & hold",
            line=dict(color=COLORS["muted"], width=1.4, dash="dash"),
            hovertemplate="%{y:.1f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_hline(y=100, line=dict(color=COLORS["border"], width=1, dash="dot"), row=1, col=1)
    fig.add_trace(
        go.Scatter(
            x=nav.index,
            y=nav["drawdown"] * 100.0,
            mode="lines",
            name="Drawdown",
            line=dict(color=COLORS["pink"], width=1.4),
            fill="tozeroy",
            fillcolor="rgba(255, 23, 68, 0.12)",
            hovertemplate="%{y:.2f}%<extra></extra>",
        ),
        row=2,
        col=1,
    )
    final_strategy = float(strategy_index.iloc[-1]) - 100.0
    final_benchmark = float(benchmark_index.iloc[-1]) - 100.0
    fig.add_annotation(
        x=nav.index[-1],
        y=float(strategy_index.iloc[-1]),
        text=f" {final_strategy:+.1f}%",
        showarrow=False,
        xanchor="right",
        yanchor="bottom",
        font=dict(color=COLORS["green"], size=11, family=FONT_MONO),
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=nav.index[-1],
        y=float(benchmark_index.iloc[-1]),
        text=f" {final_benchmark:+.1f}%",
        showarrow=False,
        xanchor="right",
        yanchor="top",
        font=dict(color=COLORS["muted"], size=11, family=FONT_MONO),
        row=1,
        col=1,
    )
    _base_layout(fig, height)
    fig.update_yaxes(title_text="Index (100 = start)", row=1, col=1, tickformat=",.0f")
    fig.update_yaxes(title_text="Drawdown %", row=2, col=1, ticksuffix="%", tickformat=".1f")
    fig.update_xaxes(showgrid=False, row=2, col=1)
    fig.update_layout(hovermode="x unified")
    return fig


def cycle_pnl_figure(result, height: int = 300) -> go.Figure:
    fig = go.Figure()
    if result.cycles is None or result.cycles.empty:
        _base_layout(fig, height)
        fig.add_annotation(
            text="No completed cycles yet.",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color=COLORS["muted"], size=13),
        )
        return fig
    cycles = result.cycles
    colors = [COLORS["green"] if value >= 0 else COLORS["pink"] for value in cycles["pnl"]]
    fig.add_trace(
        go.Bar(
            x=cycles["end"],
            y=cycles["pnl"],
            marker_color=colors,
            marker_line_width=0,
            name="Cycle P&L",
            hovertemplate="Cycle %{customdata}<br>P&L %{y:,.2f}<extra></extra>",
            customdata=cycles["cycle"],
        )
    )
    cumulative = cycles["pnl"].cumsum()
    fig.add_trace(
        go.Scatter(
            x=cycles["end"],
            y=cumulative,
            mode="lines+markers",
            name="Cumulative",
            line=dict(color=COLORS["silver"], width=1.4),
            marker=dict(size=4),
            hovertemplate="Cumulative %{y:,.2f}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line=dict(color=COLORS["border"], width=1))
    _base_layout(fig, height)
    fig.update_yaxes(title_text="Cycle P&L", tickprefix=result.asset.currency_symbol, tickformat=",.0f")
    return fig


def volatility_figure(result, height: int = 310) -> go.Figure:
    nav = result.nav
    fig = go.Figure()
    if "iv" not in nav or nav.empty:
        _base_layout(fig, height)
        return fig
    fig.add_trace(
        go.Scatter(
            x=nav.index,
            y=nav["iv"] * 100.0,
            mode="lines",
            name="Synthetic IV (annualized)",
            line=dict(color=COLORS["magenta"], width=1.8),
            fill="tozeroy",
            fillcolor="rgba(224, 64, 251, 0.07)",
            hovertemplate="IV %{y:.1f}%<extra></extra>",
        )
    )
    _base_layout(fig, height)
    fig.update_yaxes(title_text="Implied volatility %", ticksuffix="%", tickformat=".0f")
    fig.update_layout(hovermode="x")
    return fig


def price_path_figure(game: ScenarioGame, height: int = 500) -> go.Figure:
    """Live scenario path with strikes, alerts, and equity in one terminal view."""
    frame = game.path_frame()
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=[0.66, 0.34],
    )
    if frame.empty:
        _base_layout(fig, height)
        return fig
    symbol = game.asset.currency_symbol
    span = max(game.frame["Close"].max() - game.frame["Close"].min(), 1e-9)
    lower = float(game.frame["Close"].min()) - span * 0.06
    upper = float(game.frame["Close"].max()) + span * 0.06

    spot_marker_size = 3 if len(frame) > 45 else 6
    fig.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["spot"],
            mode="lines+markers",
            name="Spot",
            line=dict(color=COLORS["text"], width=1.9),
            marker=dict(size=spot_marker_size, color=COLORS["text"]),
            hovertemplate="%{y:,.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    if game.entry_spot > 0:
        fig.add_hline(
            y=game.entry_spot,
            line=dict(color=COLORS["muted"], width=1, dash="dot"),
            annotation_text="Entry",
            annotation_position="top left",
            annotation_font=dict(color=COLORS["muted"], size=9),
            row=1,
            col=1,
        )
    current_plan = game.current_plan or game.entry_plan
    if current_plan is not None:
        seen: set[tuple[str, float]] = set()
        for leg in current_plan.legs:
            key = (leg.kind, round(leg.strike, 4))
            if key in seen:
                continue
            seen.add(key)
            color = COLORS["pink"] if leg.qty < 0 else COLORS["green"]
            fig.add_hline(
                y=leg.strike,
                line=dict(color=color, width=1, dash="dot"),
                annotation_text=f"{'Short' if leg.qty < 0 else 'Long'} {leg.kind[0].upper()} {leg.strike:,.2f}",
                annotation_position="right",
                annotation_font=dict(color=color, size=9),
                row=1,
                col=1,
            )
        if game.strategy_key == "iron_condor" and len(current_plan.legs) >= 4:
            short_put = current_plan.legs[0].strike
            short_call = current_plan.legs[2].strike
            fig.add_vrect(
                x0=frame.index[0],
                x1=frame.index[-1],
                y0=short_put,
                y1=short_call,
                fillcolor="rgba(0, 230, 118, 0.04)",
                line_width=0,
                layer="below",
                row=1,
                col=1,
            )
    fig.add_trace(
        go.Scatter(
            x=[frame.index[-1]],
            y=[frame["spot"].iloc[-1]],
            mode="markers",
            name="Now",
            marker=dict(color=COLORS["green"], size=9, line=dict(color=COLORS["bg"], width=2)),
            hovertemplate="Spot " + symbol + "%{y:,.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    events = game.event_frame()
    alert_events = events[events["kind"].isin(["alert", "assignment", "finish"])] if not events.empty else events
    alert_x: list = []
    alert_y: list[float] = []
    alert_text: list[str] = []
    if not alert_events.empty:
        for _, event in alert_events.iterrows():
            event_date = event["date"]
            try:
                alert_y.append(float(game.frame.loc[event_date, "Close"]))
            except KeyError:
                alert_y.append(float(game.frame["Close"].iloc[-1]))
            alert_x.append(event_date)
            alert_text.append(str(event["title"]))
    # Always emit the trace, even when empty, so the Plotly figure has a stable
    # number of traces across ticks and alerts.
    fig.add_trace(
        go.Scatter(
            x=alert_x,
            y=alert_y,
            mode="markers",
            name="Events",
            marker=dict(color=COLORS["pink"], size=8, symbol="diamond"),
            text=alert_text,
            hovertemplate="%{text}<br>%{x|%Y-%m-%d}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=frame.index,
            y=frame["equity_index"],
            mode="lines+markers",
            name="NAV index",
            line=dict(color=COLORS["green"], width=1.8),
            marker=dict(size=3 if len(frame) > 45 else 5, color=COLORS["green"]),
            fill="tozeroy",
            fillcolor="rgba(0, 230, 118, 0.06)",
            hovertemplate="%{y:.1f}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=100, line=dict(color=COLORS["border"], width=1, dash="dot"), row=2, col=1)
    _base_layout(fig, height)
    fig.update_xaxes(type="date", tickformat="%b %d", automargin=True)
    if len(frame) < 3:
        span_start = frame.index[0]
        fig.update_xaxes(range=[span_start, span_start + pd.Timedelta(days=21)])
    fig.update_yaxes(title_text=f"Price ({symbol})", range=[lower, upper], row=1, col=1, tickformat=",.2f")
    fig.update_yaxes(title_text="NAV index", row=2, col=1, tickformat=",.0f")
    fig.update_layout(hovermode="x unified")
    return fig


def score_bar_figure(score: int, height: int = 190) -> go.Figure:
    color = COLORS["green"] if score >= 70 else (COLORS["amber"] if score >= 45 else COLORS["pink"])
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=float(score),
            number=dict(suffix="/100", font=dict(color=COLORS["text"], family=FONT_MONO, size=30)),
            gauge=dict(
                axis=dict(range=[0, 100], tickwidth=0, tickcolor=COLORS["muted"], tickfont=dict(size=9)),
                bar=dict(color=color, thickness=0.32),
                bgcolor="rgba(0,0,0,0)",
                borderwidth=0,
                steps=[
                    dict(range=[0, 45], color="rgba(255, 23, 68, 0.10)"),
                    dict(range=[45, 70], color="rgba(255, 209, 102, 0.10)"),
                    dict(range=[70, 100], color="rgba(0, 230, 118, 0.10)"),
                ],
            ),
        )
    )
    fig.update_layout(
        height=height,
        margin=dict(l=18, r=18, t=12, b=6),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_SANS, color=COLORS["muted"]),
    )
    return fig


def empty_figure(message: str = "Run a simulation to populate this chart.", height: int = 300) -> go.Figure:
    fig = go.Figure()
    _base_layout(fig, height)
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(color=COLORS["muted"], size=13),
    )
    return fig
