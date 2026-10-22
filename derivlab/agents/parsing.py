"""Tolerant JSON extraction for model responses.

LLMs routinely wrap JSON in Markdown fences or add a short sentence before the
payload. These helpers never raise; callers receive ``None`` and fall back to the
deterministic local agent.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def strip_code_fences(text: str) -> str:
    if not text:
        return ""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Find and parse the first JSON object in a model response."""

    cleaned = strip_code_fences(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def extract_json_array(text: str) -> list[Any] | None:
    """Find and parse the first JSON array in a model response."""

    cleaned = strip_code_fences(text)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, list) else None
