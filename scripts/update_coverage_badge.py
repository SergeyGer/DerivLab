"""Generate the README coverage badge from coverage.py JSON data.

Usage:
    coverage json -o coverage.json
    python scripts/update_coverage_badge.py            # write the SVG
    python scripts/update_coverage_badge.py --check    # fail if stale
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "coverage.json"
DEFAULT_OUTPUT = ROOT / "docs" / "badges" / "coverage.svg"


def _color(percent: float) -> str:
    if percent >= 90:
        return "#4c1"
    if percent >= 80:
        return "#97ca00"
    if percent >= 70:
        return "#dfb317"
    if percent >= 60:
        return "#fe7d37"
    return "#e05d44"


def render(percent: float) -> str:
    value = f"{percent:.0f}%"
    color = _color(percent)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="164" height="20" role="img" aria-label="coverage: {value}">
  <title>coverage: {value}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="164" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="102" height="20" fill="#555"/>
    <rect x="102" width="62" height="20" fill="{color}"/>
    <rect width="164" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="51" y="15" fill="#010101" fill-opacity=".3">coverage</text>
    <text x="51" y="14">coverage</text>
    <text x="132" y="15" fill="#010101" fill-opacity=".3">{value}</text>
    <text x="132" y="14">{value}</text>
  </g>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail if the SVG is stale")
    args = parser.parse_args()

    if not args.json.exists():
        raise SystemExit(f"coverage data not found: {args.json}. Run pytest with --cov first.")
    payload = json.loads(args.json.read_text(encoding="utf-8"))
    percent = float(payload["totals"]["percent_covered"])
    svg = render(percent)

    if args.check:
        if not args.output.exists():
            raise SystemExit(f"coverage badge missing: {args.output}")
        current = args.output.read_text(encoding="utf-8")
        match = re.search(r"aria-label=\"coverage: ([0-9.]+)%\"", current)
        if not match:
            raise SystemExit("existing coverage badge has no readable percentage")
        if match.group(1) != f"{percent:.0f}":
            raise SystemExit(
                f"coverage badge is stale: {match.group(1)}% in SVG, {percent:.0f}% measured"
            )
        print(f"coverage badge is current: {percent:.0f}%")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(svg, encoding="utf-8")
    print(f"wrote {args.output} at {percent:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
