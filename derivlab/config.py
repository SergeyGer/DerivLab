"""Application-wide configuration: asset universe, palette and strategy copy.

Everything that a demo presenter may want to tune lives in this module. All
user-facing text is in English, as required by the project specification.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths and application metadata
# ---------------------------------------------------------------------------

APP_NAME = "DerivLab"
APP_VERSION = "1.0.0"
APP_TITLE = "Options & Futures Strategy Emulator"
APP_SUBTITLE = (
    "Learn, configure, and backtest advanced trading strategies using "
    "synthetic options and historical market data."
)
DISCLAIMER = (
    "Educational simulator only. Synthetic option chains are generated with "
    "the Black-Scholes model and are not executable market quotes. Nothing "
    "here is investment advice."
)

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default.resolve()


DATA_DIR = _env_path("DERIVLAB_DATA_DIR", BASE_DIR / "data" / "cache")
SEED_DIR = _env_path("DERIVLAB_SEED_DIR", BASE_DIR / "data" / "seed")
YF_CACHE_DIR = DATA_DIR / "yf_cache"
MANIFEST_NAME = "manifest.json"

# ---------------------------------------------------------------------------
# Market model constants
# ---------------------------------------------------------------------------

TRADING_DAYS = 252
HV_WINDOW = 30
IV_FLOOR = 0.05
IV_CAP = 2.50
DEFAULT_FEE_BPS = 5.0
DEFAULT_LOOKBACK_YEARS = 5
DEFAULT_TENOR_DAYS = 30
DEFAULT_LOTS = 2.0
TERM_DAYS = (30, 60, 90)
LOOKBACK_YEARS = (1, 3, 5)
MAX_CONTRACTS = 10_000

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "JPY": "¥", "GBP": "£"}

RISK_FREE_ANCHORS = {
    "USD": (0.0400, "US Treasury 13-week anchor (~4.00%)"),
    "EUR": (0.0275, "ECB deposit-facility anchor (~2.75%)"),
    "JPY": (0.0050, "Bank of Japan policy anchor (~0.50%)"),
}

# ---------------------------------------------------------------------------
# Dark "financial cyberpunk" palette (mandated by the specification)
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#121212",
    "bg_deep": "#0C0D10",
    "panel": "#1E1E1E",
    "panel_alt": "#17181C",
    "border": "#2A2D34",
    "grid": "#24272E",
    "text": "#F5F5F5",
    "muted": "#9AA1AE",
    "silver": "#C3C8D2",
    "green": "#00E676",
    "green_soft": "rgba(0, 230, 118, 0.14)",
    "pink": "#FF1744",
    "pink_soft": "rgba(255, 23, 68, 0.14)",
    "magenta": "#E040FB",
    "cyan": "#00E5FF",
    "amber": "#FFD166",
    "violet": "#7C4DFF",
}

FONT_SANS = (
    '"Inter", "SF Pro Display", -apple-system, BlinkMacSystemFont, '
    '"Segoe UI", Roboto, Helvetica, Arial, sans-serif'
)
FONT_MONO = '"JetBrains Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace'


# ---------------------------------------------------------------------------
# Asset universe (Section 3 of the SRS)
# ---------------------------------------------------------------------------


def slugify_symbol(symbol: str) -> str:
    """Return a filesystem-safe, stable storage key for a ticker symbol."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_")
    return cleaned.upper() or "ASSET"


@dataclass(frozen=True)
class Asset:
    """Metadata for one tradable instrument in the simulation universe."""

    symbol: str
    name: str
    short_name: str
    asset_class: str
    region: str
    currency: str
    multiplier: float
    unit_label: str
    dividend_yield: float
    base_price: float
    base_iv: float
    color: str

    @property
    def storage_key(self) -> str:
        return slugify_symbol(self.symbol)

    @property
    def currency_symbol(self) -> str:
        return CURRENCY_SYMBOLS.get(self.currency, self.currency)

    @property
    def display_name(self) -> str:
        return f"{self.symbol} · {self.short_name}"

    @property
    def one_lot_notional_text(self) -> str:
        return f"1 simulated lot = {self.multiplier:,.0f} {self.unit_label}"

    @property
    def risk_free_anchor(self) -> tuple[float, str]:
        return RISK_FREE_ANCHORS.get(self.currency, (0.03, "Indicative rate"))


ASSETS: dict[str, Asset] = {
    # US equities
    "AAPL": Asset("AAPL", "Apple Inc.", "Apple", "US Equity", "United States", "USD", 100, "shares", 0.0045, 340.0, 0.26, COLORS["cyan"]),
    "MSFT": Asset("MSFT", "Microsoft Corporation", "Microsoft", "US Equity", "United States", "USD", 100, "shares", 0.0075, 530.0, 0.24, COLORS["cyan"]),
    "NVDA": Asset("NVDA", "NVIDIA Corporation", "NVIDIA", "US Equity", "United States", "USD", 100, "shares", 0.0003, 220.0, 0.45, COLORS["cyan"]),
    # European equities
    "SAP.DE": Asset("SAP.DE", "SAP SE", "SAP", "European Equity", "Germany", "EUR", 100, "shares", 0.016, 205.0, 0.24, COLORS["violet"]),
    "ALV.DE": Asset("ALV.DE", "Allianz SE", "Allianz", "European Equity", "Germany", "EUR", 100, "shares", 0.045, 435.0, 0.22, COLORS["violet"]),
    "ASML.AS": Asset("ASML.AS", "ASML Holding N.V.", "ASML", "European Equity", "Netherlands", "EUR", 100, "shares", 0.008, 1_440.0, 0.32, COLORS["violet"]),
    # Forex
    "EURUSD=X": Asset("EURUSD=X", "Euro / US Dollar", "EUR/USD", "Forex", "Global", "USD", 10_000, "EUR units", 0.0, 1.12, 0.08, COLORS["amber"]),
    "JPY=X": Asset("JPY=X", "US Dollar / Japanese Yen", "USD/JPY", "Forex", "Global", "JPY", 10_000, "USD units", 0.0, 157.0, 0.10, COLORS["amber"]),
    # Commodities
    "GC=F": Asset("GC=F", "Gold Futures (front month)", "Gold", "Commodity", "Global", "USD", 10, "troy ounces", 0.0, 4_100.0, 0.16, COLORS["gold"] if "gold" in COLORS else COLORS["amber"]),
    "BZ=F": Asset("BZ=F", "Brent Crude Oil Futures", "Brent", "Commodity", "Global", "USD", 100, "barrels", 0.0, 112.0, 0.34, COLORS["amber"]),
    # Indices
    "^GSPC": Asset("^GSPC", "S&P 500 Index", "S&P 500", "Index", "United States", "USD", 1, "index units", 0.013, 7_750.0, 0.16, COLORS["green"]),
    "^DJI": Asset("^DJI", "Dow Jones Industrial Average", "Dow 30", "Index", "United States", "USD", 1, "index units", 0.016, 52_800.0, 0.15, COLORS["green"]),
    "^GDAXI": Asset("^GDAXI", "DAX 40 Index", "DAX 40", "Index", "Germany", "EUR", 1, "index units", 0.022, 25_350.0, 0.18, COLORS["green"]),
    "^FCHI": Asset("^FCHI", "CAC 40 Index", "CAC 40", "Index", "France", "EUR", 1, "index units", 0.032, 7_830.0, 0.17, COLORS["green"]),
}

ASSET_SYMBOLS: tuple[str, ...] = tuple(ASSETS)
ASSET_GROUPS: dict[str, tuple[str, ...]] = {
    "US Equities": ("AAPL", "MSFT", "NVDA"),
    "European Equities": ("SAP.DE", "ALV.DE", "ASML.AS"),
    "Forex": ("EURUSD=X", "JPY=X"),
    "Commodities": ("GC=F", "BZ=F"),
    "Indices": ("^GSPC", "^DJI", "^GDAXI", "^FCHI"),
}


def get_asset(symbol: str) -> Asset:
    """Look up an asset, raising a friendly error for unknown symbols."""
    try:
        return ASSETS[symbol]
    except KeyError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Unknown asset symbol: {symbol!r}") from exc


# ---------------------------------------------------------------------------
# Strategy education database (Screen 1 copy)
# ---------------------------------------------------------------------------

STRATEGY_ORDER: tuple[str, ...] = (
    "basis_trade",
    "covered_call",
    "cash_secured_put",
    "long_straddle",
    "iron_condor",
)

STRATEGY_EDU_DB: dict[str, dict] = {
    "basis_trade": {
        "label": "🔗 Basis Trade (Futures Arbitrage)",
        "short": "Basis Trade",
        "title": "Basis Trade (Futures Arbitrage)",
        "tagline": "Capture the price gap between spot and futures markets.",
        "concept": (
            "When a market is bullish or cash is tight, futures contracts often "
            "trade above the actual asset. That gap is called contango. A basis "
            "trade buys the spot asset and simultaneously shorts a synthetic "
            "futures contract. As expiration approaches, the futures price "
            "converges to spot. The locked-in gap is the basis."
        ),
        "steps": [
            "Buy the spot asset at the current market price.",
            "Short a synthetic futures contract on the same asset at a premium.",
            "Hold both legs until expiration, when spot and futures converge.",
            "Realize the captured basis, then roll into the next contract.",
        ],
        "market": "Bullish or high-volatility regimes, when futures premiums are widest.",
        "risk_level": "🟢 Low / Delta-Neutral",
        "risk_tone": "green",
        "risks": (
            "Execution slippage, funding-rate changes, margin calls on the short "
            "future, and exchange/counterparty risk. The hedge neutralizes "
            "direction, not operational risk."
        ),
        "style": "Basis capture",
        "complexity": "Intermediate",
        "tags": ["Delta-neutral", "Carry", "Futures"],
    },
    "covered_call": {
        "label": "🛡️ Covered Call (Income Generation)",
        "short": "Covered Call",
        "title": "Covered Call",
        "tagline": "Turn a long-term stock portfolio into a steady income stream.",
        "concept": (
            "If you own shares and expect the price to stay flat or rise slowly, "
            "you can sell call options against them. The buyer pays you a premium "
            "today for the right to buy your shares at the strike price. If the "
            "stock finishes below the strike, you keep the shares and the "
            "premium, and you can repeat the trade."
        ),
        "steps": [
            "Buy or hold one simulated lot of shares.",
            "Sell one out-of-the-money call option per lot, expiring in 30-90 days.",
            "Collect the premium immediately as cash.",
            "If the call expires worthless, keep the shares and sell another. "
            "If it finishes in the money, the shares are called away.",
        ],
        "market": "Flat, sideways, or mildly bullish markets with stable volatility.",
        "risk_level": "🟡 Medium",
        "risk_tone": "amber",
        "risks": (
            "You remain fully exposed to a stock crash. Upside is capped: if the "
            "stock rallies far above the strike, the shares are sold at the "
            "strike and you miss the extra gain."
        ),
        "style": "Premium income",
        "complexity": "Beginner",
        "tags": ["Income", "Long stock", "Short call"],
    },
    "cash_secured_put": {
        "label": "💵 Cash-Secured Put (Buy at a Discount)",
        "short": "Cash-Secured Put",
        "title": "Cash-Secured Put",
        "tagline": "Get paid to wait for a chance to buy an asset at a discount.",
        "concept": (
            "Instead of buying at the current price, you sell a put at a lower "
            "strike where you would be happy to own the asset. You set aside the "
            "cash needed to buy it, so the position is fully secured. Another "
            "trader pays you a premium for the obligation to buy their asset if "
            "it falls below your strike."
        ),
        "steps": [
            "Pick a strike below the current spot price.",
            "Set aside enough cash to buy one lot at that strike.",
            "Sell the put and collect the premium immediately.",
            "If the asset stays above the strike, keep the premium and repeat. "
            "If it falls below, you are assigned shares at the strike.",
        ],
        "market": "Neutral to mildly bullish markets, or while waiting for a pullback.",
        "risk_level": "🟡 Medium",
        "risk_tone": "amber",
        "risks": (
            "A sharp crash still forces you to buy at the strike. The premium "
            "softens the entry price but does not remove downside risk. "
            "Assignment consumes the reserved cash."
        ),
        "style": "Premium income",
        "complexity": "Beginner",
        "tags": ["Income", "Short put", "Collateralized"],
    },
    "long_straddle": {
        "label": "⚡ Long Straddle (Volatility Expansion)",
        "short": "Long Straddle",
        "title": "Long Straddle",
        "tagline": "Bet on a big move without guessing which direction it takes.",
        "concept": (
            "A long straddle buys a call and a put with the same strike and "
            "expiration. It profits if the underlying moves far enough in either "
            "direction to cover the total premium paid. Direction does not "
            "matter; the size of the move and the timing do."
        ),
        "steps": [
            "Buy one at-the-money call and one at-the-money put.",
            "Pay a net debit for both options.",
            "Wait for a volatility event, such as earnings or a macro surprise.",
            "Profit if spot finishes beyond either break-even; lose the debit if "
            "it stays pinned near the strike.",
        ],
        "market": "A large move is expected, but its direction is unknown.",
        "risk_level": "🟠 Medium-High",
        "risk_tone": "pink",
        "risks": (
            "Time decay works against both legs. An implied-volatility crush can "
            "lose money even when the price moves. Maximum loss is the premium "
            "paid, plus costs."
        ),
        "style": "Volatility long",
        "complexity": "Advanced",
        "tags": ["Long volatility", "Debit", "Two legs"],
    },
    "iron_condor": {
        "label": "🕸️ Iron Condor (Range Income)",
        "short": "Iron Condor",
        "title": "Iron Condor",
        "tagline": "Collect premium while the market sleeps inside a defined range.",
        "concept": (
            "An iron condor sells an out-of-the-money call spread and an "
            "out-of-the-money put spread at the same time. The two short options "
            "collect premium, while the two long wings cap the maximum loss. "
            "You profit if the underlying finishes between the short strikes."
        ),
        "steps": [
            "Sell an OTM call and an OTM put to collect a net credit.",
            "Buy a further-OTM call and put to define the risk on both sides.",
            "Wait for expiration while price stays inside the short strikes.",
            "Keep the credit if price finishes inside. Pay the spread difference "
            "if price breaks out beyond a wing.",
        ],
        "market": "Low-volatility, range-bound markets with no major catalyst.",
        "risk_level": "🟡 Medium",
        "risk_tone": "amber",
        "risks": (
            "A sharp breakout can hit the maximum loss, which equals the wing "
            "width minus the credit. Four legs also mean more transaction costs "
            "and wider execution slippage."
        ),
        "style": "Premium income",
        "complexity": "Advanced",
        "tags": ["Range-bound", "Credit", "Four legs"],
    },
}

STRATEGY_META = {
    "basis_trade": {"strike_mode": "none", "premium_style": "basis", "default_tenor": 90, "default_offset": 0.0},
    "covered_call": {"strike_mode": "call", "premium_style": "credit", "default_tenor": 30, "default_offset": 5.0},
    "cash_secured_put": {"strike_mode": "put", "premium_style": "credit", "default_tenor": 30, "default_offset": -5.0},
    "long_straddle": {"strike_mode": "straddle", "premium_style": "debit", "default_tenor": 30, "default_offset": 0.0},
    "iron_condor": {"strike_mode": "condor", "premium_style": "credit", "default_tenor": 30, "default_offset": 5.0},
}

CALL_PRESETS: tuple[tuple[str, float], ...] = (
    ("ATM · 0%", 0.0),
    ("5% OTM · +5%", 5.0),
    ("10% OTM · +10%", 10.0),
    ("5% ITM · -5%", -5.0),
    ("10% ITM · -10%", -10.0),
)
PUT_PRESETS: tuple[tuple[str, float], ...] = (
    ("ATM · 0%", 0.0),
    ("5% OTM · -5%", -5.0),
    ("10% OTM · -10%", -10.0),
    ("5% ITM · +5%", 5.0),
    ("10% ITM · +10%", 10.0),
)
STRADDLE_PRESETS: tuple[tuple[str, float], ...] = (
    ("ATM straddle · 0%", 0.0),
    ("5% OTM · +5%", 5.0),
    ("5% ITM · -5%", -5.0),
    ("10% OTM · +10%", 10.0),
    ("10% ITM · -10%", -10.0),
)


def strike_presets(strategy_key: str) -> tuple[tuple[str, float], ...]:
    mode = STRATEGY_META.get(strategy_key, {}).get("strike_mode", "call")
    if mode == "put":
        return PUT_PRESETS
    if mode == "straddle":
        return STRADDLE_PRESETS
    return CALL_PRESETS


# ---------------------------------------------------------------------------
# Hold-the-Position scenarios
# ---------------------------------------------------------------------------

GAME_SCENARIOS: tuple[dict, ...] = (
    {
        "id": "rate_shock_2022",
        "label": "2022 · Rate Shock",
        "start": "2022-01-03",
        "end": "2022-12-30",
        "blurb": "Inflation, aggressive hikes, and a brutal year for long-duration stocks.",
    },
    {
        "id": "recovery_2023",
        "label": "2023 · Recovery Grind",
        "start": "2023-01-03",
        "end": "2023-12-29",
        "blurb": "A slow, uneven recovery with pockets of sharp volatility.",
    },
    {
        "id": "rally_2024",
        "label": "2024 · Momentum Rally",
        "start": "2024-01-02",
        "end": "2024-12-31",
        "blurb": "Strong trend and complacent volatility - friendly to income sellers.",
    },
    {
        "id": "last_12m",
        "label": "Latest 12 Months",
        "start": None,
        "end": None,
        "lookback_bars": 253,
        "blurb": "The most recent market year available in your local data cache.",
    },
    {
        "id": "full_history",
        "label": "Full 5-Year Marathon",
        "start": None,
        "end": None,
        "blurb": "Ride the full cached history from the first available trading day.",
    },
)

# ---------------------------------------------------------------------------
# Formatting helpers shared by charts and the UI
# ---------------------------------------------------------------------------


def suggested_capital(spot: float, multiplier: float, lots: float = DEFAULT_LOTS) -> int:
    """Choose a friendly default capital figure that buys roughly a few lots."""
    raw = max(spot * multiplier * lots, 25_000.0)
    if raw >= 1_000_000:
        step = 50_000
    elif raw >= 100_000:
        step = 5_000
    elif raw >= 10_000:
        step = 1_000
    else:
        step = 100
    return max(int(round(raw / step) * step), 1_000)


def format_money(value: float, currency: str = "USD", compact: bool = True) -> str:
    """Format a monetary value with the right symbol and a compact suffix."""
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    amount = abs(float(value))
    if compact and amount >= 1_000_000_000:
        return f"{sign}{symbol}{amount / 1_000_000_000:.2f}B"
    if compact and amount >= 1_000_000:
        return f"{sign}{symbol}{amount / 1_000_000:.2f}M"
    if compact and amount >= 1_000:
        return f"{sign}{symbol}{amount / 1_000:.1f}K"
    return f"{sign}{symbol}{amount:,.2f}"


def format_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.{digits}f}%"


def format_number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"
