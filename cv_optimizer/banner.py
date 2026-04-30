"""
ASCII banner shown at the start of `cvo run` and after a successful
`cvo setup`. Pure cosmetic — no behavior depends on it.
"""

from __future__ import annotations

import os
import sys


_LETTERS = [
    r"  ██████  ██    ██  ██████  ",
    r" ██       ██    ██ ██    ██ ",
    r" ██       ██    ██ ██    ██ ",
    r" ██        ██  ██  ██    ██ ",
    r"  ██████    ████    ██████  ",
]


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _gradient(line: str, code: str) -> str:
    return f"\033[{code}m{line}\033[0m" if _supports_color() else line


# Magenta → cyan vertical gradient (256-color codes).
_GRADIENT_CODES = ["38;5;201", "38;5;165", "38;5;129", "38;5;93", "38;5;57"]


def render_banner(subtitle: str | None = None) -> str:
    """Return the multi-line CVO banner (with optional subtitle)."""
    lines: list[str] = [""]
    for letter, code in zip(_LETTERS, _GRADIENT_CODES):
        lines.append(_gradient(letter, code))
    if subtitle:
        dim = "2;37"
        lines.append("")
        lines.append(_gradient(f"   {subtitle}", dim))
    lines.append("")
    return "\n".join(lines)


def print_banner(subtitle: str | None = None) -> None:
    print(render_banner(subtitle))


def mask_key(key: str) -> str:
    """Show only the last 4 chars of an API key, masking the rest."""
    if not key:
        return "(empty)"
    if len(key) <= 4:
        return "*" * len(key)
    return f"{'*' * 8}{key[-4:]}"
