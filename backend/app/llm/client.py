"""LLM Client Interface & Degradation Handling.

Task A5: Implements LLMClient.generate() per DOC3 §14 and DOC2 §12A.

Key guarantees:
- generate() NEVER raises an uncaught exception — always returns a typed LLMResult.
- Exactly one retry on timeout before returning status='unavailable'.
- The concrete provider (model, endpoint, credentials) is resolved entirely
  inside this module via config — no other module may reference provider-specific
  details (DOC3 §14 contract rule, A5 §17).
- Every call site must pass `context` explicitly — no implicit/global state.

LLMResult union (DOC3 §14):
  {status: 'ok',          text: str}
| {status: 'unavailable', reason: 'timeout' | 'provider_error' | 'rate_limited'}
"""

import logging
import time
from typing import Any, Dict, Literal, Optional, Protocol, Union

from pydantic import BaseModel

from app.config import get_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result types — exact mirror of DOC3 §14 LLMResult union
# ---------------------------------------------------------------------------

class LLMResultOk(BaseModel):
    status: Literal["ok"] = "ok"
    text: str


class LLMResultUnavailable(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    reason: Literal["timeout", "provider_error", "rate_limited"]


LLMResult = Union[LLMResultOk, LLMResultUnavailable]

# Default timeout when the caller does not specify one (milliseconds)
_DEFAULT_TIMEOUT_MS = 30_000


# ---------------------------------------------------------------------------
# Internal provider protocol — all provider implementations must conform.
# This keeps provider-specific imports isolated inside _load_provider().
# ---------------------------------------------------------------------------

class _LLMProvider(Protocol):
    def call(
        self,
        prompt: str,
        context: Any,
        timeout_ms: int,
    ) -> str:
        """Send a prompt+context to the provider; return the text response.

        Raises:
            TimeoutError: request exceeded timeout_ms.
            RateLimitError: provider returned a rate-limit response.
            Exception: any other provider-side failure.
        """
        ...


# ---------------------------------------------------------------------------
# Built-in providers
# ---------------------------------------------------------------------------

class _MockProvider:
    """Offline provider used for local/test runs (LLM_PROVIDER='mock').

    Returns a predictable, deterministic response so tests don't need a real API.
    """

    def call(self, prompt: str, context: Any, timeout_ms: int) -> str:
        logger.debug("MockProvider.call (prompt_len=%d)", len(prompt))
        return f"[mock response] prompt received ({len(prompt)} chars)"


class _OpenAIProvider:
    """OpenAI provider — resolved from config when LLM_PROVIDER='openai'.

    Imports openai lazily so it is not a hard dependency for offline runs.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model

    def call(self, prompt: str, context: Any, timeout_ms: int) -> str:
        try:
            import openai  # lazy import — optional dependency
        except ImportError as exc:
            raise RuntimeError(
                "openai package is not installed. "
                "Run: pip install openai"
            ) from exc

        client = openai.OpenAI(api_key=self._api_key, timeout=timeout_ms / 1000)
        messages = [
            {"role": "system", "content": str(context)},
            {"role": "user", "content": prompt},
        ]
        try:
            completion = client.chat.completions.create(
                model=self._model,
                messages=messages,
            )
            return completion.choices[0].message.content or ""
        except openai.RateLimitError as exc:
            raise _RateLimitError(str(exc)) from exc
        except openai.APITimeoutError as exc:
            raise TimeoutError(str(exc)) from exc


class _GeminiProvider:
    """Google Gemini provider — resolved from config when LLM_PROVIDER='gemini'.

    Imports google-generativeai lazily so it is not a hard dependency.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._api_key = api_key
        self._model = model

    def call(self, prompt: str, context: Any, timeout_ms: int) -> str:
        try:
            import google.generativeai as genai  # lazy import — optional dependency
        except ImportError as exc:
            raise RuntimeError(
                "google-generativeai package is not installed. "
                "Run: pip install google-generativeai"
            ) from exc

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(self._model)
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        response = model.generate_content(full_prompt)
        return response.text or ""


# Sentinel for rate-limit errors (avoids provider-specific exception types leaking out)
class _RateLimitError(Exception):
    pass


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def _load_provider() -> _LLMProvider:
    """Instantiate and return the concrete provider configured in Config.

    This is the ONLY place provider-specific details are referenced; no other
    module may reach through this boundary (DOC3 §14 contract rule).
    """
    cfg = get_config()
    provider_name = cfg.LLM_PROVIDER.lower()

    if provider_name == "mock":
        return _MockProvider()

    if provider_name == "openai":
        if not cfg.LLM_API_KEY:
            raise ValueError("LLM_API_KEY must be set when LLM_PROVIDER='openai'")
        return _OpenAIProvider(api_key=cfg.LLM_API_KEY)

    if provider_name == "gemini":
        if not cfg.LLM_API_KEY:
            raise ValueError("LLM_API_KEY must be set when LLM_PROVIDER='gemini'")
        return _GeminiProvider(api_key=cfg.LLM_API_KEY)

    raise ValueError(
        f"Unknown LLM_PROVIDER '{cfg.LLM_PROVIDER}'. "
        "Supported values: 'mock', 'openai', 'gemini'."
    )


# ---------------------------------------------------------------------------
# LLMClient — the public interface (DOC3 §14)
# ---------------------------------------------------------------------------

class LLMClient:
    """Provider-agnostic LLM client.

    Usage:
        client = LLMClient()
        result = client.generate(
            prompt="Translate to Cypher: ...",
            context={"schema": "..."},
            options={"timeout_ms": 15000},
        )
        if result.status == "ok":
            cypher = result.text
        else:
            # handle degradation per DOC2 §12A
            ...

    Callers MUST treat status='unavailable' as a typed failure (never retry
    indefinitely, never substitute fabricated text — DOC3 §14 contract rule).
    """

    def __init__(self, provider: Optional[_LLMProvider] = None) -> None:
        """
        Args:
            provider: Optional override for testing. When None, the provider is
                      resolved from Config via _load_provider() on first call.
        """
        self._provider = provider
        self._resolved_provider: Optional[_LLMProvider] = None

    def _get_provider(self) -> _LLMProvider:
        if self._provider is not None:
            return self._provider
        if self._resolved_provider is None:
            self._resolved_provider = _load_provider()
        return self._resolved_provider

    def generate(
        self,
        prompt: str,
        context: Any,
        options: Optional[Dict[str, Any]] = None,
    ) -> LLMResult:
        """Send a prompt to the configured LLM provider and return a typed result.

        DOC3 §14 contract guarantees:
        - Never raises an uncaught exception — always returns LLMResult.
        - Exactly one retry on TimeoutError before returning unavailable/timeout.
        - provider_error on any non-timeout, non-rate-limit failure.
        - rate_limited when the provider returns a rate-limit response.
        - Every call site must supply `context` explicitly (not None by default
          in practice — callers pass their structured context object).

        Args:
            prompt:  The instruction/question string.
            context: Structured context passed to the provider as grounding data.
                     Must be supplied explicitly by every caller (DOC3 §14).
            options: Optional dict. Supported keys:
                       timeout_ms (int): per-attempt timeout in milliseconds.
        """
        timeout_ms = int((options or {}).get("timeout_ms", _DEFAULT_TIMEOUT_MS))
        provider = self._get_provider()

        for attempt in range(2):  # attempt 0 = first try, attempt 1 = single retry
            try:
                text = provider.call(prompt, context, timeout_ms)
                return LLMResultOk(text=text)

            except TimeoutError as exc:
                if attempt == 0:
                    logger.warning(
                        "LLMClient timeout on attempt %d, retrying once. error=%s",
                        attempt + 1, exc,
                    )
                    continue  # single retry
                logger.error("LLMClient timeout after retry. Returning unavailable.")
                return LLMResultUnavailable(reason="timeout")

            except _RateLimitError as exc:
                logger.warning("LLMClient rate limited: %s", exc)
                return LLMResultUnavailable(reason="rate_limited")

            except Exception as exc:  # noqa: BLE001
                logger.error("LLMClient provider error: %s", exc)
                return LLMResultUnavailable(reason="provider_error")

        # Should be unreachable (loop always returns), but satisfies type checker
        return LLMResultUnavailable(reason="provider_error")


# ---------------------------------------------------------------------------
# Module-level singleton for convenient import by Tracks B, F, G
# ---------------------------------------------------------------------------

def get_llm_client() -> LLMClient:
    """Return a default LLMClient using the provider from Config.

    Each caller may also instantiate LLMClient() directly if it needs to
    inject a custom provider (e.g., in tests).
    """
    return LLMClient()
