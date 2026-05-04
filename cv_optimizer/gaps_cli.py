"""
`cvo gaps` — standalone gap-closing plan generator.

Useful when you've already run `cvo start` (or `cvo screen`) and just want
to re-run / iterate the gap plan without re-doing the full pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .gaps import generate_gap_plan, render_gap_plan_markdown
from .interactive import select
from .models import CV, Offer
from .providers import has_api_key, make_client, provider_meta
from .setup_wizard import ensure_provider_configured


def _supports_color() -> bool:
    import os, sys
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _c(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _supports_color() else s


def _info(msg: str): print(_c(f"ℹ  {msg}", "36"))
def _ok(msg: str):   print(_c(f"✓  {msg}", "32"))
def _err(msg: str):  print(_c(f"✗  {msg}", "31"))


def _resolve_cv(arg: str | None) -> CV | None:
    if arg:
        p = Path(arg).expanduser()
        if not p.exists():
            _err(f"CV not found: {p}"); return None
        return CV.from_json_file(p)
    cands = sorted(Path("data/json").glob("*.json")) if Path("data/json").is_dir() else []
    if not cands:
        _err("No --cv given and no JSONs in data/json/."); return None
    if len(cands) == 1:
        _info(f"Auto-detected CV: {cands[0]}")
        return CV.from_json_file(cands[0])
    picked = select("Pick a CV", [(str(p), p) for p in cands], default=cands[0])
    return CV.from_json_file(picked) if picked else None


def _resolve_offer(arg: str | None) -> Offer | None:
    if arg:
        p = Path(arg).expanduser()
        if not p.exists():
            _err(f"Offer not found: {p}"); return None
        return Offer.from_json_file(p)
    cands = sorted(Path("data/offers").glob("*.json")) if Path("data/offers").is_dir() else []
    if not cands:
        _err("No --offer given and no JSONs in data/offers/."); return None
    if len(cands) == 1:
        _info(f"Auto-detected offer: {cands[0]}")
        return Offer.from_json_file(cands[0])
    picked = select("Pick an offer", [(str(p), p) for p in cands], default=cands[0])
    return Offer.from_json_file(picked) if picked else None


def cmd_gaps(args: argparse.Namespace) -> int:
    try:
        provider = ensure_provider_configured(args.provider)
    except KeyboardInterrupt:
        print(); _err("Setup cancelled."); return 130
    if not has_api_key(provider):
        _err(f"No API key for {provider}. Run `cvo setup`."); return 1
    meta = provider_meta(provider)
    client = make_client(provider, args.model or meta["default_model"])
    _info(f"Provider: {meta['display_name']} (model: {client.model})")

    cv = _resolve_cv(args.cv)
    if cv is None:
        return 1
    offer = _resolve_offer(args.offer)
    if offer is None:
        return 1

    plan = generate_gap_plan(cv, offer, client)

    md = render_gap_plan_markdown(plan)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    _ok(f"Gap plan written to: {out_path}")

    # Also print to stdout for immediate visibility.
    print()
    print(md)
    return 0
