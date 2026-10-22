"""Dark "financial cyberpunk" theme and reusable HTML components."""

from __future__ import annotations

import html
import textwrap
from collections.abc import Iterable

import streamlit as st

from .config import COLORS, FONT_MONO, FONT_SANS
from .metrics import ScoreCard

CSS = f"""
<style>
:root {{
    --dl-bg: {COLORS['bg']};
    --dl-panel: {COLORS['panel']};
    --dl-panel-alt: {COLORS['panel_alt']};
    --dl-border: {COLORS['border']};
    --dl-text: {COLORS['text']};
    --dl-silver: {COLORS['silver']};
    --dl-muted: {COLORS['muted']};
    --dl-green: {COLORS['green']};
    --dl-pink: {COLORS['pink']};
    --dl-magenta: {COLORS['magenta']};
    --dl-cyan: {COLORS['cyan']};
    --dl-amber: {COLORS['amber']};
    --dl-mono: {FONT_MONO};
}}
html, body, [data-testid="stAppViewContainer"] {{
    background:
        radial-gradient(1100px 500px at 12% -10%, rgba(0, 230, 118, 0.055), transparent 60%),
        radial-gradient(900px 480px at 92% 0%, rgba(224, 64, 251, 0.045), transparent 60%),
        var(--dl-bg);
    color: var(--dl-text);
    font-family: {FONT_SANS};
}}
[data-testid="stAppViewContainer"] > .main {{
    background: transparent;
}}
.block-container {{
    padding-top: 1.1rem;
    padding-bottom: 3rem;
    max-width: 1480px;
}}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] {{
    display: none !important;
}}
header[data-testid="stHeader"] {{
    background: transparent;
}}
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #131418 0%, #0D0E12 100%);
    border-right: 1px solid var(--dl-border);
}}
[data-testid="stSidebar"] > div:first-child {{
    padding-top: 1.2rem;
}}
[data-testid="stSidebar"] .block-container {{
    padding-top: 0.4rem;
}}
h1, h2, h3, h4 {{
    font-family: {FONT_SANS};
    letter-spacing: -0.02em;
    color: var(--dl-text);
}}
p, li, label, span {{
    color: var(--dl-silver, #C3C8D2);
}}
a {{
    color: var(--dl-green) !important;
    text-decoration: none;
}}
a:hover {{ text-decoration: underline; }}
code, .mono, [data-testid="stMetricValue"] {{
    font-family: var(--dl-mono);
}}
hr {{ border-color: var(--dl-border); }}

/* ---------- widgets ---------- */
.stButton > button, .stDownloadButton > button, .stLinkButton > a {{
    background: #191B21;
    color: var(--dl-text);
    border: 1px solid #303540;
    border-radius: 9px;
    font-weight: 600;
    letter-spacing: 0.01em;
    padding: 0.48rem 1rem;
    transition: border-color 120ms ease, color 120ms ease, transform 120ms ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {{
    border-color: var(--dl-green);
    color: var(--dl-green);
    transform: translateY(-1px);
}}
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primary"] {{
    background: linear-gradient(135deg, #00E676 0%, #00C9A7 100%);
    color: #04140C !important;
    border: 1px solid rgba(0, 230, 118, 0.75);
    box-shadow: 0 0 22px rgba(0, 230, 118, 0.18);
}}
.stButton > button[kind="primary"] p, [data-testid="stBaseButton-primary"] p {{
    color: #04140C !important;
    font-weight: 750;
}}
.stButton > button:disabled, .stButton > button:disabled:hover {{
    opacity: 0.35 !important;
    color: #8B93A7 !important;
    border-color: #2A2D34 !important;
    background: #17191F !important;
    box-shadow: none !important;
    transform: none;
}}
.stButton > button:disabled p {{ color: #8B93A7 !important; }}
.stButton > button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover {{
    color: #04140C;
    box-shadow: 0 0 30px rgba(0, 230, 118, 0.30);
}}
.stButton > button:disabled {{
    opacity: 0.4;
    transform: none;
}}
div[data-testid="stSelectbox"] label,
div[data-testid="stNumberInput"] label,
div[data-testid="stSlider"] label,
div[data-testid="stRadio"] > label,
div[data-testid="stCheckbox"] label {{
    color: var(--dl-muted);
    font-size: 0.76rem;
    font-weight: 600;
    letter-spacing: 0.09em;
    text-transform: uppercase;
}}
div[data-baseweb="select"] > div,
div[data-testid="stNumberInput"] input,
div[data-testid="stTextInput"] input {{
    background: #17191F;
    border-color: #303540;
    color: var(--dl-text);
    border-radius: 8px;
}}
div[data-baseweb="select"] > div:hover {{
    border-color: #46505F;
}}
[data-baseweb="popover"] ul {{
    background: #17191F;
}}
[data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"] {{
    background: var(--dl-green);
    box-shadow: 0 0 12px rgba(0, 230, 118, 0.45);
}}
[data-testid="stSlider"] [data-baseweb="slider"] > div > div {{
    background: var(--dl-green);
}}
[data-testid="stExpander"] {{
    background: rgba(30, 30, 30, 0.55);
    border: 1px solid var(--dl-border);
    border-radius: 10px;
}}
[data-testid="stExpander"] summary {{
    color: var(--dl-silver, #C3C8D2);
    font-size: 0.86rem;
}}
[data-testid="stTabs"] button {{
    color: var(--dl-muted);
    font-weight: 600;
    font-size: 0.82rem;
    letter-spacing: 0.03em;
}}
[data-testid="stTabs"] button[aria-selected="true"] {{
    color: var(--dl-green);
}}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{
    background-color: var(--dl-green);
}}
[data-testid="stTabs"] [data-baseweb="tab-border"] {{
    background-color: var(--dl-border);
}}
div[data-testid="stAlert"] {{
    background: #17191F;
    color: var(--dl-text);
    border: 1px solid var(--dl-border);
    border-radius: 10px;
}}
div[data-testid="stAlert"] p {{ color: var(--dl-text); }}
[data-testid="stDataFrame"] {{
    border: 1px solid var(--dl-border);
    border-radius: 10px;
    overflow: hidden;
}}
[data-testid="stProgress"] > div > div > div > div {{
    background: linear-gradient(90deg, var(--dl-green), var(--dl-cyan));
}}
[data-testid="stPlotlyChart"] {{
    border: 1px solid var(--dl-border);
    border-radius: 14px;
    background: rgba(24, 25, 29, 0.55);
    padding: 6px 6px 0 6px;
}}
[data-testid="stMetric"] {{
    background: var(--dl-panel);
    border: 1px solid var(--dl-border);
    border-radius: 10px;
    padding: 12px;
}}
[data-testid="stToast"] {{
    background: #17191F;
    border: 1px solid var(--dl-green);
    color: var(--dl-text);
}}

/* ---------- strategy navigator ---------- */
div[data-testid="stRadio"] > div[role="radiogroup"] {{
    gap: 10px;
}}
div[data-testid="stRadio"] label[data-baseweb="radio"] {{
    background: linear-gradient(150deg, #1B1D22 0%, #141519 100%);
    border: 1px solid #2A2D34;
    border-radius: 11px;
    padding: 13px 15px;
    width: 100%;
    transition: border-color 140ms ease, box-shadow 140ms ease, transform 140ms ease;
}}
div[data-testid="stRadio"] label[data-baseweb="radio"]:hover {{
    border-color: #46505F;
    transform: translateX(2px);
}}
div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {{
    border-color: rgba(0, 230, 118, 0.7);
    box-shadow: inset 3px 0 0 var(--dl-green), 0 0 22px rgba(0, 230, 118, 0.08);
    background: linear-gradient(150deg, rgba(0, 230, 118, 0.09) 0%, #141519 65%);
}}
div[data-testid="stRadio"] label[data-baseweb="radio"] > div:first-child {{
    display: none;
}}
div[data-testid="stRadio"] label[data-baseweb="radio"] div[data-testid="stMarkdownContainer"] p {{
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--dl-text);
    margin: 0;
}}

/* ---------- semantic blocks ---------- */
.dl-hero {{
    position: relative;
    overflow: hidden;
    border: 1px solid var(--dl-border);
    border-radius: 18px;
    padding: 26px 30px 24px 30px;
    margin-bottom: 20px;
    background:
        radial-gradient(700px 240px at 8% 0%, rgba(0, 230, 118, 0.10), transparent 65%),
        radial-gradient(520px 260px at 95% 15%, rgba(224, 64, 251, 0.08), transparent 65%),
        linear-gradient(155deg, #17191F 0%, #101116 75%);
}}
.dl-hero::after {{
    content: "";
    position: absolute;
    inset: 0;
    background-image:
        linear-gradient(rgba(255,255,255,0.024) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.024) 1px, transparent 1px);
    background-size: 34px 34px;
    mask-image: linear-gradient(110deg, rgba(0,0,0,0.9), transparent 72%);
    pointer-events: none;
}}
.dl-hero > * {{ position: relative; z-index: 1; }}
.dl-eyebrow {{
    font-family: var(--dl-mono);
    font-size: 0.68rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--dl-green);
    margin-bottom: 8px;
}}
.dl-hero h1 {{
    font-size: clamp(1.65rem, 2.4vw, 2.35rem);
    line-height: 1.08;
    margin: 0 0 8px 0;
    font-weight: 750;
}}
.dl-hero .dl-sub {{
    color: var(--dl-muted);
    font-size: 0.96rem;
    line-height: 1.5;
    max-width: 860px;
    margin: 0;
}}
.dl-chips {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 16px;
}}
.dl-chip {{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-family: var(--dl-mono);
    font-size: 0.68rem;
    letter-spacing: 0.05em;
    color: var(--dl-silver, #C3C8D2);
    border: 1px solid var(--dl-border);
    background: rgba(12, 13, 16, 0.55);
    border-radius: 999px;
    padding: 5px 11px;
    text-transform: uppercase;
}}
.dl-chip .dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--dl-green);
    box-shadow: 0 0 8px var(--dl-green);
}}
.dl-chip.green {{ border-color: rgba(0,230,118,.35); color: var(--dl-green); }}
.dl-chip.pink {{ border-color: rgba(255,23,68,.35); color: var(--dl-pink); }}
.dl-chip.amber {{ border-color: rgba(255,209,102,.35); color: var(--dl-amber); }}
.dl-chip.cyan {{ border-color: rgba(0,229,255,.35); color: var(--dl-cyan); }}
.dl-chip.muted {{ color: var(--dl-muted); }}

.dl-kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(142px, 1fr));
    gap: 12px;
    margin: 6px 0 16px 0;
}}
.dl-kpi {{
    position: relative;
    overflow: hidden;
    background: linear-gradient(160deg, #1E1E1E 0%, #15161A 100%);
    border: 1px solid var(--dl-border);
    border-radius: 12px;
    padding: 15px 17px 13px 17px;
    min-height: 92px;
}}
.dl-kpi::before {{
    content: "";
    position: absolute;
    left: 0; top: 0;
    width: 100%; height: 2px;
    background: linear-gradient(90deg, var(--tone, var(--dl-green)), transparent 85%);
}}
.dl-kpi .k-label {{
    font-family: var(--dl-mono);
    font-size: 0.62rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--dl-muted);
    margin-bottom: 8px;
}}
.dl-kpi .k-value {{
    font-family: var(--dl-mono);
    font-size: clamp(1.1rem, 1.6vw, 1.48rem);
    font-weight: 600;
    color: var(--dl-text);
    line-height: 1.15;
    letter-spacing: -0.02em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.dl-kpi .k-sub {{
    color: var(--dl-muted);
    font-size: 0.72rem;
    margin-top: 6px;
    line-height: 1.3;
}}
.dl-kpi.tone-green {{ --tone: var(--dl-green); }}
.dl-kpi.tone-pink {{ --tone: var(--dl-pink); }}
.dl-kpi.tone-amber {{ --tone: var(--dl-amber); }}
.dl-kpi.tone-cyan {{ --tone: var(--dl-cyan); }}
.dl-kpi.tone-magenta {{ --tone: var(--dl-magenta); }}
.dl-kpi.tone-muted {{ --tone: var(--dl-muted); }}
.dl-kpi .value-green {{ color: var(--dl-green); }}
.dl-kpi .value-pink {{ color: var(--dl-pink); }}
.dl-kpi .value-amber {{ color: var(--dl-amber); }}
.dl-kpi .value-cyan {{ color: var(--dl-cyan); }}

.dl-section {{
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    margin: 22px 0 10px 0;
}}
.dl-section .eyebrow {{
    font-family: var(--dl-mono);
    font-size: 0.64rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--dl-green);
    margin-bottom: 4px;
}}
.dl-section h3 {{
    margin: 0;
    font-size: 1.08rem;
    font-weight: 700;
}}
.dl-section .sub {{
    color: var(--dl-muted);
    font-size: 0.8rem;
    margin-top: 3px;
}}

.dl-edu {{
    position: relative;
    background:
        radial-gradient(420px 220px at 100% 0%, rgba(0, 230, 118, 0.06), transparent 65%),
        linear-gradient(155deg, #1E1E1E 0%, #141519 100%);
    border: 1px solid var(--dl-border);
    border-radius: 16px;
    padding: 26px 28px 24px 28px;
    min-height: 100%;
}}
.dl-edu::before {{
    content: "";
    position: absolute;
    top: 0; left: 22px; right: 22px;
    height: 2px;
    background: linear-gradient(90deg, var(--dl-green), var(--dl-cyan), transparent);
    border-radius: 2px;
}}
.dl-edu .edu-topline {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
}}
.dl-edu h2 {{
    font-size: clamp(1.35rem, 2vw, 1.7rem);
    margin: 0 0 6px 0;
}}
.dl-edu .tagline {{
    color: var(--dl-silver, #C3C8D2);
    font-size: 0.98rem;
    line-height: 1.55;
    margin: 0 0 18px 0;
}}
.dl-edu .edu-block {{
    margin-top: 18px;
    padding-top: 16px;
    border-top: 1px solid rgba(255,255,255,0.06);
}}
.dl-edu .edu-label {{
    font-family: var(--dl-mono);
    font-size: 0.62rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--dl-muted);
    margin-bottom: 8px;
}}
.dl-edu .concept {{
    color: #D8DCE4;
    font-size: 0.91rem;
    line-height: 1.65;
}}
.dl-steps {{
    list-style: none;
    padding: 0;
    margin: 0;
    counter-reset: step;
}}
.dl-steps li {{
    position: relative;
    padding-left: 36px;
    margin: 10px 0;
    color: #D8DCE4;
    font-size: 0.88rem;
    line-height: 1.5;
}}
.dl-steps li::before {{
    counter-increment: step;
    content: counter(step);
    position: absolute;
    left: 0;
    top: 0;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--dl-mono);
    font-size: 0.66rem;
    color: var(--dl-green);
    background: rgba(0, 230, 118, 0.10);
    border: 1px solid rgba(0, 230, 118, 0.35);
}}
.dl-risk {{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-family: var(--dl-mono);
    font-size: 0.7rem;
    letter-spacing: 0.04em;
    padding: 7px 12px;
    border-radius: 999px;
    border: 1px solid var(--dl-border);
    color: var(--dl-silver, #C3C8D2);
}}
.dl-risk.green {{ color: var(--dl-green); border-color: rgba(0,230,118,.35); background: rgba(0,230,118,.07); }}
.dl-risk.amber {{ color: var(--dl-amber); border-color: rgba(255,209,102,.35); background: rgba(255,209,102,.07); }}
.dl-risk.pink {{ color: var(--dl-pink); border-color: rgba(255,23,68,.35); background: rgba(255,23,68,.07); }}
.dl-mini-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-top: 10px;
}}
.dl-mini {{
    background: rgba(12, 13, 16, 0.55);
    border: 1px solid var(--dl-border);
    border-radius: 10px;
    padding: 12px 14px;
}}
.dl-mini .m-label {{
    font-family: var(--dl-mono);
    font-size: 0.6rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--dl-muted);
    margin-bottom: 5px;
}}
.dl-mini .m-value {{
    color: var(--dl-text);
    font-size: 0.84rem;
    line-height: 1.45;
}}

.dl-note {{
    border-left: 2px solid var(--dl-cyan);
    background: rgba(0, 229, 255, 0.045);
    border-radius: 0 8px 8px 0;
    padding: 11px 14px;
    color: var(--dl-muted);
    font-size: 0.8rem;
    line-height: 1.55;
}}
.dl-note.pink {{ border-left-color: var(--dl-pink); background: rgba(255, 23, 68, 0.05); }}
.dl-note.amber {{ border-left-color: var(--dl-amber); background: rgba(255, 209, 102, 0.05); }}
.dl-note strong {{ color: var(--dl-text); }}

.dl-status {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
    border: 1px solid var(--dl-border);
    border-radius: 12px;
    padding: 13px 16px;
    background: linear-gradient(160deg, #1B1D22, #131418);
    margin: 10px 0 14px 0;
}}
.dl-live {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-family: var(--dl-mono);
    font-size: 0.68rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--dl-green);
}}
.dl-live .pulse {{
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--dl-green);
    box-shadow: 0 0 0 0 rgba(0, 230, 118, 0.5);
    animation: dlpulse 1.8s infinite;
}}
@keyframes dlpulse {{
    0% {{ box-shadow: 0 0 0 0 rgba(0, 230, 118, 0.45); }}
    70% {{ box-shadow: 0 0 0 9px rgba(0, 230, 118, 0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(0, 230, 118, 0); }}
}}
.dl-status .item {{
    font-family: var(--dl-mono);
    font-size: 0.72rem;
    color: var(--dl-muted);
}}
.dl-status .item b {{ color: var(--dl-text); font-weight: 600; }}

.dl-alert {{
    border: 1px solid rgba(255, 23, 68, 0.5);
    background:
        radial-gradient(600px 160px at 0% 0%, rgba(255, 23, 68, 0.13), transparent 70%),
        linear-gradient(160deg, #20151A, #151116);
    border-radius: 14px;
    padding: 20px 22px;
    margin: 12px 0;
    animation: dlalertin 250ms ease-out;
}}
@keyframes dlalertin {{
    from {{ opacity: 0; transform: translateY(-4px); }}
    to {{ opacity: 1; transform: translateY(0); }}
}}
.dl-alert .a-head {{
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: var(--dl-mono);
    font-size: 0.68rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--dl-pink);
    margin-bottom: 8px;
}}
.dl-alert h3 {{
    margin: 0 0 8px 0;
    font-size: 1.18rem;
    color: var(--dl-text);
}}
.dl-alert p {{
    margin: 0;
    color: #E3C8CF;
    font-size: 0.89rem;
    line-height: 1.55;
}}
.dl-alert .a-metrics {{
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    margin-top: 14px;
    font-family: var(--dl-mono);
    font-size: 0.72rem;
    color: var(--dl-muted);
}}
.dl-alert .a-metrics b {{ color: var(--dl-text); }}

.dl-decision {{
    border: 1px solid var(--dl-border);
    border-radius: 14px;
    background: linear-gradient(160deg, #1B1D22, #131418);
    padding: 18px 20px;
    margin-bottom: 14px;
}}
.dl-decision h3 {{
    margin: 0 0 4px 0;
    font-size: 1rem;
}}
.dl-decision p {{
    color: var(--dl-muted);
    font-size: 0.8rem;
    margin: 0 0 12px 0;
}}

.dl-badge {{
    display: flex;
    align-items: center;
    gap: 18px;
    border: 1px solid rgba(0, 230, 118, 0.32);
    border-radius: 16px;
    padding: 20px 22px;
    background:
        radial-gradient(420px 180px at 0% 0%, rgba(0, 230, 118, 0.10), transparent 70%),
        linear-gradient(155deg, #1B211C, #141519);
    margin: 10px 0 16px 0;
}}
.dl-badge .medal {{
    font-size: 2.2rem;
    line-height: 1;
    filter: drop-shadow(0 0 14px rgba(0, 230, 118, 0.35));
}}
.dl-badge .b-label {{
    font-family: var(--dl-mono);
    font-size: 0.62rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: var(--dl-muted);
}}
.dl-badge .b-title {{
    font-size: 1.35rem;
    font-weight: 750;
    color: var(--dl-green);
    margin: 2px 0 4px 0;
}}
.dl-badge.mid {{
    border-color: rgba(255, 209, 102, 0.32);
    background:
        radial-gradient(420px 180px at 0% 0%, rgba(255, 209, 102, 0.10), transparent 70%),
        linear-gradient(155deg, #211E1B, #141519);
}}
.dl-badge.mid .b-title {{ color: var(--dl-amber); }}
.dl-badge.low {{
    border-color: rgba(255, 23, 68, 0.34);
    background:
        radial-gradient(420px 180px at 0% 0%, rgba(255, 23, 68, 0.10), transparent 70%),
        linear-gradient(155deg, #21171B, #141519);
}}
.dl-badge.low .b-title {{ color: var(--dl-pink); }}
.dl-badge .b-tag {{ color: var(--dl-silver, #C3C8D2); font-size: 0.84rem; }}

.dl-footer {{
    border-top: 1px solid var(--dl-border);
    margin-top: 34px;
    padding-top: 14px;
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 10px;
    color: var(--dl-muted);
    font-family: var(--dl-mono);
    font-size: 0.66rem;
    letter-spacing: 0.04em;
}}

.dl-kv {{
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 1px dashed rgba(255,255,255,0.06);
    font-size: 0.8rem;
}}
.dl-kv:last-child {{ border-bottom: none; }}
.dl-kv .k {{ color: var(--dl-muted); }}
.dl-kv .v {{ color: var(--dl-text); font-family: var(--dl-mono); }}

.dl-side-brand {{
    padding: 2px 2px 16px 2px;
    border-bottom: 1px solid var(--dl-border);
    margin-bottom: 12px;
}}
.dl-side-brand .logo {{
    font-family: var(--dl-mono);
    font-size: 1.28rem;
    font-weight: 700;
    letter-spacing: -0.02em;
}}
.dl-side-brand .logo span {{ color: var(--dl-green); }}
.dl-side-brand .tag {{
    color: var(--dl-muted);
    font-family: var(--dl-mono);
    font-size: 0.58rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-top: 4px;
}}
.dl-side-label {{
    font-family: var(--dl-mono);
    font-size: 0.58rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--dl-muted);
    margin: 16px 0 7px 2px;
}}
.dl-side-status {{
    background: rgba(30, 30, 30, 0.5);
    border: 1px solid var(--dl-border);
    border-radius: 10px;
    padding: 12px 13px;
    font-size: 0.75rem;
}}
.dl-side-status .row {{
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 3px 0;
    color: var(--dl-muted);
}}
.dl-side-status .row b {{
    color: var(--dl-text);
    font-family: var(--dl-mono);
    font-weight: 500;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"] {{
    padding: 9px 12px;
    border-radius: 8px;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label[data-baseweb="radio"] div p {{
    font-size: 0.82rem;
}}
[data-testid="stSidebar"] .stButton > button {{
    width: 100%;
    font-size: 0.78rem;
}}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
    font-size: 0.68rem;
}}
@media (max-width: 900px) {{
    .dl-hero {{ padding: 20px; }}
    .dl-edu {{ padding: 20px; }}
    .dl-mini-grid {{ grid-template-columns: 1fr; }}
    .dl-badge {{ flex-direction: column; align-items: flex-start; gap: 10px; }}
}}
</style>
"""


def html_block(markup: str) -> None:
    """Render a single-line HTML block.

    Streamlit's Markdown parser treats leading indentation and blank lines inside
    raw HTML as code blocks. Collapsing everything to one line keeps the custom
    terminal components intact across Streamlit versions.
    """
    cleaned = " ".join(textwrap.dedent(str(markup)).split())
    st.markdown(cleaned, unsafe_allow_html=True)


def inject_theme() -> None:
    html_block(CSS)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def hero(
    eyebrow: str,
    title: str,
    subtitle: str,
    chips: Iterable[tuple[str, str] | str] = (),
) -> None:
    chip_html = []
    for item in chips:
        if isinstance(item, tuple):
            label, tone = item
        else:
            label, tone = str(item), "muted"
        dot = '<span class="dot"></span>' if tone == "green" else ""
        chip_html.append(f'<span class="dl-chip { _e(tone) }">{dot}{_e(label)}</span>')
    html_block(f"""
        <div class="dl-hero">
            <div class="dl-eyebrow">{_e(eyebrow)}</div>
            <h1>{_e(title)}</h1>
            <p class="dl-sub">{_e(subtitle)}</p>
            <div class="dl-chips">{''.join(chip_html)}</div>
        </div>
        """)


def section_header(eyebrow: str, title: str, subtitle: str = "") -> None:
    sub = f'<div class="sub">{_e(subtitle)}</div>' if subtitle else ""
    html_block(f"""
        <div class="dl-section">
            <div>
                <div class="eyebrow">{_e(eyebrow)}</div>
                <h3>{_e(title)}</h3>
                {sub}
            </div>
        </div>
        """)


def kpi_card(label: str, value: str, sub: str = "", tone: str = "green") -> str:
    return f"""
    <div class="dl-kpi tone-{_e(tone)}">
        <div class="k-label">{_e(label)}</div>
        <div class="k-value">{_e(value)}</div>
        <div class="k-sub">{_e(sub)}</div>
    </div>
    """


def kpi_grid(cards: Iterable[str]) -> None:
    html_block(f'<div class="dl-kpi-grid">{"".join(cards)}</div>')


def chips(items: Iterable[tuple[str, str] | str]) -> None:
    rendered = []
    for item in items:
        label, tone = item if isinstance(item, tuple) else (str(item), "muted")
        rendered.append(f'<span class="dl-chip {_e(tone)}">{_e(label)}</span>')
    html_block(f'<div class="dl-chips">{"".join(rendered)}</div>')


def education_card(strategy: dict) -> None:
    tone = strategy.get("risk_tone", "green")
    steps = "".join(f"<li>{_e(step)}</li>" for step in strategy.get("steps", []))
    tags = "".join(
        f'<span class="dl-chip {_e("muted")}">{_e(tag)}</span>' for tag in strategy.get("tags", [])
    )
    html_block(f"""
        <div class="dl-edu">
            <div class="edu-topline">
                <span class="dl-chip green">Educational card</span>
                <span class="dl-chip muted">{_e(strategy.get("style", "Strategy"))}</span>
                <span class="dl-chip muted">Complexity · {_e(strategy.get("complexity", "—"))}</span>
            </div>
            <h2>{_e(strategy.get("title", ""))}</h2>
            <p class="tagline">{_e(strategy.get("tagline", ""))}</p>
            <div class="edu-block">
                <div class="edu-label">Core concept</div>
                <div class="concept">{_e(strategy.get("concept", ""))}</div>
            </div>
            <div class="edu-block">
                <div class="edu-label">How it works</div>
                <ol class="dl-steps">{steps}</ol>
            </div>
            <div class="edu-block">
                <div class="edu-label">Risk profile</div>
                <span class="dl-risk {_e(tone)}">{_e(strategy.get("risk_level", ""))}</span>
                <div class="dl-mini-grid">
                    <div class="dl-mini">
                        <div class="m-label">Ideal market</div>
                        <div class="m-value">{_e(strategy.get("market", ""))}</div>
                    </div>
                    <div class="dl-mini">
                        <div class="m-label">Primary risk</div>
                        <div class="m-value">{_e(strategy.get("risks", ""))}</div>
                    </div>
                </div>
                <div class="dl-chips" style="margin-top:12px;">{tags}</div>
            </div>
        </div>
        """)


def note(text: str, tone: str = "cyan") -> None:
    css = "" if tone == "cyan" else f" {tone}"
    html_block(f'<div class="dl-note{css}">{_e(text)}</div>')


def status_bar(items: list[tuple[str, str]], live: str = "LIVE SIMULATION") -> None:
    rendered = "".join(
        f'<span class="item">{_e(label)} <b>{_e(value)}</b></span>' for label, value in items
    )
    html_block(f"""
        <div class="dl-status">
            <span class="dl-live"><span class="pulse"></span>{_e(live)}</span>
            {rendered}
        </div>
        """)


def risk_alert(title: str, message: str, metrics: list[tuple[str, str]], severity: str = "high") -> None:
    metrics_html = "".join(f"<span>{_e(label)}: <b>{_e(value)}</b></span>" for label, value in metrics)
    html_block(f"""
        <div class="dl-alert">
            <div class="a-head">⚠ Risk alert · {_e(severity.upper())} · playback paused</div>
            <h3>{_e(title)}</h3>
            <p>{_e(message)}</p>
            <div class="a-metrics">{metrics_html}</div>
        </div>
        """)


def badge_card(score: ScoreCard) -> None:
    tone = "high" if score.score >= 70 else ("mid" if score.score >= 45 else "low")
    html_block(f"""
        <div class="dl-badge {tone}">
            <div class="medal">🏅</div>
            <div>
                <div class="b-label">Thematic profile · score {score.score}/100</div>
                <div class="b-title">{_e(score.badge)}</div>
                <div class="b-tag">{_e(score.tagline)}</div>
            </div>
        </div>
        """)


def sidebar_brand(subtitle: str) -> None:
    html_block(f"""
        <div class="dl-side-brand">
            <div class="logo">Deriv<span>Lab</span></div>
            <div class="tag">{_e(subtitle)}</div>
        </div>
        """)


def sidebar_label(text: str) -> None:
    html_block(f'<div class="dl-side-label">{_e(text)}</div>')


def sidebar_status(rows: list[tuple[str, str]]) -> None:
    body = "".join(f'<div class="row"><span>{_e(k)}</span><b>{_e(v)}</b></div>' for k, v in rows)
    html_block(f'<div class="dl-side-status">{body}</div>')


def footer() -> None:
    html_block("""
        <div class="dl-footer">
            <span>DERIVLAB · OPTIONS &amp; FUTURES STRATEGY EMULATOR</span>
            <span>SYNTHETIC BLACK-SCHOLES CHAINS · YAHOO FINANCE HISTORY · NOT INVESTMENT ADVICE</span>
        </div>
        """)
