"""
Anthropic / Claude client wrapper.
Centralizes API calls, error handling, JSON extraction, and streaming.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterator

from anthropic import Anthropic


# Default model. Override with the --model flag in the CLI.
# Reasonable options:
#   - claude-opus-4-7        (highest quality, most expensive)
#   - claude-sonnet-4-6      (best quality/cost balance, recommended)
#   - claude-haiku-4-5       (fastest, cheapest)
DEFAULT_MODEL = "claude-sonnet-4-6"

DEFAULT_SYSTEM = "You are an expert CV optimization assistant."


class ClaudeClient:
    """Thin wrapper around the Anthropic SDK."""

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Missing ANTHROPIC_API_KEY. Set it in .env or as an env var."
            )
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def call(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> str:
        """Single-shot call. Returns the response text."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or DEFAULT_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()

    def call_json(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Call expecting a JSON response. Strips markdown fences if present."""
        raw = self.call(user_prompt, system=system, max_tokens=max_tokens, temperature=temperature)
        return _extract_json(raw)

    def call_stream(
        self,
        user_prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> Iterator[str]:
        """Stream the response as text deltas. Use for live CLI display."""
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or DEFAULT_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text


def _extract_json(text: str) -> dict[str, Any]:
    """
    Robust JSON extraction: handles ```json fences, preambles, and partial garbage
    around the actual JSON object.
    """
    # 1) Direct attempt
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2) Strip ```json ... ``` fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # 3) Find first balanced { ... } block
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(
        "Could not extract valid JSON from the model response. "
        "Raw response:\n" + text[:500]
    )
