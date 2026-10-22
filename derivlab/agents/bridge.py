"""Async bridge between Backtrader events and the autonomous agent layer.

The Backtrader strategy/controller emits a small market-shock payload whenever a
short strike is breached or an option is assigned. If an event loop is supplied,
the bridge schedules ``process_market_shock`` without blocking the simulation;
otherwise the event is retained in-process for the UI and the report builder.

This is deliberately transport-agnostic. A production deployment can replace the
in-memory queue with Kafka, Redis Streams, or an agent orchestration framework.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

LOGGER = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class MarketEvent:
    """A normalized market shock emitted by the simulation engine."""

    event: str
    date: str
    spot: float
    strike: float
    message: str
    severity: str = "medium"
    agent: str = ""
    strategy: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "date": self.date,
            "spot": self.spot,
            "strike": self.strike,
            "message": self.message,
            "severity": self.severity,
            "agent": self.agent,
            "strategy": self.strategy,
        }


class AIAgentBridge:
    """Collects Backtrader events and optionally dispatches them asynchronously."""

    def __init__(self, event_loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.loop = event_loop
        self._events: list[MarketEvent] = []
        self._processed: list[MarketEvent] = []
        self._lock = threading.Lock()

    # -- event emission ----------------------------------------------------
    def emit(self, context: dict[str, Any]) -> MarketEvent:
        """Record an event immediately and, if possible, schedule async work."""

        event = self._coerce(context)
        with self._lock:
            self._events.append(event)
        if self.loop is not None and self.loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self.process_market_shock(context), self.loop)
            except Exception as exc:  # pragma: no cover - defensive thread boundary
                LOGGER.debug("Could not schedule AI market shock: %s", exc)
        return event

    async def process_market_shock(self, context: dict[str, Any]) -> MarketEvent:
        """Async hook for LLM reasoning / UI fan-out (SRS 5.2 template)."""

        event = self._coerce(context)
        with self._lock:
            self._processed.append(event)
        await asyncio.sleep(0)
        return event

    # -- retrieval ---------------------------------------------------------
    def drain(self) -> list[MarketEvent]:
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events

    @property
    def events(self) -> list[MarketEvent]:
        with self._lock:
            return list(self._events)

    @property
    def processed_events(self) -> list[MarketEvent]:
        with self._lock:
            return list(self._processed)

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._events)

    # -- coercion ----------------------------------------------------------
    @staticmethod
    def _coerce(context: dict[str, Any]) -> MarketEvent:
        payload = dict(context) if isinstance(context, dict) else {"message": str(context)}
        raw_date = (
            payload.get("date")
            or payload.get("as_of")
            or datetime.now(timezone.utc).date().isoformat()
        )
        if isinstance(raw_date, (date, datetime)):
            date_text = raw_date.isoformat()
        else:
            date_text = str(raw_date)
        return MarketEvent(
            event=str(payload.get("event", "MARKET_SHOCK")),
            date=date_text,
            spot=_safe_float(payload.get("spot_price", payload.get("spot", 0.0))),
            strike=_safe_float(payload.get("strike_price", payload.get("strike", 0.0))),
            message=str(payload.get("message", "")),
            severity=str(payload.get("severity", "medium")),
            agent=str(payload.get("agent", "")),
            strategy=str(payload.get("strategy", "")),
            payload=payload,
        )
