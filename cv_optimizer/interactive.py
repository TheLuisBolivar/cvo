"""
Tiny TUI helpers used by the CLI: a `select` for arrow-key menus and a
`secret` for hidden input.

Uses `questionary` when available (arrow-key navigation, cross-platform).
Falls back to a numbered prompt if questionary is missing or stdin is not
a TTY (e.g. piped input in CI).

Public API:
    select(message, choices, default=None)
        choices: list of (label, value) tuples OR list of plain strings.
        Returns the selected `value` (or the string itself), or None on cancel.

    secret(message)
        Hidden input. Returns the entered string (may be empty).
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import Any

try:
    import questionary  # type: ignore
    _HAVE_QUESTIONARY = True
except ImportError:
    questionary = None  # type: ignore
    _HAVE_QUESTIONARY = False


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _normalize_choices(
    choices: list[tuple[str, Any]] | list[str],
) -> tuple[list[str], list[Any]]:
    """Returns (labels, values) for both shapes."""
    labels: list[str] = []
    values: list[Any] = []
    for c in choices:
        if isinstance(c, tuple):
            labels.append(c[0])
            values.append(c[1])
        else:
            labels.append(str(c))
            values.append(c)
    return labels, values


def select(
    message: str,
    choices: list[tuple[str, Any]] | list[str],
    default: Any = None,
) -> Any:
    """
    Show a menu. Returns the chosen value, or None if the user cancels.
    """
    labels, values = _normalize_choices(choices)
    if not labels:
        return None

    if _HAVE_QUESTIONARY and _is_interactive():
        # Map default value back to its label for questionary.
        default_label: str | None = None
        if default is not None:
            for lbl, val in zip(labels, values):
                if val == default:
                    default_label = lbl
                    break
        try:
            picked_label = questionary.select(
                message,
                choices=labels,
                default=default_label,
                use_indicator=True,
                instruction="(↑/↓ to move · Enter to confirm · Esc/Ctrl-C to cancel)",
            ).ask()
        except KeyboardInterrupt:
            return None
        if picked_label is None:
            return None
        return values[labels.index(picked_label)]

    return _select_fallback(message, labels, values, default)


def _select_fallback(
    message: str,
    labels: list[str],
    values: list[Any],
    default: Any,
) -> Any:
    """Numbered-list fallback used when questionary is unavailable."""
    print()
    print(message)
    for i, lbl in enumerate(labels, start=1):
        print(f"  {i}) {lbl}")
    print()

    default_idx = 1
    if default is not None and default in values:
        default_idx = values.index(default) + 1

    while True:
        try:
            raw = input(f"Pick 1-{len(labels)} [{default_idx}]: ").strip()
        except EOFError:
            return None
        if raw.lower() in ("q", "quit", "exit"):
            return None
        if not raw:
            return values[default_idx - 1]
        if raw.isdigit() and 1 <= int(raw) <= len(labels):
            return values[int(raw) - 1]
        print("  invalid choice — try again.")


def secret(message: str) -> str:
    """
    Hidden input. Uses questionary's password mode when available,
    falls back to getpass.
    """
    if _HAVE_QUESTIONARY and _is_interactive():
        try:
            value = questionary.password(message).ask()
        except KeyboardInterrupt:
            return ""
        return (value or "").strip()
    try:
        return getpass.getpass(message + " ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return ""
