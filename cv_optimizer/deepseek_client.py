"""
DeepSeek client. Uses the openai SDK pointed at DeepSeek's endpoint
(DeepSeek's API is OpenAI-compatible).

Exposes the same interface as ClaudeClient (`call`, `call_json`, `call_stream`)
so the rest of the codebase can use either provider interchangeably.

DeepSeek V4 models (released 2026-04-24):
    - deepseek-v4-flash   → 284B total / 13B active params, 1M context, fast and cheap (DEFAULT)
    - deepseek-v4-pro     → top-tier quality, 1M context
    - deepseek-chat       → legacy V3, deprecated 2026-07-24
    - deepseek-reasoner   → legacy R1, deprecated 2026-07-24

Both V4 models support thinking / non-thinking modes and 1M context.
"""

from __future__ import annotations

import os
from typing import Any, Iterator

from openai import OpenAI

from .client import _extract_json


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

DEFAULT_SYSTEM = "You are an expert CV optimization assistant."


class DeepSeekClient:
    """Thin wrapper around the DeepSeek API (via the openai SDK)."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_DEEPSEEK_MODEL):
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing DEEPSEEK_API_KEY. Set it in .env or as an env var. "
                "Get one at https://platform.deepseek.com/api_keys"
            )
        self.client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        self.model = model

    def _build_messages(self, user_prompt: str, system: str | None) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": system or DEFAULT_SYSTEM}]
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def call(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> str:
        """Single-shot call. Returns the response text."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self._build_messages(user_prompt, system),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()

    def call_json(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """
        Call expecting a JSON response. Uses DeepSeek's native JSON mode when
        available; falls back to tolerant parsing in any case.
        """
        messages = self._build_messages(user_prompt, system)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except Exception:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        raw = (response.choices[0].message.content or "").strip()
        return _extract_json(raw)

    def call_stream(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> Iterator[str]:
        """Stream the response as text deltas. Use for live CLI display."""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=self._build_messages(user_prompt, system),
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            try:
                delta_obj = chunk.choices[0].delta
            except (IndexError, AttributeError):
                continue
            # Only yield the visible answer text. Reasoning models also
            # send `reasoning_content`, but mixing it into the buffer
            # contaminates JSON parsing — the real answer is in `content`.
            content = getattr(delta_obj, "content", None)
            if content:
                yield content
