"""Historical market data acquisition, local caching, and volatility estimates.

The public interface is :class:`MarketDataService`. It never lets a network
failure reach the UI: cached data is preferred, the bundled seed is the second
line of defence, and deterministic synthetic data is the final offline fallback.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    ASSETS,
    DATA_DIR,
    HV_WINDOW,
    MANIFEST_NAME,
    SEED_DIR,
    TRADING_DAYS,
    Asset,
    get_asset,
)

LOGGER = logging.getLogger(__name__)

REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")
_RENAME = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "adj close": "Close",
    "adj_close": "Close",
    "volume": "Volume",
}
MIN_ROWS_ACCEPTABLE = 100


class DataUnavailableError(RuntimeError):
    """Raised internally when neither the network nor local caches have data."""


@dataclass
class MarketData:
    """A validated OHLCV history plus provenance information."""

    asset: Asset
    frame: pd.DataFrame
    source: str
    path: Path | None = None
    note: str = ""

    @property
    def rows(self) -> int:
        return int(len(self.frame))

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(self.frame.index.min())

    @property
    def end(self) -> pd.Timestamp:
        return pd.Timestamp(self.frame.index.max())

    @property
    def latest_close(self) -> float:
        if self.frame.empty:
            return 0.0
        return float(self.frame["Close"].iloc[-1])

    @property
    def previous_close(self) -> float:
        if len(self.frame) < 2:
            return self.latest_close
        return float(self.frame["Close"].iloc[-2])

    @property
    def daily_change(self) -> float:
        prev = self.previous_close
        if prev <= 0:
            return 0.0
        return self.latest_close / prev - 1.0

    @property
    def latest_date(self) -> pd.Timestamp:
        return self.end

    def hv_series(self, window: int = HV_WINDOW) -> pd.Series:
        return compute_hv_series(self.frame["Close"], window=window)

    def latest_hv(self, window: int = HV_WINDOW) -> float:
        series = self.hv_series(window=window).dropna()
        if series.empty:
            return self.asset.base_iv
        value = float(series.iloc[-1])
        if not math.isfinite(value) or value <= 0:
            return self.asset.base_iv
        return value

    def tail_years(self, years: int) -> pd.DataFrame:
        if self.frame.empty:
            return self.frame
        cutoff = self.end - pd.DateOffset(years=max(int(years), 1))
        sliced = self.frame[self.frame.index >= cutoff]
        if len(sliced) < 60:
            return self.frame.tail(min(len(self.frame), 260))
        return sliced


@dataclass
class RefreshResult:
    """Outcome of one symbol refresh attempt."""

    symbol: str
    ok: bool
    message: str
    rows: int = 0
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None


@dataclass
class RefreshReport:
    """Aggregate outcome of a refresh batch."""

    results: list[RefreshResult] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> list[RefreshResult]:
        return [r for r in self.results if r.ok]

    @property
    def failed(self) -> list[RefreshResult]:
        return [r for r in self.results if not r.ok]

    @property
    def ok(self) -> bool:
        return bool(self.results) and not self.failed

    def summary(self) -> str:
        return f"{len(self.succeeded)} updated, {len(self.failed)} failed"


# ---------------------------------------------------------------------------
# DataFrame normalization and disk helpers
# ---------------------------------------------------------------------------


def _flatten_yfinance_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse yfinance's (Price, Ticker) MultiIndex into plain columns."""
    if not isinstance(frame.columns, pd.MultiIndex):
        return frame
    levels = [list(frame.columns.get_level_values(i)) for i in range(frame.columns.nlevels)]
    best_level = 0
    best_score = -1
    for idx, values in enumerate(levels):
        normalized = {str(v).strip().lower().replace("_", " ") for v in values}
        score = sum(1 for key in _RENAME if key in normalized)
        if score > best_score:
            best_level, best_score = idx, score
    frame = frame.copy()
    frame.columns = [str(col[best_level]).strip() for col in frame.columns]
    return frame


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a clean, tz-naive, sorted OHLCV frame or raise ValueError."""
    if frame is None or len(frame) == 0:
        raise ValueError("empty market data frame")

    df = _flatten_yfinance_columns(pd.DataFrame(frame).copy())
    df.columns = [str(c).strip() for c in df.columns]

    renamed = {}
    for col in df.columns:
        key = col.strip().lower().replace("_", " ")
        if key in _RENAME:
            renamed[col] = _RENAME[key]
    df = df.rename(columns=renamed)

    if "Close" not in df.columns:
        if "Adj Close" in df.columns:
            df["Close"] = df["Adj Close"]
        else:
            raise ValueError("market data has no Close/Adj Close column")

    if not isinstance(df.index, pd.DatetimeIndex):
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.set_index("Date")
        else:
            if "date" in {str(c).lower() for c in df.columns}:
                date_col = next(c for c in df.columns if str(c).lower() == "date")
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.set_index(date_col)
            else:
                df.index = pd.to_datetime(df.index, errors="coerce")

    try:
        index = pd.to_datetime(df.index, errors="coerce", utc=True)
        index = index.tz_convert(None)
    except (TypeError, ValueError):
        index = pd.to_datetime(df.index, errors="coerce")

    df.index = index
    df = df[~df.index.isna()]

    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            if col == "Volume":
                df[col] = 0.0
            elif col == "Open":
                df[col] = df["Close"]
            elif col == "High":
                df[col] = df[["Open", "Close"]].max(axis=1)
            elif col == "Low":
                df[col] = df[["Open", "Close"]].min(axis=1)
            else:
                raise ValueError(f"market data has no {col} column")

    for col in REQUIRED_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    df["Volume"] = df["Volume"].fillna(0.0).clip(lower=0.0)

    for col in ("Open", "High", "Low"):
        df[col] = df[col].fillna(df["Close"])
    df["High"] = df[["High", "Open", "Close"]].max(axis=1)
    df["Low"] = df[["Low", "Open", "Close"]].min(axis=1)
    df["Open"] = df["Open"].clip(lower=0.000001)

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df[list(REQUIRED_COLUMNS)]

    if len(df) < 5:
        raise ValueError("market data has fewer than 5 usable rows")
    return df


def save_frame(frame: pd.DataFrame, path: Path) -> Path:
    """Save a normalized frame atomically, preferring Parquet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_frame(frame)
    target = path
    if path.suffix != ".parquet":
        target = path.with_suffix(".parquet")
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        normalized.to_parquet(tmp, engine="pyarrow", compression="snappy")
        os.replace(tmp, target)
        return target
    except Exception as exc:  # pyarrow missing or parquet engine failure
        LOGGER.debug("Parquet save failed for %s: %s", target, exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        fallback = path.with_suffix(".csv.gz")
        normalized.to_csv(fallback, compression="gzip")
        return fallback


def load_frame(path: Path) -> pd.DataFrame:
    """Load a cached frame from Parquet or CSV, normalizing it."""
    if path.suffix == ".parquet":
        return _normalize_frame(pd.read_parquet(path, engine="pyarrow"))
    if path.suffix in {".csv", ".gz"}:
        return _normalize_frame(pd.read_csv(path, index_col=0, parse_dates=True))
    raise ValueError(f"Unsupported data file: {path}")


def compute_hv_series(close: pd.Series, window: int = HV_WINDOW) -> pd.Series:
    """Annualized rolling historical volatility from daily log returns."""
    close = pd.to_numeric(pd.Series(close), errors="coerce").dropna()
    if len(close) < 3:
        return pd.Series(index=close.index, dtype=float)
    returns = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan)
    min_periods = max(3, min(window, max(3, window // 2)))
    vol = returns.rolling(window=window, min_periods=min_periods).std(ddof=1) * math.sqrt(TRADING_DAYS)
    return vol.replace([np.inf, -np.inf], np.nan).ffill()


def latest_hv(close: pd.Series, window: int = HV_WINDOW, fallback: float = 0.25) -> float:
    series = compute_hv_series(close, window=window).dropna()
    if series.empty:
        return fallback
    value = float(series.iloc[-1])
    return value if math.isfinite(value) and value > 0 else fallback


# ---------------------------------------------------------------------------
# Deterministic offline fallback
# ---------------------------------------------------------------------------


def synthetic_frame(asset: Asset, years: int = 5, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Generate deterministic, clearly-labelled synthetic OHLCV data.

    This is only used when both the runtime cache and the bundled seed are
    missing and the network is unavailable. It keeps every screen operational
    without pretending to be real market history.
    """
    end = pd.Timestamp(end or pd.Timestamp.utcnow().tz_localize(None).normalize())
    periods = max(int(years * 252), 260)
    index = pd.bdate_range(end=end, periods=periods, name="Date")
    seed = zlib.crc32(asset.symbol.encode("utf-8")) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    vol = max(asset.base_iv, 0.05)
    dt = 1.0 / TRADING_DAYS
    drift = 0.055
    shocks = rng.normal((drift - 0.5 * vol * vol) * dt, vol * math.sqrt(dt), size=periods)
    # A handful of macro-style jumps makes the demo feel less synthetic.
    jump_days = rng.choice(periods, size=max(3, periods // 180), replace=False)
    shocks[jump_days] += rng.normal(0.0, 0.035, size=len(jump_days))
    closes = asset.base_price * np.exp(np.cumsum(shocks))
    closes *= asset.base_price / closes[-1]
    opens = np.concatenate([[closes[0]], closes[:-1] * np.exp(rng.normal(0, 0.0035, size=periods - 1))])
    highs = np.maximum(opens, closes) * (1.0 + np.abs(rng.normal(0, 0.006, size=periods)))
    lows = np.minimum(opens, closes) * (1.0 - np.abs(rng.normal(0, 0.006, size=periods)))
    volume = rng.lognormal(mean=15.0, sigma=0.35, size=periods)
    frame = pd.DataFrame(
        {
            "Open": opens,
            "High": np.maximum.reduce([highs, opens, closes]),
            "Low": np.minimum.reduce([lows, opens, closes]),
            "Close": closes,
            "Volume": volume,
        },
        index=index,
    )
    return _normalize_frame(frame)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MarketDataService:
    """Load, validate, download, and persist market history for the universe."""

    def __init__(
        self,
        cache_dir: Path | str = DATA_DIR,
        seed_dir: Path | str = SEED_DIR,
        assets: dict[str, Asset] | None = None,
        create_dirs: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir).expanduser().resolve()
        self.seed_dir = Path(seed_dir).expanduser().resolve()
        self.assets = dict(assets or ASSETS)
        self.yf_cache_dir = self.cache_dir / "yf_cache"
        if create_dirs:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.seed_dir.mkdir(parents=True, exist_ok=True)

    # -- paths -------------------------------------------------------------
    def cache_path(self, symbol: str, suffix: str = ".parquet") -> Path:
        return self.cache_dir / f"{slug_for(symbol)}{suffix}"

    def seed_path(self, symbol: str, suffix: str = ".parquet") -> Path:
        return self.seed_dir / f"{slug_for(symbol)}{suffix}"

    def _candidate_paths(self, symbol: str) -> list[Path]:
        paths: list[Path] = []
        for base in (self.cache_dir, self.seed_dir):
            for suffix in (".parquet", ".csv.gz", ".csv"):
                path = base / f"{slug_for(symbol)}{suffix}"
                if path.exists() and path.is_file():
                    paths.append(path)
        return paths

    # -- loading -----------------------------------------------------------
    def load(self, symbol: str, allow_synthetic: bool = True) -> MarketData:
        """Load the freshest local copy; never performs a network request."""
        asset = self.assets.get(symbol) or get_asset(symbol)
        candidates = self._candidate_paths(symbol)
        frames: list[MarketData] = []
        for path in candidates:
            try:
                frame = load_frame(path)
                source = "cache" if self.cache_dir in path.parents else "seed"
                frames.append(MarketData(asset=asset, frame=frame, source=source, path=path))
            except Exception as exc:
                LOGGER.warning("Could not read %s: %s", path, exc)
        if frames:
            # Prefer the freshest history; on a tie prefer the refreshed runtime
            # cache over the bundled seed.
            frames.sort(key=lambda item: (item.end, 1 if item.source == "cache" else 0))
            best = frames[-1]
            if best.source == "seed":
                best.note = "Bundled historical seed. Refresh in Data Vault to update."
            else:
                best.note = "Runtime cache."
            return best
        if allow_synthetic:
            frame = synthetic_frame(asset)
            return MarketData(
                asset=asset,
                frame=frame,
                source="synthetic",
                note=(
                    "OFFLINE FALLBACK: deterministic synthetic prices. Run the data "
                    "preprocessor or refresh Data Vault to load real market history."
                ),
            )
        raise DataUnavailableError(f"No local data available for {symbol}")

    def load_many(self, symbols: Iterable[str]) -> dict[str, MarketData]:
        result: dict[str, MarketData] = {}
        for symbol in symbols:
            try:
                result[symbol] = self.load(symbol)
            except Exception as exc:  # defensive; load() normally never raises
                LOGGER.warning("Skipping %s: %s", symbol, exc)
        return result

    # -- downloading -------------------------------------------------------
    def _download_one(self, symbol: str, years: int = 5) -> pd.DataFrame:
        import yfinance as yf  # imported lazily to keep app start-up fast

        try:
            self.yf_cache_dir.mkdir(parents=True, exist_ok=True)
            yf.set_tz_cache_location(str(self.yf_cache_dir))
            if hasattr(yf, "set_cache_location"):
                yf.set_cache_location(str(self.yf_cache_dir))
        except Exception as exc:  # cache location is a nicety, not a requirement
            LOGGER.debug("Could not configure yfinance cache: %s", exc)

        errors: list[str] = []
        try:
            raw = yf.download(
                tickers=symbol,
                period=f"{int(years)}y",
                interval="1d",
                auto_adjust=True,
                actions=False,
                progress=False,
                threads=False,
            )
            if raw is not None and len(raw) > 0:
                return _normalize_frame(raw)
            errors.append("empty download")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

        # Second attempt via the Ticker API - independent code path on Yahoo.
        try:
            raw = yf.Ticker(symbol).history(
                period=f"{int(years)}y",
                interval="1d",
                auto_adjust=True,
                actions=False,
                timeout=30,
            )
            if raw is not None and len(raw) > 0:
                return _normalize_frame(raw)
            errors.append("empty ticker history")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

        raise DataUnavailableError("; ".join(errors)[:300] or "unknown download error")

    def refresh_one(self, symbol: str, years: int = 5, retries: int = 3) -> RefreshResult:
        asset = self.assets.get(symbol) or get_asset(symbol)
        attempt_errors: list[str] = []
        for attempt in range(1, max(int(retries), 1) + 1):
            try:
                frame = self._download_one(asset.symbol, years=years)
                if len(frame) < MIN_ROWS_ACCEPTABLE:
                    raise DataUnavailableError(f"only {len(frame)} rows returned")
                path = save_frame(frame, self.cache_path(asset.symbol))
                LOGGER.info("Updated %s (%s rows) -> %s", asset.symbol, len(frame), path)
                return RefreshResult(
                    symbol=asset.symbol,
                    ok=True,
                    message=f"{len(frame):,} rows saved",
                    rows=len(frame),
                    start=frame.index.min(),
                    end=frame.index.max(),
                )
            except Exception as exc:
                attempt_errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                LOGGER.warning("Download failed for %s on attempt %s: %s", asset.symbol, attempt, exc)
                if attempt < retries:
                    time.sleep(min(2.0 * attempt, 5.0))
        return RefreshResult(
            symbol=asset.symbol,
            ok=False,
            message=attempt_errors[-1] if attempt_errors else "download failed",
        )

    def refresh(
        self,
        symbols: Iterable[str] | None = None,
        years: int = 5,
        retries: int = 3,
        pause: float = 0.6,
    ) -> RefreshReport:
        selected = list(symbols) if symbols else list(self.assets)
        report = RefreshReport()
        for idx, symbol in enumerate(selected):
            result = self.refresh_one(symbol, years=years, retries=retries)
            report.results.append(result)
            if result.ok and idx < len(selected) - 1:
                time.sleep(max(pause, 0.0))
        self.write_manifest(report=report, years=years)
        return report

    # -- seed management ---------------------------------------------------
    def promote_to_seed(self, symbols: Iterable[str] | None = None) -> list[str]:
        """Copy successfully refreshed cache files into the bundled seed folder."""
        selected = list(symbols) if symbols else list(self.assets)
        promoted: list[str] = []
        for symbol in selected:
            asset = self.assets.get(symbol) or get_asset(symbol)
            src = self.cache_path(asset.symbol)
            if not src.exists():
                # try CSV fallback
                src = self.cache_path(asset.symbol, ".csv.gz")
            if not src.exists():
                continue
            try:
                frame = load_frame(src)
                save_frame(frame, self.seed_path(asset.symbol))
                promoted.append(asset.symbol)
            except Exception as exc:
                LOGGER.warning("Could not promote %s to seed: %s", symbol, exc)
        self.write_manifest(directory=self.seed_dir, symbols=promoted or None, years=5)
        return promoted

    # -- manifests and status --------------------------------------------
    def write_manifest(
        self,
        directory: Path | None = None,
        report: RefreshReport | None = None,
        symbols: Iterable[str] | None = None,
        years: int = 5,
    ) -> Path:
        directory = Path(directory or self.cache_dir)
        directory.mkdir(parents=True, exist_ok=True)
        selected = list(symbols) if symbols else list(self.assets)
        entries = []
        for symbol in selected:
            asset = self.assets.get(symbol) or get_asset(symbol)
            path = None
            for base in (directory,):
                for suffix in (".parquet", ".csv.gz", ".csv"):
                    candidate = base / f"{slug_for(symbol)}{suffix}"
                    if candidate.exists():
                        path = candidate
                        break
                if path:
                    break
            if not path:
                continue
            try:
                frame = load_frame(path)
                entries.append(
                    {
                        "symbol": asset.symbol,
                        "rows": int(len(frame)),
                        "start": frame.index.min().date().isoformat(),
                        "end": frame.index.max().date().isoformat(),
                        "file": path.name,
                    }
                )
            except Exception as exc:
                LOGGER.debug("Manifest skipped %s: %s", symbol, exc)
        payload = {
            "app": "DerivLab",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "yfinance (Yahoo Finance)",
            "years_requested": int(years),
            "assets": entries,
            "last_refresh": (
                {
                    "succeeded": [r.symbol for r in report.succeeded],
                    "failed": [r.symbol for r in report.failed],
                }
                if report
                else None
            ),
        }
        path = directory / MANIFEST_NAME
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def manifest(self, directory: Path | None = None) -> dict:
        path = Path(directory or self.cache_dir) / MANIFEST_NAME
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def coverage(self) -> pd.DataFrame:
        """One-row-per-asset inventory used by the Data Vault screen."""
        rows = []
        for symbol, asset in self.assets.items():
            loaded: MarketData | None = None
            error = ""
            try:
                loaded = self.load(symbol)
            except Exception as exc:
                error = str(exc)
            if loaded is None:
                rows.append(
                    {
                        "Symbol": symbol,
                        "Name": asset.short_name,
                        "Class": asset.asset_class,
                        "Region": asset.region,
                        "Currency": asset.currency,
                        "Source": "missing",
                        "Rows": 0,
                        "Start": None,
                        "End": None,
                        "Last": None,
                        "HV 30d": None,
                        "Status": error or "No data",
                    }
                )
                continue
            hv = loaded.latest_hv()
            status = {
                "cache": "Live cache",
                "seed": "Bundled seed",
                "synthetic": "Synthetic fallback",
            }.get(loaded.source, loaded.source)
            rows.append(
                {
                    "Symbol": symbol,
                    "Name": asset.short_name,
                    "Class": asset.asset_class,
                    "Region": asset.region,
                    "Currency": asset.currency,
                    "Source": loaded.source,
                    "Rows": loaded.rows,
                    "Start": loaded.start.date().isoformat(),
                    "End": loaded.end.date().isoformat(),
                    "Last": loaded.latest_close,
                    "HV 30d": hv,
                    "Status": status,
                    "Path": str(loaded.path) if loaded.path else "",
                }
            )
        return pd.DataFrame(rows)

    def stats(self) -> dict:
        coverage = self.coverage()
        if coverage.empty:
            return {"assets": 0, "rows": 0, "latest": None, "sources": {}}
        return {
            "assets": int((coverage["Rows"] > 0).sum()),
            "rows": int(coverage["Rows"].sum()),
            "latest": coverage["End"].dropna().max(),
            "sources": coverage["Source"].value_counts().to_dict(),
            "synthetic": int((coverage["Source"] == "synthetic").sum()),
        }

    def purge_runtime_cache(self) -> int:
        """Delete runtime cache files, falling back to the bundled seed."""
        removed = 0
        for path in self.cache_dir.glob("*"):
            if path.name == "yf_cache" or path.is_dir():
                continue
            if path.suffix in {".parquet", ".csv", ".gz", ".json"}:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


def slug_for(symbol: str) -> str:
    from .config import slugify_symbol

    return slugify_symbol(symbol)
