"""
Analyzer: parses the job offer and returns the structured analysis that
the rest of the modules consume.

Provider-agnostic — accepts any LLMClient (Claude, OpenAI, Gemini, DeepSeek).
"""

from __future__ import annotations

from typing import Any

from .providers import LLMClient
from .prompts import ANALYZER_PROMPT, ANALYZER_SYSTEM


def analyze_offer(offer_text: str, client: LLMClient) -> dict[str, Any]:
    """Return the structured JSON analysis of the offer."""
    prompt = ANALYZER_PROMPT.format(offer=offer_text.strip())
    return client.call_json(prompt, system=ANALYZER_SYSTEM, max_tokens=3000)
