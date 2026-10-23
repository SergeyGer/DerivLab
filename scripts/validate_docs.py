"""Validate docs links, anchors, images, snippets, versions, and ownership.

The script is deliberately standard-library only so the Docs workflow can run it
before installing the application dependencies.
"""

from __future__ import annotations

import ast
import re
import struct
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
ADR_REQUIRED = ("## Status", "## Context", "## Decision", "## Consequences")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_LINK_RE = re.compile(r'(?:src|href)="([^"]+)"')
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
PYTHON_BLOCK_RE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
SKIP_SCHEMES = {"http", "https", "mailto", "tel", "data"}
VERSION_RE = re.compile(r'APP_VERSION\s*=\s*"([^"]+)"')


def _iter_docs() -> list[Path]:
    docs = [ROOT / "README.md"]
    docs.extend(sorted((ROOT / "docs").rglob("*.md")))
    return [path for path in docs if path.is_file()]


def _anchors(path: Path) -> set[str]:
    """Approximate GitHub heading anchors, including emoji/punctuation variants."""

    text = path.read_text(encoding="utf-8")
    anchors: set[str] = set()
    for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, re.MULTILINE):
        raw = match.group(2)
        raw = re.sub(r"<[^>]+>", "", raw)
        raw = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)
        raw = raw.replace("`", "")
        base = re.sub(r"[^\w\s-]", "", raw.lower(), flags=re.UNICODE)
        if not base.strip():
            continue
        trimmed = base.strip().replace(" ", "-")
        leading = base.replace(" ", "-")
        anchors.update({trimmed, leading, re.sub(r"-+", "-", trimmed)})
    return anchors


def _check_local_links(path: Path, errors: list[str]) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    checked = 0
    anchors_checked = 0
    for raw in LINK_RE.findall(text) + HTML_LINK_RE.findall(text):
        target = raw.strip().strip("<>")
        if not target:
            continue
        if target.startswith("#"):
            fragment = unquote(target[1:])
            checked += 1
            anchors_checked += 1
            if fragment and fragment not in _anchors(path):
                errors.append(f"{path.relative_to(ROOT)}: missing anchor: {target}")
            continue
        parsed = urlparse(target)
        if parsed.scheme.lower() in SKIP_SCHEMES or parsed.scheme:
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
            continue
        fragment = unquote(parsed.fragment)
        if fragment and resolved.suffix.lower() in {".md", ".markdown"}:
            anchors_checked += 1
            if fragment not in _anchors(resolved):
                errors.append(f"{path.relative_to(ROOT)}: missing anchor: {target}")
    return checked, anchors_checked


def _check_images(path: Path, errors: list[str]) -> int:
    text = path.read_text(encoding="utf-8")
    count = 0
    for alt, _target in MD_IMAGE_RE.findall(text):
        count += 1
        if not alt.strip():
            errors.append(f"{path.relative_to(ROOT)}: Markdown image without alt text")
    for tag in HTML_IMAGE_RE.findall(text):
        count += 1
        match = re.search(r'\balt="([^"]*)"', tag, re.IGNORECASE)
        if not match or not match.group(1).strip():
            errors.append(f"{path.relative_to(ROOT)}: HTML image without alt text")
    return count


def _check_python_snippets(path: Path, errors: list[str]) -> int:
    text = path.read_text(encoding="utf-8")
    count = 0
    for block in PYTHON_BLOCK_RE.findall(text):
        count += 1
        try:
            ast.parse(block)
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid Python snippet: {exc}")
    return count


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


def _check_versioned_docs(errors: list[str]) -> str:
    config = (ROOT / "derivlab" / "config.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(config)
    if not match:
        errors.append("derivlab/config.py: APP_VERSION not found")
        return ""
    version = match.group(1)
    compatibility = ROOT / "docs" / "COMPATIBILITY.md"
    if not compatibility.exists():
        errors.append("docs/COMPATIBILITY.md is missing")
    else:
        text = compatibility.read_text(encoding="utf-8")
        if f"**Current release:** {version}" not in text:
            errors.append(f"docs/COMPATIBILITY.md: current release is not {version}")
        if "**Last verified:**" not in text:
            errors.append("docs/COMPATIBILITY.md: missing Last verified date")

    versions_dir = ROOT / "docs" / "versions"
    index = versions_dir / "README.md"
    if not index.exists():
        errors.append("docs/versions/README.md is missing")
        return version
    index_text = index.read_text(encoding="utf-8")
    snapshots = sorted(versions_dir.glob("v*.md"))
    if not snapshots:
        errors.append("docs/versions: no snapshots found")
    for snapshot in snapshots:
        if snapshot.name not in index_text:
            errors.append(f"{snapshot.relative_to(ROOT)}: not linked from versions index")
    expected = versions_dir / f"v{version}.md"
    if not expected.exists():
        errors.append(f"current version snapshot missing: {expected.relative_to(ROOT)}")
    return version


def _check_governance(errors: list[str]) -> None:
    for relative in (
        "docs/OWNERS.md",
        ".github/CODEOWNERS",
        ".github/ISSUE_TEMPLATE/docs-feedback.yml",
    ):
        if not (ROOT / relative).exists():
            errors.append(f"missing documentation governance file: {relative}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "## Start here" not in readme:
        errors.append("README.md: missing Start here router")
    if "docs-feedback.yml" not in readme:
        errors.append("README.md: missing docs feedback link")


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
    link_count = 0
    anchor_count = 0
    image_count = 0
    snippet_count = 0
    for path in _iter_docs():
        links, anchors = _check_local_links(path, errors)
        link_count += links
        anchor_count += anchors
        image_count += _check_images(path, errors)
        snippet_count += _check_python_snippets(path, errors)
    adrs = _check_adrs(errors)
    version = _check_versioned_docs(errors)
    _check_governance(errors)
    _check_assets(errors)

    if errors:
        print("Documentation validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print(
        f"Documentation OK: {link_count} links ({anchor_count} anchors), "
        f"{image_count} images, {snippet_count} Python snippets, "
        f"{adrs} ADRs, version {version}, governance, assets."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
