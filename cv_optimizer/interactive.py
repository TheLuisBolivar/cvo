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
    from questionary import Style as _QStyle  # type: ignore
    _HAVE_QUESTIONARY = True
except ImportError:
    questionary = None  # type: ignore
    _QStyle = None  # type: ignore
    _HAVE_QUESTIONARY = False


# ──────────────────────────────────────────────────────────────────────
# Theme — Claude-like: soft magenta highlight, bold, no harsh background
# ──────────────────────────────────────────────────────────────────────
_CVO_STYLE = (
    _QStyle(
        [
            ("qmark",       "fg:#bd93f9 bold"),       # the leading "?"
            ("question",    "bold"),                  # the prompt text
            ("answer",      "fg:#bd93f9 bold"),       # final selected answer
            ("pointer",     "fg:#ff79c6 bold"),       # ❯ pointer
            ("highlighted", "fg:#ff79c6 bold"),       # highlighted choice (no bg)
            ("selected",    "fg:#bd93f9 bold"),       # selected radio/check
            ("separator",   "fg:#6272a4"),
            ("instruction", "fg:#6272a4 italic"),     # right-side hint
            ("text",        ""),
            ("disabled",    "fg:#858585 italic"),
        ]
    )
    if _HAVE_QUESTIONARY
    else None
)


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
                qmark="❯",
                pointer="▸",
                use_indicator=False,
                use_arrow_keys=True,
                use_shortcuts=False,
                instruction="(↑/↓ · Enter)",
                style=_CVO_STYLE,
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
    Hidden input that echoes asterisks as the user types.

    - Uses questionary's password mode when available — prompt_toolkit
      renders one '*' per character.
    - Falls back to a manual termios/msvcrt loop that ALSO echoes '*' so
      the user sees feedback even without questionary.
    - Final fallback: getpass (no echo at all). Last resort, only used
      when no TTY is available.
    """
    if _HAVE_QUESTIONARY and _is_interactive():
        try:
            value = questionary.password(
                message,
                qmark="❯",
                style=_CVO_STYLE,
            ).ask()
        except KeyboardInterrupt:
            return ""
        return (value or "").strip()

    if _is_interactive():
        masked = _read_masked(message)
        if masked is not None:
            return masked.strip()

    try:
        return getpass.getpass(message + " ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return ""


def _read_masked(prompt: str) -> str | None:
    """
    Read a line from stdin, echoing '*' for each character. Returns None
    if the platform-specific path is unavailable (caller should fall back).
    """
    try:
        if os.name == "nt":  # Windows
            import msvcrt
            sys.stdout.write(prompt + " ")
            sys.stdout.flush()
            buf: list[str] = []
            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "".join(buf)
                if ch == "\x03":  # Ctrl-C
                    sys.stdout.write("\n")
                    raise KeyboardInterrupt
                if ch == "\x08":  # Backspace
                    if buf:
                        buf.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                buf.append(ch)
                sys.stdout.write("*")
                sys.stdout.flush()
        else:  # POSIX
            import termios, tty
            sys.stdout.write(prompt + " ")
            sys.stdout.flush()
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            buf: list[str] = []
            try:
                tty.setraw(fd)
                while True:
                    ch = sys.stdin.read(1)
                    if ch in ("\r", "\n"):
                        sys.stdout.write("\r\n")
                        sys.stdout.flush()
                        return "".join(buf)
                    if ch == "\x03":  # Ctrl-C
                        sys.stdout.write("\r\n")
                        raise KeyboardInterrupt
                    if ch in ("\x7f", "\x08"):  # Backspace / DEL
                        if buf:
                            buf.pop()
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                        continue
                    if ch == "\x04" and not buf:  # Ctrl-D on empty line
                        sys.stdout.write("\r\n")
                        return ""
                    buf.append(ch)
                    sys.stdout.write("*")
                    sys.stdout.flush()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (ImportError, OSError):
        return None
