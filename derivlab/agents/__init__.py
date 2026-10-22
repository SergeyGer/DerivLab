"""Autonomous AI agent layer for DerivLab.

The public surface is intentionally small:

* :mod:`derivlab.agents.llm` - provider settings, model catalog, HTTP client.
* :mod:`derivlab.agents.personas` - rival desk personas and trading policies.
* :mod:`derivlab.agents.bridge` - async bridge from Backtrader events to agents.
* :mod:`derivlab.agents.commentary` - AlphaVanguard reports and cyberpunk news.
* :mod:`derivlab.agents.arena` - the four-desk AI Arena simulation.
"""

from __future__ import annotations

__all__ = [
    "AIAgentBridge",
    "ArenaResult",
    "LLMClient",
    "LLMSettings",
    "run_arena",
]

from .arena import ArenaResult, run_arena
from .bridge import AIAgentBridge
from .llm import LLMClient, LLMSettings
