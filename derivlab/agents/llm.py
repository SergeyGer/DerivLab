"""LLM provider abstraction and model catalog.

DerivLab is fully functional without an API key: the deterministic local quant
models below run every screen. When an OpenAI-compatible or Anthropic endpoint is
configured, the same interfaces call a real LLM and the UI displays the exact
model names in use.

No provider SDK is required. The client uses ``requests`` so it works with
OpenAI, Azure OpenAI-compatible gateways, OpenRouter, Groq, vLLM, LM Studio,
Ollama, and Anthropic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)

LOCAL_DECISION_MODEL = "derivlab-local-quant-core-v1"
LOCAL_CRITIC_MODEL = "derivlab-local-critic-v1"
LOCAL_NEWS_MODEL = "derivlab-local-newswire-v1"

ROLE_DECISION = "decision"
ROLE_CRITIC = "critic"
ROLE_NEWS = "news"

PROVIDER_LABELS = {
    "local": "Offline deterministic",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "openai_compatible": "OpenAI-compatible",
    "ollama": "Ollama",
    "lmstudio": "LM Studio",
    "vllm": "vLLM",
}

NO_KEY_PROVIDERS = {"openai_compatible", "ollama", "lmstudio", "vllm"}

DEFAULT_OPENAI_MODELS = {
    ROLE_DECISION: "gpt-5-mini",
    ROLE_CRITIC: "gpt-5",
    ROLE_NEWS: "gpt-5-mini",
}
DEFAULT_ANTHROPIC_MODELS = {
    ROLE_DECISION: "claude-haiku-4-5",
    ROLE_CRITIC: "claude-sonnet-4-5",
    ROLE_NEWS: "claude-haiku-4-5",
}
DEFAULT_COMPATIBLE_MODELS = {
    ROLE_DECISION: "local-model",
    ROLE_CRITIC: "local-model",
    ROLE_NEWS: "local-model",
}


@dataclass(frozen=True)
class ModelRecommendation:
    """A model pairing recommendation shown in the UI and README."""

    role: str
    primary: str
    alternatives: tuple[str, ...]
    rationale: str


MODEL_RECOMMENDATIONS: tuple[ModelRecommendation, ...] = (
    ModelRecommendation(
        role="Critic / rival fund manager",
        primary="OpenAI GPT-5",
        alternatives=("Anthropic Claude Sonnet 4.5", "Google Gemini 2.5 Pro"),
        rationale=(
            "Best at multi-metric reasoning, nuanced risk critique, and following the strict "
            "three-section Markdown contract. Use the strongest reasoning model you can afford."
        ),
    ),
    ModelRecommendation(
        role="Fast news wire",
        primary="OpenAI GPT-5 mini",
        alternatives=("Anthropic Claude Haiku 4.5", "Google Gemini 2.5 Flash"),
        rationale=(
            "Headlines need speed and low cost more than deep reasoning. A mini/flash model "
            "keeps the wire snappy even when the user runs several cycles."
        ),
    ),
    ModelRecommendation(
        role="Autonomous trading decisions",
        primary="Deterministic local quant core",
        alternatives=("GPT-5 mini with JSON mode", "Claude Haiku 4.5", "Qwen3-32B"),
        rationale=(
            "Trading decisions should be reproducible and auditable. Keep the built-in policy "
            "as the default; enable LLM-directed decisions only when you want creative variety."
        ),
    ),
    ModelRecommendation(
        role="Private / offline deployment",
        primary="Qwen3-32B via vLLM or Ollama",
        alternatives=("Llama 3.3 70B", "Mistral Small 3"),
        rationale=(
            "Runs on your own hardware, keeps portfolio context private, and has no per-call "
            "cost. Quality is lower than frontier APIs but sufficient for commentary and news."
        ),
    ),
)


@dataclass(frozen=True)
class LLMSettings:
    """Configuration for the optional LLM layer.

    ``enabled`` is derived; if it is false the application never makes a network
    call and every agent uses the local deterministic models.
    """

    provider: str = "local"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    decision_model: str = LOCAL_DECISION_MODEL
    critic_model: str = LOCAL_CRITIC_MODEL
    news_model: str = LOCAL_NEWS_MODEL
    timeout: float = 25.0
    temperature: float = 0.55
    explicitly_configured: bool = False

    @property
    def enabled(self) -> bool:
        if self.provider not in PROVIDER_LABELS or self.provider == "local":
            return False
        if not self.base_url:
            return False
        if self.provider in {"openai", "anthropic"} and not self.api_key:
            return False
        if any(
            not model or model.startswith("derivlab-local-")
            for model in (self.decision_model, self.critic_model, self.news_model)
        ):
            return False
        return True

    @property
    def provider_label(self) -> str:
        return PROVIDER_LABELS.get(self.provider, self.provider)

    @property
    def mode_label(self) -> str:
        return "LLM CONNECTED" if self.enabled else "LOCAL QUANT CORE"

    def model_for(self, role: str) -> str:
        if role == ROLE_DECISION:
            return self.decision_model
        if role == ROLE_NEWS:
            return self.news_model
        return self.critic_model

    def local_model_for(self, role: str) -> str:
        if role == ROLE_DECISION:
            return LOCAL_DECISION_MODEL
        if role == ROLE_NEWS:
            return LOCAL_NEWS_MODEL
        return LOCAL_CRITIC_MODEL

    def active_model_for(self, role: str) -> str:
        return self.model_for(role) if self.enabled else self.local_model_for(role)

    def public_dict(self, use_llm_decisions: bool = True) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "provider_label": self.provider_label,
            "mode": self.mode_label,
            "decision_model": (
                self.model_for(ROLE_DECISION)
                if self.enabled and use_llm_decisions
                else LOCAL_DECISION_MODEL
            ),
            "critic_model": self.active_model_for(ROLE_CRITIC),
            "news_model": self.active_model_for(ROLE_NEWS),
            "base_url": self.base_url if self.enabled else "",
            "api_key_configured": bool(self.api_key),
        }

    @classmethod
    def local(cls) -> LLMSettings:
        return cls()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LLMSettings:
        values = env if env is not None else os.environ
        explicit_provider = str(values.get("DERIVLAB_LLM_PROVIDER", "")).strip().lower()
        generic_key = str(values.get("DERIVLAB_LLM_API_KEY", "")).strip()
        openai_key = str(values.get("OPENAI_API_KEY", "")).strip()
        anthropic_key = str(values.get("ANTHROPIC_API_KEY", "")).strip()
        base_url_env = str(values.get("DERIVLAB_LLM_BASE_URL", "")).strip()
        model_env = str(values.get("DERIVLAB_LLM_MODEL", "")).strip()

        if explicit_provider:
            provider = explicit_provider
        elif anthropic_key and not openai_key:
            provider = "anthropic"
        elif openai_key or generic_key:
            provider = "openai"
        elif base_url_env:
            provider = "openai_compatible"
        else:
            provider = "local"

        if provider not in PROVIDER_LABELS:
            provider = "local"

        if provider == "anthropic":
            api_key = generic_key or anthropic_key
            base_url = base_url_env or "https://api.anthropic.com"
            defaults = DEFAULT_ANTHROPIC_MODELS
        elif provider in {"openai"}:
            api_key = generic_key or openai_key
            base_url = base_url_env or "https://api.openai.com/v1"
            defaults = DEFAULT_OPENAI_MODELS
        elif provider in NO_KEY_PROVIDERS:
            api_key = generic_key or openai_key
            base_url = base_url_env or "http://127.0.0.1:11434/v1"
            defaults = DEFAULT_COMPATIBLE_MODELS
        else:
            api_key = ""
            base_url = ""
            defaults = {
                ROLE_DECISION: LOCAL_DECISION_MODEL,
                ROLE_CRITIC: LOCAL_CRITIC_MODEL,
                ROLE_NEWS: LOCAL_NEWS_MODEL,
            }

        decision_model = str(values.get("DERIVLAB_DECISION_MODEL", "") or model_env or defaults[ROLE_DECISION])
        critic_model = str(values.get("DERIVLAB_CRITIC_MODEL", "") or model_env or defaults[ROLE_CRITIC])
        news_model = str(values.get("DERIVLAB_NEWS_MODEL", "") or model_env or defaults[ROLE_NEWS])

        try:
            timeout = float(values.get("DERIVLAB_LLM_TIMEOUT", "25") or 25)
        except (TypeError, ValueError):
            timeout = 25.0
        timeout = max(3.0, min(timeout, 120.0))
        try:
            temperature = float(values.get("DERIVLAB_LLM_TEMPERATURE", "0.55") or 0.55)
        except (TypeError, ValueError):
            temperature = 0.55
        temperature = max(0.0, min(temperature, 1.5))

        explicitness = bool(
            explicit_provider
            or generic_key
            or openai_key
            or anthropic_key
            or base_url_env
            or model_env
            or any(
                values.get(key)
                for key in (
                    "DERIVLAB_DECISION_MODEL",
                    "DERIVLAB_CRITIC_MODEL",
                    "DERIVLAB_NEWS_MODEL",
                )
            )
        )
        return cls(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            decision_model=decision_model,
            critic_model=critic_model,
            news_model=news_model,
            timeout=timeout,
            temperature=temperature,
            explicitly_configured=explicitness,
        )


@dataclass
class LLMResult:
    """Normalized output from one model call."""

    text: str
    ok: bool
    model: str
    provider: str
    source: str
    error: str = ""
    latency_ms: int = 0

    @property
    def used_llm(self) -> bool:
        return bool(self.ok and self.source == "llm")

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "model": self.model,
            "provider": self.provider,
            "source": self.source,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


class LLMClient:
    """Small, defensive HTTP client for chat-completion style APIs.

    The client never raises to callers: every failure is returned as an
    ``LLMResult`` with ``ok=False`` so the caller can use the local fallback.
    """

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings.from_env()

    def generate(
        self,
        system: str,
        user: str,
        *,
        role: str = ROLE_CRITIC,
        max_tokens: int = 900,
    ) -> LLMResult:
        model = self.settings.model_for(role)
        started = time.perf_counter()
        if not self.settings.enabled:
            return LLMResult(
                text="",
                ok=False,
                model=self.settings.local_model_for(role),
                provider="local",
                source="local",
                error="LLM is not configured; the deterministic local model is active.",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            if self.settings.provider == "anthropic":
                text = self._anthropic_messages(system, user, model, max_tokens)
            else:
                text = self._openai_compatible(system, user, model, max_tokens)
        except requests.RequestException as exc:
            error = f"network error: {type(exc).__name__}: {str(exc)[:200]}"
            LOGGER.warning("LLM request failed: %s", error)
            return self._failure(role, model, error, started)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            error = f"response error: {type(exc).__name__}: {str(exc)[:200]}"
            LOGGER.warning("LLM response could not be parsed: %s", error)
            return self._failure(role, model, error, started)
        except Exception as exc:  # defensive: a model outage must never break the UI
            error = f"unexpected error: {type(exc).__name__}: {str(exc)[:200]}"
            LOGGER.warning("Unexpected LLM error: %s", error)
            return self._failure(role, model, error, started)

        if not text or not text.strip():
            return self._failure(role, model, "empty model response", started)
        return LLMResult(
            text=text.strip(),
            ok=True,
            model=model,
            provider=self.settings.provider,
            source="llm",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def generate_async(
        self,
        system: str,
        user: str,
        *,
        role: str = ROLE_CRITIC,
        max_tokens: int = 900,
    ) -> LLMResult:
        """Async wrapper used by the agent bridge and notebooks."""

        return await asyncio.to_thread(
            self.generate, system, user, role=role, max_tokens=max_tokens
        )

    # -- provider implementations -----------------------------------------
    def _failure(self, role: str, model: str, error: str, started: float) -> LLMResult:
        return LLMResult(
            text="",
            ok=False,
            model=self.settings.local_model_for(role),
            provider=self.settings.provider,
            source="local",
            error=error,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _openai_compatible(self, system: str, user: str, model: str, max_tokens: int) -> str:
        url = self._endpoint("chat/completions")
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.settings.temperature,
            "max_tokens": int(max_tokens),
        }
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.settings.timeout,
        )
        if response.status_code == 400 and "max_tokens" in response.text.lower():
            # Reasoning-model APIs replaced max_tokens with max_completion_tokens.
            payload.pop("max_tokens", None)
            payload["max_completion_tokens"] = int(max_tokens)
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.settings.timeout,
            )
        if response.status_code >= 400:
            raise ValueError(f"HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("no choices in response")
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        return str(content)

    def _anthropic_messages(self, system: str, user: str, model: str, max_tokens: int) -> str:
        url = self._endpoint("messages")
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.settings.api_key:
            headers["x-api-key"] = self.settings.api_key
        payload = {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": int(max_tokens),
            "temperature": self.settings.temperature,
        }
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.settings.timeout,
        )
        if response.status_code >= 400:
            raise ValueError(f"HTTP {response.status_code}: {response.text[:300]}")
        data = response.json()
        blocks = data.get("content") or []
        text = "".join(
            str(block.get("text", "")) for block in blocks if isinstance(block, dict)
        )
        if not text:
            raise ValueError("no content blocks in response")
        return text

    def _endpoint(self, suffix: str) -> str:
        base = (self.settings.base_url or "").rstrip("/")
        if base.endswith(suffix):
            return base
        if self.settings.provider == "anthropic":
            if base.endswith("/v1"):
                return f"{base}/{suffix}"
            return f"{base}/v1/{suffix}"
        return f"{base}/{suffix}"


def public_model_stack(settings: LLMSettings, use_llm_decisions: bool = True) -> list[dict[str, Any]]:
    """A UI-friendly list of the models currently in use."""

    active = settings.public_dict(use_llm_decisions=use_llm_decisions)
    return [
        {
            "role": "Autonomous decisions",
            "model": active["decision_model"],
            "provider": active["provider_label"],
            "mode": "LLM" if settings.enabled and use_llm_decisions else "Local",
        },
        {
            "role": "AlphaVanguard critic",
            "model": active["critic_model"],
            "provider": active["provider_label"],
            "mode": "LLM" if settings.enabled else "Local fallback",
        },
        {
            "role": "NewsWire headlines",
            "model": active["news_model"],
            "provider": active["provider_label"],
            "mode": "LLM" if settings.enabled else "Local fallback",
        },
    ]
