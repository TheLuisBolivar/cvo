"""
Google Gemini client wrapper. Same interface as ClaudeClient
(`call`, `call_json`, `call_stream`).

Uses the google-generativeai SDK.
"""

from __future__ import annotations

import os
from typing import Any, Iterator

from .client import _extract_json


DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"

DEFAULT_SYSTEM = "You are an expert CV optimization assistant."


class GeminiClient:
    """Thin wrapper around Google's Gemini SDK."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_GEMINI_MODEL):
        api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing GEMINI_API_KEY. Set it in .env or as an env var. "
                "Get one at https://aistudio.google.com/apikey"
            )
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise RuntimeError(
                "Missing dependency 'google-generativeai'. Install with: "
                "pip install google-generativeai"
            ) from e

        genai.configure(api_key=api_key)
        self._genai = genai
        self.model = model

    def _make_model(self, system: str | None):
        return self._genai.GenerativeModel(
            model_name=self.model,
            system_instruction=system or DEFAULT_SYSTEM,
        )

    def call(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> str:
        model = self._make_model(system)
        response = model.generate_content(
            user_prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        )
        return (getattr(response, "text", "") or "").strip()

    def call_json(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        model = self._make_model(system)
        try:
            response = model.generate_content(
                user_prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                    "response_mime_type": "application/json",
                },
            )
        except Exception:
            response = model.generate_content(
                user_prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
        raw = (getattr(response, "text", "") or "").strip()
        return _extract_json(raw)

    def call_stream(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> Iterator[str]:
        model = self._make_model(system)
        stream = model.generate_content(
            user_prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
            stream=True,
        )
        for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                yield text
