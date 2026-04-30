"""
Provider abstraction. The rest of the app talks to LLMs through a single
interface: any client with `call`, `call_json`, `call_stream`, plus a `model`
attribute and a `display_name`.

Four providers are supported:
    - claude    (Anthropic)
    - openai    (ChatGPT)
    - gemini    (Google)
    - deepseek

The active provider is selected via the CVO_PROVIDER env var (set by the
setup wizard) or the --provider CLI flag.
"""

from __future__ import annotations

import os
from typing import Any, Iterator, Protocol


# ──────────────────────────────────────────────────────────────────────
# Static provider metadata
# ──────────────────────────────────────────────────────────────────────
PROVIDERS: dict[str, dict[str, str]] = {
    "claude": {
        "display_name": "Claude (Anthropic)",
        "env_key":      "ANTHROPIC_API_KEY",
        "key_url":      "https://console.anthropic.com/settings/keys",
        "default_model": "claude-sonnet-4-6",
    },
    "openai": {
        "display_name": "ChatGPT (OpenAI)",
        "env_key":      "OPENAI_API_KEY",
        "key_url":      "https://platform.openai.com/api-keys",
        "default_model": "gpt-4o",
    },
    "gemini": {
        "display_name": "Gemini (Google)",
        "env_key":      "GEMINI_API_KEY",
        "key_url":      "https://aistudio.google.com/apikey",
        "default_model": "gemini-2.0-flash",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "env_key":      "DEEPSEEK_API_KEY",
        "key_url":      "https://platform.deepseek.com/api_keys",
        "default_model": "deepseek-v4-flash",
    },
}

PROVIDER_ORDER: list[str] = ["claude", "openai", "gemini", "deepseek"]


class LLMClient(Protocol):
    """Duck-typed interface every provider implementation must satisfy."""
    model: str
    def call(self, user_prompt: str, system: str | None = ..., max_tokens: int = ..., temperature: float = ...) -> str: ...
    def call_json(self, user_prompt: str, system: str | None = ..., max_tokens: int = ..., temperature: float = ...) -> dict[str, Any]: ...
    def call_stream(self, user_prompt: str, system: str | None = ..., max_tokens: int = ..., temperature: float = ...) -> Iterator[str]: ...


def provider_meta(provider: str) -> dict[str, str]:
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider: {provider!r}. "
            f"Choose one of: {', '.join(PROVIDER_ORDER)}"
        )
    return PROVIDERS[provider]


def resolve_active_provider(cli_choice: str | None = None) -> str:
    """
    Resolution order:
      1. Explicit --provider CLI flag.
      2. CVO_PROVIDER env var (set by the wizard or .env).
      3. Default to "claude".
    """
    if cli_choice:
        if cli_choice not in PROVIDERS:
            raise ValueError(
                f"Unknown provider {cli_choice!r}. "
                f"Choose one of: {', '.join(PROVIDER_ORDER)}"
            )
        return cli_choice
    env_choice = (os.getenv("CVO_PROVIDER") or "").strip().lower()
    if env_choice in PROVIDERS:
        return env_choice
    return "claude"


def make_client(provider: str, model: str | None = None) -> LLMClient:
    """
    Instantiate the correct client for the provider. The relevant API key
    must already be in the environment (loaded from .env or set manually).
    """
    meta = provider_meta(provider)
    chosen_model = model or meta["default_model"]

    if provider == "claude":
        from .client import ClaudeClient
        return ClaudeClient(model=chosen_model)
    if provider == "openai":
        from .openai_client import OpenAIClient
        return OpenAIClient(model=chosen_model)
    if provider == "gemini":
        from .gemini_client import GeminiClient
        return GeminiClient(model=chosen_model)
    if provider == "deepseek":
        from .deepseek_client import DeepSeekClient
        return DeepSeekClient(model=chosen_model)
    # unreachable thanks to provider_meta
    raise ValueError(provider)


def is_placeholder_key(value: str | None) -> bool:
    """
    True if `value` looks like a placeholder copied from .env.example
    (e.g. `sk-ant-...`, `sk-...`, `your-api-key-here`, `xxx`) rather than
    a real API key. Treat those as "not configured".
    """
    if not value:
        return True
    v = value.strip().strip('"').strip("'").lower()
    if not v:
        return True
    if "..." in v:
        return True
    placeholders = {
        "sk-...", "sk-ant-...", "your-api-key-here", "your_api_key",
        "changeme", "todo", "xxx", "xxxxx", "<your-key>",
    }
    if v in placeholders:
        return True
    if v.startswith("<") and v.endswith(">"):
        return True
    return False


def has_api_key(provider: str) -> bool:
    """True only if the env var holds a real-looking API key."""
    return not is_placeholder_key(os.getenv(provider_meta(provider)["env_key"]))
