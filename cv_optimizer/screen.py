"""
`cvo screen` — pre-filter a list of job offers against the user's CV.

For each source (URL / .txt / .md / .json) it:
  1. Fetches/loads the offer text.
  2. Runs the analyzer (skipped for already-structured .json offers).
  3. Computes the deterministic match score against the CV.
  4. Saves the structured offer to data/offers/.

Then prints a ranked table — highest match first — so the user can
decide which offers are worth running through the full optimizer.

No alignment, no summary, no skills. Just analyze + match.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ._progress import stream_json
from .interactive import select
from .match_score import MatchReport, compute_match
from .models import CV, Offer
from .prompts import ANALYZER_PROMPT, ANALYZER_SYSTEM
from .providers import has_api_key, make_client, provider_meta
from .setup_wizard import ensure_provider_configured
from .url_fetcher import fetch_offer_text, is_url


# Local color helpers (avoid circular import with cli.py).
def _supports_color() -> bool:
    import os, sys
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _c(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _supports_color() else s


def _cyan(s: str)    -> str: return _c(s, "36")
def _green(s: str)   -> str: return _c(s, "32")
def _yellow(s: str)  -> str: return _c(s, "33")
def _red(s: str)     -> str: return _c(s, "31")
def _bold(s: str)    -> str: return _c(s, "1")
def _dim(s: str)     -> str: return _c(s, "2;37")
def _info(msg: str): print(_cyan(f"ℹ  {msg}"))
def _ok(msg: str):   print(_green(f"✓  {msg}"))
def _warn(msg: str): print(_yellow(f"⚠  {msg}"))
def _err(msg: str):  print(_red(f"✗  {msg}"))


_DATA_OFFERS = Path("data/offers")


def _slug_from_url(url: str, max_len: int = 50) -> str:
    import hashlib, re
    from urllib.parse import urlparse
    parsed = urlparse(url)
    raw = (parsed.netloc + parsed.path).replace("/", "-")
    raw = re.sub(r"[^a-zA-Z0-9._-]+", "", raw).strip("-")[:max_len]
    suffix = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{raw or 'offer'}-{suffix}"


def _resolve_cv(cv_arg: str | None) -> CV | None:
    """Load CV from --cv path or auto-detect a JSON in data/json/."""
    if cv_arg:
        p = Path(cv_arg).expanduser()
        if not p.exists():
            _err(f"CV not found: {p}"); return None
        return CV.from_json_file(p)
    json_dir = Path("data/json")
    if not json_dir.is_dir():
        _err("No --cv given and data/json/ is empty."); return None
    cands = sorted(json_dir.glob("*.json"))
    if not cands:
        _err("No --cv given and no JSON in data/json/."); return None
    if len(cands) == 1:
        _info(f"Auto-detected CV: {cands[0]}")
        return CV.from_json_file(cands[0])
    picked = select(
        "Pick a CV from data/json/",
        [(str(p), p) for p in cands],
        default=cands[0],
    )
    if picked is None:
        return None
    return CV.from_json_file(picked)


def _load_or_analyze_offer(
    source: str,
    main_client: Any,
) -> tuple[Offer, str] | None:
    """Returns (Offer, source_label) or None on failure."""
    # JSON: skip analyzer entirely.
    if source.endswith(".json"):
        p = Path(source).expanduser()
        if not p.exists():
            raise FileNotFoundError(p)
        return Offer.from_json_file(p), str(p)

    # URL or text file → fetch raw text.
    if is_url(source):
        text = fetch_offer_text(source)
        slug = _slug_from_url(source)
    else:
        p = Path(source).expanduser()
        if not p.exists():
            raise FileNotFoundError(p)
        if p.suffix.lower() not in (".txt", ".md"):
            raise ValueError(f"Unsupported offer extension {p.suffix} (use .txt, .md, .json or a URL)")
        text = p.read_text(encoding="utf-8")
        slug = p.stem

    # Analyze.
    prompt = ANALYZER_PROMPT.format(offer=text.strip())
    analysis = stream_json(
        main_client, prompt, ANALYZER_SYSTEM,
        max_tokens=3000, label=f"Analyzing {slug[:30]}…", temperature=0.2,
    )
    offer = Offer.from_dict(analysis)
    offer._source = "url" if is_url(source) else "file"
    offer._source_value = source
    offer._raw_text = text

    # Persist to data/offers/.
    _DATA_OFFERS.mkdir(parents=True, exist_ok=True)
    saved = _DATA_OFFERS / f"{slug}.json"
    offer.save(saved)
    return offer, str(saved)


def _color_score(score: int) -> str:
    if score >= 75:
        return _green(f"{score}%")
    if score >= 50:
        return _yellow(f"{score}%")
    return _red(f"{score}%")


def cmd_screen(args: argparse.Namespace) -> int:
    # Provider
    try:
        provider = ensure_provider_configured(args.provider)
    except KeyboardInterrupt:
        print(); _err("Setup cancelled."); return 130
    if not has_api_key(provider):
        _err(f"No API key for {provider}. Run `cvo setup`."); return 1
    meta = provider_meta(provider)
    main_client = make_client(provider, args.model or meta["default_model"])
    _info(f"Provider: {meta['display_name']} (model: {main_client.model})")

    # CV
    cv = _resolve_cv(args.cv)
    if cv is None:
        return 1
    _ok(f"CV: {cv.personal_info.get('name','(no name)')} · {len(cv.experiences)} experience(s)")

    # Sources
    sources: list[str] = list(args.sources)
    if args.from_file:
        try:
            for line in Path(args.from_file).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    sources.append(line)
        except Exception as e:
            _err(f"Could not read --from-file: {e}"); return 1
    if not sources:
        _err("No offers to screen. Pass URLs/paths as args, or --from-file <list.txt>."); return 1

    _info(f"Screening {len(sources)} offer(s)…")
    print()

    results: list[dict[str, Any]] = []
    for i, src in enumerate(sources, start=1):
        print(_dim(f"  [{i}/{len(sources)}] {src}"))
        try:
            outcome = _load_or_analyze_offer(src, main_client)
            if outcome is None:
                continue
            offer, saved = outcome
            report = compute_match(cv, offer)
            results.append({
                "source": src,
                "saved":  saved,
                "offer":  offer,
                "report": report,
            })
        except Exception as e:
            _err(f"  failed: {e}")
            results.append({"source": src, "error": str(e)})

    # Rank by overall, errors at the bottom.
    def _key(r: dict[str, Any]) -> int:
        if "report" not in r:
            return -1
        return r["report"].overall

    results.sort(key=_key, reverse=True)

    # Print table.
    print()
    print(_bold("  Ranked offers (highest match first):"))
    print()
    print(_dim(f"  {'#':>3}  {'match':>5}  {'position':<35}  {'seniority':<10}  source"))
    print(_dim("  " + "─" * 100))
    for i, r in enumerate(results, start=1):
        if "error" in r:
            print(f"  {i:>3}  {_red('  err')}  {_red(r['error'][:60])}")
            continue
        offer: Offer = r["offer"]
        report: MatchReport = r["report"]
        pos = (offer.position or "(unknown)")[:35]
        sen = (offer.seniority or "")[:10]
        src = r["source"]
        if len(src) > 50:
            src = "…" + src[-49:]
        print(f"  {i:>3}  {_color_score(report.overall):>13}  {pos:<35}  {_dim(sen.ljust(10))}  {_dim(src)}")
    print()

    # Optional follow-up: pick the top one to optimize now.
    rankable = [r for r in results if "report" in r]
    if rankable and not args.no_followup:
        top = rankable[0]
        _info(
            f"Top match: {top['report'].overall}% — "
            f"{top['offer'].position or '(unknown)'}\n"
            f"   To optimize against it: `cvo start` and pick {top['saved']}"
        )

    return 0
