"""Validate documentation links, ADRs, versioning, and presentation assets.

This script is intentionally standard-library only so it can run in CI before
dependencies are installed.
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
ADR_REQUIRED = ("## Status", "## Context", "## Decision", "## Consequences")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_LINK_RE = re.compile(r'(?:src|href)="([^"]+)"')
SKIP_SCHEMES = {"http", "https", "mailto", "tel", "data"}


def _iter_docs() -> list[Path]:
    docs = [ROOT / "README.md"]
    docs.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in docs if path.is_file()]


def _check_local_links(path: Path, errors: list[str]) -> int:
    text = path.read_text(encoding="utf-8")
    checked = 0
    for raw in LINK_RE.findall(text) + HTML_LINK_RE.findall(text):
        target = raw.strip()
        if not target or target.startswith("#"):
            continue
        parsed = urlparse(target)
        if parsed.scheme.lower() in SKIP_SCHEMES:
            continue
        if parsed.scheme:
            continue
        local = unquote(parsed.path)
        if not local:
            continue
        resolved = (path.parent / local).resolve()
        checked += 1
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{path.relative_to(ROOT)}: link escapes repository: {target}")
            continue
        if not resolved.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing local link: {target}")
    return checked


def _check_adrs(errors: list[str]) -> int:
    adr_dir = ROOT / "docs" / "adr"
    files = sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    index = (adr_dir / "README.md").read_text(encoding="utf-8")
    for path in files:
        text = path.read_text(encoding="utf-8")
        for heading in ADR_REQUIRED:
            if heading not in text:
                errors.append(f"{path.relative_to(ROOT)}: missing {heading}")
        if path.name not in index:
            errors.append(f"{path.relative_to(ROOT)}: not linked from docs/adr/README.md")
    if not files:
        errors.append("docs/adr: no ADR files found")
    return len(files)


def _check_versioning(errors: list[str]) -> None:
    versioning = ROOT / "docs" / "VERSIONING.md"
    if not versioning.exists():
        errors.append("docs/VERSIONING.md is missing")
        return
    text = versioning.read_text(encoding="utf-8")
    for phrase in ("Semantic Versioning", "MAJOR.MINOR.PATCH", "Release checklist"):
        if phrase not in text:
            errors.append(f"docs/VERSIONING.md: missing {phrase!r}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if "## [1.2.0]" not in changelog:
        errors.append("CHANGELOG.md: missing the 1.2.0 release entry")


def _check_assets(errors: list[str]) -> None:
    coverage_badge = ROOT / "docs" / "badges" / "coverage.svg"
    if not coverage_badge.exists():
        errors.append("docs/badges/coverage.svg is missing")
    elif 'aria-label="coverage:' not in coverage_badge.read_text(encoding="utf-8"):
        errors.append("docs/badges/coverage.svg is not a coverage badge")

    social = ROOT / "docs" / "social-preview.png"
    if not social.exists():
        errors.append("docs/social-preview.png is missing")
        return
    header = social.read_bytes()[:24]
    if not header.startswith(b"\x89PNG\r\n\x1a\n"):
        errors.append("docs/social-preview.png is not a PNG")
        return
    width, height = struct.unpack(">II", header[16:24])
    if (width, height) != (1280, 640):
        errors.append(f"docs/social-preview.png is {width}x{height}, expected 1280x640")


def main() -> int:
    errors: list[str] = []
    checked = 0
    for path in _iter_docs():
        checked += _check_local_links(path, errors)
    adrs = _check_adrs(errors)
    _check_versioning(errors)
    _check_assets(errors)

    if errors:
        print("Documentation validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(f"Documentation OK: {checked} local links, {adrs} ADRs, versioning, assets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
