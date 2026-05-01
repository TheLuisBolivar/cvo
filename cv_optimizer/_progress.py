"""
Progress-bar helper for streaming LLM calls.

The OpenAI-style streaming APIs don't expose "X% done", so we estimate
progress from the number of characters accumulated against max_tokens
(assuming ~4 chars per token). Capped at 95% until the stream ends, then
snapped to 100% so the bar finishes cleanly.

Use as:
    raw = stream_with_progress(client.call_stream(...), "Parsing CV", max_tokens)
    cv_dict = _extract_json(raw)

or via the JSON / text helpers for the common case.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Iterator

from .client import _extract_json


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _c(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _supports_color() else s


# Avg English chars per token. 4 is the canonical rule of thumb.
_CHARS_PER_TOKEN = 4.0


class ProgressBar:
    """Single-line in-place progress bar with a 0–100% indicator."""

    def __init__(self, label: str, max_tokens: int, width: int = 28):
        self.label = label
        self.max_tokens = max(max_tokens, 1)
        self.width = width
        self.chars = 0
        self.started = time.time()
        self._last_pct = -1.0
        self._enabled = sys.stdout.isatty()

    def update(self, chunk_chars: int) -> None:
        self.chars += chunk_chars
        approx_tokens = self.chars / _CHARS_PER_TOKEN
        pct = min(95.0, (approx_tokens / self.max_tokens) * 100.0)
        # Throttle redraws — only repaint on >=0.5% change to avoid flicker.
        if pct - self._last_pct >= 0.5:
            self._render(pct)
            self._last_pct = pct

    def finish(self, success: bool = True) -> None:
        elapsed = time.time() - self.started
        if success:
            self._render(100.0, final=True)
        if self._enabled:
            sys.stdout.write(_c(f"  ({elapsed:.1f}s)\n", "2;37"))
        else:
            sys.stdout.write(f"  done in {elapsed:.1f}s\n")
        sys.stdout.flush()

    def _render(self, pct: float, final: bool = False) -> None:
        if not self._enabled:
            # No TTY — print one dot per ~5% advanced, no in-place.
            return
        filled = round(pct / 100.0 * self.width)
        bar = "█" * filled + "░" * (self.width - filled)
        # Color: red <50, yellow <75, green ≥75.
        if pct >= 75:
            colored = _c(bar, "32")  # green
        elif pct >= 50:
            colored = _c(bar, "33")  # yellow
        else:
            colored = _c(bar, "1;35")  # magenta
        line = f"\r  {self.label:<22}  {colored}  {pct:5.1f}%"
        sys.stdout.write(line)
        sys.stdout.flush()


def stream_with_progress(
    stream: Iterator[str],
    label: str,
    max_tokens: int,
) -> str:
    """Consume a stream of text deltas, render a progress bar, return all text."""
    bar = ProgressBar(label, max_tokens)
    buf: list[str] = []
    success = True
    try:
        for chunk in stream:
            buf.append(chunk)
            bar.update(len(chunk))
    except Exception:
        success = False
        bar.finish(success=False)
        raise
    bar.finish(success=success)
    return "".join(buf)


def stream_json(
    client: Any,
    prompt: str,
    system: str,
    max_tokens: int,
    label: str,
    temperature: float = 0.2,
    retry_on_truncation: bool = True,
    max_retry_tokens: int = 32000,
) -> dict[str, Any]:
    """
    Stream a response, parse it as JSON, return the dict.

    If the response can't be parsed (typically because the model hit
    `max_tokens` and got cut mid-JSON), automatically retry once with
    double the budget, capped at `max_retry_tokens`. The user sees a
    `⚠ retrying…` line and a fresh progress bar for the retry.
    """
    raw = stream_with_progress(
        client.call_stream(prompt, system=system, max_tokens=max_tokens, temperature=temperature),
        label,
        max_tokens,
    )
    try:
        return _extract_json(raw)
    except Exception as e:
        if not retry_on_truncation or _looks_complete(raw):
            raise
        bigger = min(max_retry_tokens, max_tokens * 2)
        if bigger <= max_tokens:
            raise
        sys.stdout.write(_c(
            f"  ⚠ response looked truncated ({len(raw)} chars) — "
            f"retrying with max_tokens={bigger}\n",
            "33",
        ))
        sys.stdout.flush()
        raw2 = stream_with_progress(
            client.call_stream(prompt, system=system, max_tokens=bigger, temperature=temperature),
            f"{label} (retry)",
            bigger,
        )
        return _extract_json(raw2)


def _looks_complete(raw: str) -> bool:
    """Cheap heuristic: complete JSON starts with `{` and ends with `}`."""
    s = (raw or "").strip()
    if not s:
        return False
    # Strip code fences if any.
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rstrip("`").strip()
    return s.startswith("{") and s.endswith("}")


def stream_text(
    client: Any,
    prompt: str,
    system: str,
    max_tokens: int,
    label: str,
    temperature: float = 0.5,
) -> str:
    return stream_with_progress(
        client.call_stream(prompt, system=system, max_tokens=max_tokens, temperature=temperature),
        label,
        max_tokens,
    ).strip()
