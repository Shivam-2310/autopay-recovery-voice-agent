"""Plug-and-play LLM factory.

Selects a LangChain chat model with tool-calling support based solely on
environment variables. Adding a new provider never requires touching
graph.py or agent.py.

Environment:
    LLM_PROVIDER        groq | gemini | deepseek | openai_compatible
    LLM_MODEL            optional override (provider default used if blank)
    LLM_API_KEY          generic key (or use provider-specific vars below)
    GROQ_API_KEY         Groq-specific key
    GEMINI_API_KEY       Gemini-specific key
    DEEPSEEK_API_KEY     DeepSeek-specific key
    LLM_BASE_URL         required only for openai_compatible
    LLM_FALLBACKS        comma-separated fallback providers (e.g. deepseek,gemini)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# ── Provider presets ──────────────────────────────────────────────────────────

_PRESETS: dict[str, dict[str, Any]] = {
    "groq": {
        "class": "langchain_openai.ChatOpenAI",
        "default_model": "openai/gpt-oss-120b",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
    },
    "deepseek": {
        "class": "langchain_openai.ChatOpenAI",
        "default_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "gemini": {
        "class": "langchain_google_genai.ChatGoogleGenerativeAI",
        "default_model": "gemini-2.0-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "openai_compatible": {
        "class": "langchain_openai.ChatOpenAI",
        "default_model": None,  # must be provided by user
        "key_env": "LLM_API_KEY",
    },
}


def _resolve_key(provider: str, preset: dict[str, Any]) -> str:
    """Resolve the API key from env, checking provider-specific then generic."""
    key = os.environ.get(preset["key_env"], "") or os.environ.get("LLM_API_KEY", "")
    if not key:
        raise EnvironmentError(
            f"No API key found for provider '{provider}'. "
            f"Set {preset['key_env']} or LLM_API_KEY."
        )
    return key


def _build_openai_compatible(
    model: str,
    api_key: str,
    base_url: str,
    **kwargs: Any,
) -> BaseChatModel:
    """Construct a ChatOpenAI instance pointing at an OpenAI-compatible endpoint."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        api_key=api_key,  # type: ignore[arg-type]
        base_url=base_url,
        temperature=0.3,
        streaming=True,
        **kwargs,
    )


def _build_gemini(model: str, api_key: str, **kwargs: Any) -> BaseChatModel:
    """Construct a ChatGoogleGenerativeAI instance."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,  # type: ignore[arg-type]
        temperature=0.3,
        streaming=True,
        convert_system_message_to_human=True,
        **kwargs,
    )


# ── Public API ────────────────────────────────────────────────────────────────


def get_llm(provider: str | None = None) -> BaseChatModel:
    """Return a LangChain chat model with tool-calling, driven by env vars.

    Args:
        provider: Override for LLM_PROVIDER env var (used internally for fallbacks).

    Returns:
        A BaseChatModel ready for .bind_tools() and streaming.
    """
    provider = (provider or os.environ.get("LLM_PROVIDER", "")).strip().lower()
    if not provider:
        raise EnvironmentError("LLM_PROVIDER env var is not set.")

    preset = _PRESETS.get(provider)
    if preset is None:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider}'. "
            f"Choose from: {', '.join(_PRESETS.keys())}"
        )

    model = os.environ.get("LLM_MODEL", "").strip() or preset["default_model"]
    if not model:
        raise EnvironmentError(
            f"LLM_MODEL must be set for provider '{provider}' (no default)."
        )

    api_key = _resolve_key(provider, preset)

    logger.info("Initializing LLM: provider=%s model=%s", provider, model)

    if provider == "gemini":
        return _build_gemini(model=model, api_key=api_key)

    # groq, deepseek, or openai_compatible
    base_url = preset.get("base_url") or os.environ.get("LLM_BASE_URL", "")
    if provider == "openai_compatible" and not base_url:
        raise EnvironmentError("LLM_BASE_URL is required for openai_compatible.")

    return _build_openai_compatible(model=model, api_key=api_key, base_url=base_url)


def get_llm_with_fallbacks() -> BaseChatModel:
    """Wrap the primary LLM with fallback providers from LLM_FALLBACKS env.

    LLM_FALLBACKS is a comma-separated list of provider names.
    On timeout, 5xx, or malformed response the next provider is tried.
    """
    primary = get_llm()
    fallback_str = os.environ.get("LLM_FALLBACKS", "").strip()
    if not fallback_str:
        return primary

    fallbacks: list[BaseChatModel] = []
    for fb_provider in fallback_str.split(","):
        fb_provider = fb_provider.strip()
        if not fb_provider:
            continue
        try:
            fallbacks.append(get_llm(provider=fb_provider))
            logger.info("Registered LLM fallback: %s", fb_provider)
        except Exception:
            logger.warning("Failed to init fallback provider '%s', skipping", fb_provider, exc_info=True)

    if not fallbacks:
        return primary

    return primary.with_fallbacks(fallbacks)  # type: ignore[return-value]
