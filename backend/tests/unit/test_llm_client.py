"""Unit tests for Task A5: LLMClient Interface & Degradation Handling.

Tests (per A5 §13):
- Success: provider returns text → LLMResultOk.
- Timeout on first attempt only → single retry → LLMResultOk.
- Timeout on both attempts → LLMResultUnavailable(reason='timeout').
- Rate-limited → LLMResultUnavailable(reason='rate_limited').
- Generic provider error → LLMResultUnavailable(reason='provider_error').
- No exception propagates out of generate() under any simulated failure.
- LLMResultOk and LLMResultUnavailable match DOC3 §14 shapes exactly.
"""

import pytest
from unittest.mock import MagicMock

from app.llm.client import (
    LLMClient,
    LLMResultOk,
    LLMResultUnavailable,
    _MockProvider,
    _RateLimitError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client(provider_mock) -> LLMClient:
    """Construct an LLMClient with a controlled provider."""
    return LLMClient(provider=provider_mock)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

def test_generate_returns_ok_on_success():
    """Successful provider call → LLMResultOk with the returned text."""
    provider = MagicMock()
    provider.call.return_value = "SELECT n FROM graph"

    result = make_client(provider).generate(
        prompt="Translate to Cypher",
        context={"schema": "Person"},
    )

    assert isinstance(result, LLMResultOk)
    assert result.status == "ok"
    assert result.text == "SELECT n FROM graph"
    provider.call.assert_called_once()


def test_generate_passes_context_explicitly():
    """generate() must pass the supplied context to the provider (DOC3 §14)."""
    provider = MagicMock()
    provider.call.return_value = "text"
    ctx = {"key": "value", "schema": "..."}

    make_client(provider).generate(prompt="Q", context=ctx)

    _, kwargs_or_args = provider.call.call_args[0], provider.call.call_args
    # context is the second positional arg
    assert provider.call.call_args[0][1] == ctx


# ---------------------------------------------------------------------------
# Timeout — single retry
# ---------------------------------------------------------------------------

def test_generate_retries_once_on_timeout_then_succeeds():
    """Timeout on first attempt → single retry → returns ok if retry succeeds."""
    provider = MagicMock()
    provider.call.side_effect = [TimeoutError("first attempt"), "recovered text"]

    result = make_client(provider).generate(prompt="Q", context={})

    assert isinstance(result, LLMResultOk)
    assert result.text == "recovered text"
    assert provider.call.call_count == 2  # initial + 1 retry


def test_generate_returns_unavailable_after_two_timeouts():
    """Timeout on first AND retry attempt → unavailable/timeout."""
    provider = MagicMock()
    provider.call.side_effect = [TimeoutError("t1"), TimeoutError("t2")]

    result = make_client(provider).generate(prompt="Q", context={})

    assert isinstance(result, LLMResultUnavailable)
    assert result.status == "unavailable"
    assert result.reason == "timeout"
    assert provider.call.call_count == 2  # exactly one retry, no more


# ---------------------------------------------------------------------------
# Rate limited
# ---------------------------------------------------------------------------

def test_generate_returns_rate_limited():
    """Rate-limit response → unavailable/rate_limited (no retry)."""
    provider = MagicMock()
    provider.call.side_effect = _RateLimitError("429 Too Many Requests")

    result = make_client(provider).generate(prompt="Q", context={})

    assert isinstance(result, LLMResultUnavailable)
    assert result.reason == "rate_limited"
    provider.call.assert_called_once()  # no retry on rate limits


# ---------------------------------------------------------------------------
# Provider error
# ---------------------------------------------------------------------------

def test_generate_returns_provider_error_on_unexpected_exception():
    """Any non-timeout, non-rate-limit exception → unavailable/provider_error."""
    provider = MagicMock()
    provider.call.side_effect = ConnectionError("network failure")

    result = make_client(provider).generate(prompt="Q", context={})

    assert isinstance(result, LLMResultUnavailable)
    assert result.reason == "provider_error"


def test_generate_never_raises_on_any_failure():
    """generate() must never propagate an exception to the caller (DOC3 §14)."""
    provider = MagicMock()
    provider.call.side_effect = RuntimeError("catastrophic failure")

    # Must not raise — must return an LLMResult
    try:
        result = make_client(provider).generate(prompt="Q", context={})
    except Exception as exc:
        pytest.fail(f"generate() raised an exception when it must not: {exc}")

    assert isinstance(result, LLMResultUnavailable)


# ---------------------------------------------------------------------------
# Timeout option
# ---------------------------------------------------------------------------

def test_generate_passes_custom_timeout_to_provider():
    """options.timeout_ms is forwarded to the provider call."""
    provider = MagicMock()
    provider.call.return_value = "ok text"

    make_client(provider).generate(
        prompt="Q",
        context={},
        options={"timeout_ms": 5000},
    )

    # Third positional arg is timeout_ms
    assert provider.call.call_args[0][2] == 5000


def test_generate_uses_default_timeout_when_options_omitted():
    """When options is None, the default timeout is passed to the provider."""
    from app.llm.client import _DEFAULT_TIMEOUT_MS

    provider = MagicMock()
    provider.call.return_value = "ok"

    make_client(provider).generate(prompt="Q", context={})

    assert provider.call.call_args[0][2] == _DEFAULT_TIMEOUT_MS


# ---------------------------------------------------------------------------
# Mock provider (offline default)
# ---------------------------------------------------------------------------

def test_mock_provider_returns_ok():
    """_MockProvider always returns a non-empty string (offline/test default)."""
    mp = _MockProvider()
    text = mp.call("some prompt", {"ctx": 1}, 5000)
    assert isinstance(text, str)
    assert len(text) > 0


def test_llm_client_uses_mock_provider_by_default_in_dev(monkeypatch):
    """With LLM_PROVIDER='mock' in Config, LLMClient resolves to _MockProvider."""
    import os
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    # Clear cached config so monkeypatched env is picked up
    from app.config import get_config
    get_config.cache_clear()

    client = LLMClient()  # no explicit provider → uses config
    result = client.generate(prompt="test", context={})

    assert isinstance(result, LLMResultOk)
    assert result.status == "ok"

    # Restore
    get_config.cache_clear()


# ---------------------------------------------------------------------------
# DOC3 §14 result shapes
# ---------------------------------------------------------------------------

def test_llm_result_ok_shape():
    r = LLMResultOk(text="some answer")
    assert r.status == "ok"
    assert r.text == "some answer"


def test_llm_result_unavailable_shapes():
    for reason in ("timeout", "provider_error", "rate_limited"):
        r = LLMResultUnavailable(reason=reason)
        assert r.status == "unavailable"
        assert r.reason == reason
