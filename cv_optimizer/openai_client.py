"""
OpenAI / ChatGPT client wrapper. Same interface as ClaudeClient and DeepSeekClient
(`call`, `call_json`, `call_stream`).
"""

from __future__ import annotations

import os
from typing import Any, Iterator

from openai import OpenAI

from .client import _extract_json


DEFAULT_OPENAI_MODEL = "gpt-4o"

DEFAULT_SYSTEM = "You are an expert CV optimization assistant."


class OpenAIClient:
    """Thin wrapper around the OpenAI SDK."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_OPENAI_MODEL):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing OPENAI_API_KEY. Set it in .env or as an env var. "
                "Get one at https://platform.openai.com/api-keys"
            )
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def _build_messages(self, user_prompt: str, system: str | None) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system or DEFAULT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

    def call(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> str:
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
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=self._build_messages(user_prompt, system),
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
            except (IndexError, AttributeError):
                delta = None
            if delta:
                yield delta
