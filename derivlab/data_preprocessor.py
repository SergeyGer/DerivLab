"""Command-line data preparation script (SRS Module 1).

Examples
--------
Download five years of daily data for every asset into the runtime cache::

    python -m derivlab.data_preprocessor --all --years 5

Refresh the runtime cache and promote successful downloads into the bundled
seed folder used by Docker and offline demos::

    python -m derivlab.data_preprocessor --all --years 5 --output both

Inspect the local cache without touching the network::

    python -m derivlab.data_preprocessor --check
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ASSETS, DATA_DIR, SEED_DIR
from .data_fetcher import MarketDataService

LOGGER = logging.getLogger("derivlab.data")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m derivlab.data_preprocessor",
        description="Download and cache five years of daily market data for DerivLab.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Ticker symbols to refresh (default: the full SRS universe).",
    )
    parser.add_argument("--all", action="store_true", help="Refresh the full asset universe.")
    parser.add_argument("--years", type=int, default=5, help="Years of daily history (default: 5).")
    parser.add_argument("--retries", type=int, default=3, help="Download attempts per symbol.")
    parser.add_argument(
        "--output",
        choices=("cache", "seed", "both"),
        default="cache",
        help="Where to persist successful downloads (default: runtime cache).",
    )
    parser.add_argument("--check", action="store_true", help="Print the local data inventory and exit.")
    parser.add_argument("--pause", type=float, default=0.6, help="Seconds between symbols (rate-limit safety).")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output.")
    return parser


def _print_inventory(service: MarketDataService) -> None:
    coverage = service.coverage()
    print()
    print(f"{'Symbol':<10} {'Source':<10} {'Rows':>5} {'Start':<12} {'End':<12} {'Last':>12} {'HV30':>7}")
    print("-" * 78)
    for _, row in coverage.iterrows():
        hv = row.get("HV 30d")
        hv_text = f"{float(hv) * 100:5.1f}%" if hv is not None and hv == hv else "  n/a"
        last = row.get("Last")
        last_text = f"{float(last):>12,.2f}" if last is not None and last == last else "         n/a"
        print(
            f"{row['Symbol']:<10} {str(row['Source']):<10} {int(row['Rows']):>5} "
            f"{str(row.get('Start') or ''):<12} {str(row.get('End') or ''):<12} "
            f"{last_text} {hv_text:>7}"
        )
    print("-" * 78)
    print(f"Runtime cache : {service.cache_dir}")
    print(f"Bundled seed  : {service.seed_dir}")
    print(f"Total rows    : {int(coverage['Rows'].sum()):,}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    service = MarketDataService()

    if args.check:
        _print_inventory(service)
        return 0

    symbols = args.symbols or list(ASSETS)
    unknown = [s for s in symbols if s not in ASSETS]
    if unknown:
        print(f"Unknown symbols: {', '.join(unknown)}", file=sys.stderr)
        return 2

    mode = "the full universe" if not args.symbols or args.all else f"{len(symbols)} symbols"
    print("DerivLab data preprocessor")
    print(f"Cache: {DATA_DIR}")
    print(f"Seed : {SEED_DIR}")
    print(f"Downloading {args.years}y of daily data for {mode}...")
    print()

    report = service.refresh(symbols=symbols, years=args.years, retries=args.retries, pause=args.pause)

    for result in report.results:
        if result.ok:
            print(
                f"  [OK]   {result.symbol:<10} {result.rows:>5} rows  "
                f"{result.start.date()} -> {result.end.date()}"
            )
        else:
            print(f"  [FAIL] {result.symbol:<10} {result.message}")

    if args.output in {"seed", "both"}:
        promoted = service.promote_to_seed([r.symbol for r in report.succeeded])
        print()
        print(f"Promoted {len(promoted)} file(s) into the bundled seed: {SEED_DIR}")

    print()
    print(f"Summary: {report.summary()}")
    if report.failed:
        print(
            "Some symbols could not be refreshed. Existing cache/seed files were kept, "
            "so the application remains usable offline.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
