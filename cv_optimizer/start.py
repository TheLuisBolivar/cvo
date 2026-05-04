"""
Guided pipeline — `cvo start`.

Walks the user through every step interactively:
    1. Pick the CV (path / file-dialog / file already in data/)
    2. If PDF or DOCX, ask whether to convert it to JSON
    3. Pick the offer (path / file-dialog)
    4. Run the alignment with a per-experience BEFORE / AFTER view
    5. Export to the chosen format(s)

Designed as a friendlier alternative to the batch-style `cvo run`. Both
share the same underlying functions (analyzer / aligner / summary /
skills / generator / exporters).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ._progress import stream_json, stream_text
from .banner import print_banner
from .cache import (
    delete_cached_parses,
    get_cached_parse,
    hash_file,
    init_db,
    set_cached_parse,
)
from .docx_parser import extract_docx_text
from .exporters import export_all, parse_format_list
from .gaps import generate_gap_plan, render_gap_plan_markdown
from .generator import build_optimized_cv_dict, generate_markdown, generate_report
from .interactive import (
    confirm,
    open_file_dialog,
    prompt_path,
    prompt_text,
    select,
    select_multiple,
)
from .match_score import MatchReport, compute_match
from .models import CV, Experience, Offer
from .pdf_parser import extract_pdf_text
from .url_fetcher import fetch_offer_text, is_url
from .prompts import (
    ALIGNER_PROMPT, ALIGNER_SYSTEM,
    ANALYZER_PROMPT, ANALYZER_SYSTEM,
    CV_PARSER_PROMPT, CV_PARSER_SYSTEM,
    SKILLS_PROMPT, SKILLS_SYSTEM,
    SUMMARY_PROMPT, SUMMARY_SYSTEM,
)
from .providers import (
    has_api_key,
    make_client,
    provider_meta,
)
from .setup_wizard import ensure_provider_configured
from .summary import _estimate_years, _industries, _tech_match


# ──────────────────────────────────────────────────────────────────────
# Color helpers (kept local so this module doesn't import from cli.py)
# ──────────────────────────────────────────────────────────────────────
def _supports_color() -> bool:
    import os
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _c(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _supports_color() else s


def _cyan(s: str)    -> str: return _c(s, "36")
def _green(s: str)   -> str: return _c(s, "32")
def _yellow(s: str)  -> str: return _c(s, "33")
def _red(s: str)     -> str: return _c(s, "31")
def _magenta(s: str) -> str: return _c(s, "1;35")
def _bold(s: str)    -> str: return _c(s, "1")
def _dim(s: str)     -> str: return _c(s, "2;37")


def _info(msg: str): print(_cyan(f"ℹ  {msg}"))
def _ok(msg: str):   print(_green(f"✓  {msg}"))
def _warn(msg: str): print(_yellow(f"⚠  {msg}"))
def _err(msg: str):  print(_red(f"✗  {msg}"))


def _step(idx: int, total: int, title: str) -> None:
    print()
    print(_bold(_magenta(f"━━━ Step {idx}/{total} — {title} ".ljust(70, "━"))))


# ──────────────────────────────────────────────────────────────────────
# File-pick helpers
# ──────────────────────────────────────────────────────────────────────
_DATA_DIRS = {
    "json":   Path("data/json"),
    "pdf":    Path("data/pdfs"),
    "docx":   Path("data/docx"),
    "offers": Path("data/offers"),
}
_KIND_FROM_SUFFIX = {".json": "json", ".pdf": "pdf", ".docx": "docx"}


def _list_data_files() -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    for kind, p in _DATA_DIRS.items():
        if not p.is_dir():
            continue
        glob = "*.json" if kind == "json" else f"*.{kind}"
        items.extend((kind, f) for f in sorted(p.glob(glob)))
    return items


def _pick_cv() -> tuple[str, Path] | None:
    """Returns (kind, path) for the chosen CV, or None to cancel.

    Loops so 'Manage / delete' returns to the picker after deletion.
    """
    while True:
        existing = _list_data_files()
        options: list[tuple[str, str]] = [
            ("Type a path",      "path"),
            ("Open file dialog", "dialog"),
        ]
        if existing:
            options.insert(0, (f"Use one already in data/  ({len(existing)} found)", "data"))
            options.append(("Manage / delete CVs in data/", "manage"))

        mode = select(
            "How do you want to provide the CV?",
            options,
            default="data" if existing else "path",
        )
        if mode is None:
            return None

        if mode == "manage":
            _manage_cvs(existing)
            continue  # back to the picker so the user can pick or delete more

        if mode == "data":
            choices = [(f"[{k.upper():4}] {p}", (k, p)) for k, p in existing]
            picked = select("Pick a CV from data/", choices, default=existing[0])
            return picked

        if mode == "dialog":
            path = open_file_dialog(
                "Select your CV",
                filetypes=[("CV files", "*.pdf *.docx *.json"),
                           ("PDF", "*.pdf"),
                           ("DOCX", "*.docx"),
                           ("JSON", "*.json")],
            )
            if not path:
                _warn("No file selected.")
                continue
        else:  # "path"
            raw = prompt_path(
                "Path to your CV (.pdf / .docx / .json):",
                only_existing=True,
                extensions=[".pdf", ".docx", ".json"],
            )
            if not raw:
                continue
            path = raw

        p = Path(path).expanduser()
        suffix = p.suffix.lower()
        if suffix not in _KIND_FROM_SUFFIX:
            _err(f"Unsupported file type: {suffix}")
            continue
        return _KIND_FROM_SUFFIX[suffix], p


_DONE_SENTINEL = ("__done__", Path("/"))


def _manage_cvs(_unused: list[tuple[str, Path]]) -> None:
    """
    One-at-a-time delete loop. Each iteration:
      1. Re-lists the files in data/ so the UI stays in sync.
      2. Lets the user pick one (or 'Done' to exit).
      3. Asks Y/N confirmation.
      4. Wipes cache rows for that file_hash, then unlink()s.
      5. Verifies the file is actually gone.
    """
    while True:
        current = _list_data_files()
        if not current:
            _ok("No CVs left in data/.")
            return

        choices: list[tuple[str, tuple[str, Path]]] = [
            (f"[{kind.upper():4}] {p}", (kind, p)) for kind, p in current
        ]
        choices.append(("◀  Done — back to CV picker", _DONE_SENTINEL))

        picked = select(
            f"Pick a CV to delete  ({len(current)} in data/)",
            choices,
            default=current[0],
        )
        if picked is None or picked == _DONE_SENTINEL:
            return

        kind, p = picked
        if not confirm(
            f"Delete {p}?  (this cannot be undone)",
            default=False,
        ):
            _info("Skipped — file kept.")
            continue

        # Best-effort cache cleanup BEFORE unlink (we need the file to hash).
        cache_rows = 0
        try:
            if p.exists():
                cache_rows = delete_cached_parses(hash_file(p))
        except Exception as e:
            _warn(f"Could not clean cache for {p}: {e}")

        # Actual deletion + verification.
        try:
            p.unlink()
        except FileNotFoundError:
            _warn(f"Already gone: {p}")
            continue
        except PermissionError as e:
            _err(f"Permission denied deleting {p}: {e}")
            continue
        except Exception as e:
            _err(f"Could not delete {p}: {e}")
            continue

        if p.exists():
            _err(f"unlink() returned but file STILL exists: {p.resolve()}")
            continue

        _ok(f"Deleted: {p.resolve()}")
        if cache_rows:
            _info(f"  …and removed {cache_rows} cached parse row(s).")


def _pick_offer() -> tuple[str, Any] | None:
    """
    Pick where the offer comes from. Returns (kind, value):
      - ("file", Path)
      - ("url",  str)
      - None if cancelled.
    """
    options = [
        ("Type a path",      "path"),
        ("Open file dialog", "dialog"),
        ("Paste a URL",      "url"),
    ]
    mode = select("How do you want to provide the job offer?", options, default="path")
    if mode is None:
        return None

    if mode == "url":
        url = prompt_text(
            "Offer URL (https://…):",
            validate=lambda v: True if is_url(v or "") else "Must start with http:// or https://",
        )
        if not url:
            return None
        return "url", url

    if mode == "dialog":
        path = open_file_dialog(
            "Select the job offer",
            filetypes=[
                ("Offer files", "*.txt *.md *.json"),
                ("Text",        "*.txt *.md"),
                ("JSON",        "*.json"),
                ("Any",         "*.*"),
            ],
        )
        if not path:
            _warn("No file selected.")
            return None
    else:
        path = prompt_path(
            "Path to the offer (.txt / .md / .json):",
            only_existing=True,
            extensions=[".txt", ".md", ".json"],
        )
        if not path:
            return None
    return "file", Path(path).expanduser()


# ──────────────────────────────────────────────────────────────────────
# Per-experience BEFORE / AFTER view
# ──────────────────────────────────────────────────────────────────────
def _print_experience_diff(
    idx: int,
    total: int,
    exp: Experience,
    aligned: dict[str, Any],
) -> None:
    print()
    print(_bold(_magenta(f"  Experience {idx}/{total} — {exp.position} @ {exp.company}")))
    print(_dim(f"  {exp.start_date} → {exp.end_date}" + (f" · {exp.location}" if exp.location else "")))
    print()

    # BEFORE
    print(_yellow(_bold("  BEFORE")))
    if exp.achievements:
        for b in exp.achievements:
            print(_dim(f"    · {b}"))
    else:
        print(_dim("    (no original bullets)"))

    # AFTER
    print()
    print(_green(_bold("  AFTER")))
    bullets = aligned.get("bullets") or []
    if bullets:
        for b in bullets:
            print(_green(f"    ✓ {b}"))
    else:
        print(_dim("    (no aligned bullets)"))

    # Stack + score + notes
    stack = aligned.get("highlighted_technologies") or []
    if stack:
        print()
        print(_dim(f"  Stack: {', '.join(stack)}"))

    score = aligned.get("alignment_score", 0)
    notes = aligned.get("alignment_notes", "")
    bar = _score_bar(score)
    print()
    print(f"  {_bold('alignment')} {bar}  {_bold(str(score))}/100")
    if notes:
        print(_dim(f"  {notes}"))


def _score_bar(score: int, width: int = 20) -> str:
    score = max(0, min(100, int(score)))
    filled = round(score / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    if score >= 75:
        return _green(bar)
    if score >= 50:
        return _yellow(bar)
    return _red(bar)


def _print_match_report(report: MatchReport) -> None:
    """Pretty-print the local CV ↔ Offer match score with a breakdown."""
    overall_bar = _score_bar(report.overall, width=28)
    print()
    print(_bold(_magenta(f"  CV ↔ Offer match")))
    print(f"  {overall_bar}  {_bold(str(report.overall) + '%')}")
    print()

    rows = [
        ("Hard skills",   "40%", report.hard_skills),
        ("Must-have",     "30%", report.must_have),
        ("ATS keywords",  "20%", report.ats_keywords),
        ("Seniority",     "10%", report.seniority),
    ]
    for name, weight, cat in rows:
        bar = _score_bar(int(cat.score), width=14)
        print(f"  {name:<14} {_dim(weight)}  {bar}  {_bold(f'{int(cat.score)}%'.rjust(4))}")
        if cat.matched:
            shown = ", ".join(cat.matched[:8])
            extra = f"  (+{len(cat.matched)-8} more)" if len(cat.matched) > 8 else ""
            print(_green(f"     ✓ {shown}{extra}"))
        if cat.missing:
            shown = ", ".join(cat.missing[:8])
            extra = f"  (+{len(cat.missing)-8} more)" if len(cat.missing) > 8 else ""
            print(_red(f"     ✗ {shown}{extra}"))
        if cat.note:
            print(_dim(f"       {cat.note}"))
    print()


# ──────────────────────────────────────────────────────────────────────
# Subcommand entry point
# ──────────────────────────────────────────────────────────────────────
def cmd_start(args: argparse.Namespace) -> int:
    print_banner(subtitle="cv-optimizer · guided pipeline")

    # ── Provider / API key ──
    try:
        provider = ensure_provider_configured(args.provider)
    except KeyboardInterrupt:
        print(); _err("Setup cancelled."); return 130
    if not has_api_key(provider):
        _err(f"Still no API key for {provider}. Aborting."); return 1
    meta = provider_meta(provider)
    main_client = make_client(provider, args.model or meta["default_model"])
    _info(f"Provider: {meta['display_name']} (model: {main_client.model})")

    # ── Step 1 — pick CV ──
    _step(1, 4, "Select your CV")
    picked = _pick_cv()
    if picked is None:
        _err("No CV selected."); return 1
    kind, cv_path = picked
    _ok(f"CV: {cv_path}")

    # Copy into data/<kind>/ if it lives outside the project.
    cv_path = _copy_into_data(cv_path, kind)

    # ── Step 2 — convert to JSON if needed ──
    _step(2, 4, "Convert to structured JSON" if kind != "json" else "Skip parsing (already JSON)")
    if kind == "json":
        _ok("Input is already JSON — no parsing needed.")
        cv = CV.from_json_file(cv_path)
    else:
        # Pick parser provider: prefer DeepSeek when available (cheaper).
        parser_provider = "deepseek" if has_api_key("deepseek") else provider
        parser_client = make_client(parser_provider)
        intermediate = _DATA_DIRS["json"] / (cv_path.stem + ".json")

        # ── Idempotent cache check ──
        cv_dict: dict[str, Any] | None = None
        if not args.no_cache:
            try:
                init_db()
                file_hash = hash_file(cv_path)
                cached = get_cached_parse(file_hash, parser_provider, parser_client.model)
            except Exception as e:
                _warn(f"Cache lookup failed ({e}) — re-parsing.")
                cached = None
            if cached:
                _ok(
                    f"Cached parse found (parsed {cached['parsed_at']} with "
                    f"{parser_provider}/{parser_client.model}) — reusing."
                )
                _info(_dim("Pass --no-cache to force a fresh parse."))
                cv_dict = cached["data"]
                # Mirror to data/json/ for visibility.
                intermediate.parent.mkdir(parents=True, exist_ok=True)
                intermediate.write_text(json.dumps(cv_dict, ensure_ascii=False, indent=2), encoding="utf-8")

        if cv_dict is None:
            proceed = select(
                f"Process the {kind.upper()} into JSON now?",
                [("Yes — parse it with the LLM", True),
                 ("No — abort",                  False)],
                default=True,
            )
            if not proceed:
                _warn("Aborted."); return 0

            _info(f"Parser:   {provider_meta(parser_provider)['display_name']} (model: {parser_client.model})")
            try:
                if kind == "pdf":
                    text = extract_pdf_text(cv_path)
                else:
                    text = extract_docx_text(cv_path)
                _ok(f"Extracted {len(text)} chars of raw text")
                prompt = CV_PARSER_PROMPT.format(pdf_text=text[:60_000])
                # Long / senior CVs can blow past 8000 — start at 16k, retry to 32k.
                cv_dict = stream_json(
                    parser_client, prompt, CV_PARSER_SYSTEM,
                    max_tokens=16000,
                    label=f"Parsing {kind.upper()} → JSON",
                    temperature=0.1,
                    max_retry_tokens=32000,
                )
            except Exception as e:
                print()
                _err(f"Parsing failed: {e}"); return 1

            intermediate.parent.mkdir(parents=True, exist_ok=True)
            intermediate.write_text(json.dumps(cv_dict, ensure_ascii=False, indent=2), encoding="utf-8")
            _ok(f"Saved structured JSON to: {intermediate}")

            # Save to cache for next time.
            try:
                set_cached_parse(
                    file_hash=hash_file(cv_path),
                    parser_provider=parser_provider,
                    parser_model=parser_client.model,
                    file_name=cv_path.name,
                    file_kind=kind,
                    parsed=cv_dict,
                )
            except Exception as e:
                _warn(f"Could not write to cache: {e}")

        cv = CV.from_dict(cv_dict)

    _ok(f"{cv.personal_info.get('name','(no name)')} · {len(cv.experiences)} experience(s)")

    # ── Step 3 — pick offer(s) ──
    _step(3, 4, "Select the job offer")
    _info("Batch mode (multiple offers) not yet implemented — single offer for now.")
    picked_offer = _pick_offer()
    if picked_offer is None:
        _err("No offer selected."); return 1
    offer_kind, offer_value = picked_offer

    offer: Offer | None = None
    offer_text: str = ""
    offer_label: str = ""  # used to name the saved JSON

    if offer_kind == "url":
        _info(f"Fetching offer from {offer_value} …")
        try:
            offer_text = fetch_offer_text(offer_value)
        except (RuntimeError, ValueError) as e:
            _err(str(e)); return 1
        _ok(f"Fetched and cleaned {len(offer_text)} chars from {offer_value}")
        offer_label = _slug_from_url(offer_value)

    else:
        offer_path: Path = offer_value
        if not offer_path.exists():
            _err(f"Offer not found: {offer_path}"); return 1
        suffix = offer_path.suffix.lower()
        if suffix == ".json":
            try:
                offer = Offer.from_json_file(offer_path)
            except Exception as e:
                _err(f"Could not load offer JSON {offer_path}: {e}"); return 1
            _ok(f"Offer JSON loaded — skipping analyzer (already structured).")
            _info(f"Position: {offer.position or '(unknown)'} · seniority: {offer.seniority or '(unknown)'}")
        elif suffix in (".txt", ".md"):
            offer_text = offer_path.read_text(encoding="utf-8")
            _ok(f"Offer loaded ({len(offer_text)} chars): {offer_path}")
            offer_label = offer_path.stem
        else:
            _err(f"Unsupported offer format: {suffix}. Use .txt, .md, or .json.")
            return 1

    # ── Step 4 — run the pipeline ──
    _step(4, 4, "Optimize the CV")

    # Run analyzer ONLY when we have raw text (URL / .txt / .md).
    if offer is None:
        analyzer_prompt = ANALYZER_PROMPT.format(offer=offer_text.strip())
        analysis = stream_json(
            main_client, analyzer_prompt, ANALYZER_SYSTEM,
            max_tokens=3000, label="Analyzing offer", temperature=0.2,
        )
        offer = Offer.from_dict(analysis)
        offer._source = offer_kind
        offer._source_value = offer_value if offer_kind == "url" else str(offer_path)
        offer._raw_text = offer_text
        # Persist the analyzed offer for reuse next time.
        if offer_label:
            saved = offer.save(_DATA_DIRS["offers"] / f"{offer_label}.json")
            _ok(f"Saved structured offer to: {saved}")

    analysis = offer.to_dict(include_provenance=False)
    _ok(f"Position: {analysis.get('position','?')} · seniority: {analysis.get('seniority','?')}")
    _ok(f"hard_skills={len(analysis.get('hard_skills', []))} · ats_keywords={len(analysis.get('ats_keywords', []))}")

    # ── Match preview (deterministic, no LLM) ──
    report = compute_match(cv, offer)
    _print_match_report(report)

    if report.overall < 30:
        prompt_msg = f"Match is low ({report.overall}%). Optimize anyway?"
        default_proceed = False
    else:
        prompt_msg = "Continue with the optimization?"
        default_proceed = True
    proceed = select(
        prompt_msg,
        [("Yes — run optimizer", True),
         ("No — abort",          False)],
        default=default_proceed,
    )
    if not proceed:
        _warn("Aborted by user."); return 0

    print()
    _info(f"Aligning {len(cv.experiences)} experience(s) — BEFORE / AFTER per experience:")
    aligned: list[dict[str, Any]] = []
    total = len(cv.experiences)
    for i, exp in enumerate(cv.experiences, start=1):
        achievements_fmt = "\n".join(f"- {a}" for a in exp.achievements) or "(no bullets provided)"
        techs_fmt = ", ".join(exp.technologies) or "(unspecified)"
        prompt = ALIGNER_PROMPT.format(
            company=exp.company, position=exp.position,
            start_date=exp.start_date, end_date=exp.end_date,
            location=exp.location or "unspecified",
            description=exp.description or "(no description provided)",
            achievements=achievements_fmt, technologies=techs_fmt,
            offer_analysis=json.dumps(analysis, ensure_ascii=False, indent=2),
        )
        try:
            result = stream_json(
                main_client, prompt, ALIGNER_SYSTEM,
                max_tokens=4000,
                label=f"Aligning experience {i}/{total}",
                temperature=0.2,
                max_retry_tokens=8000,
            )
            result["_original_experience"] = exp
            aligned.append(result)
            _print_experience_diff(i, total, exp, result)
        except Exception as e:
            print()
            _err(f"Experience {i}/{total} failed: {e}")
            aligned.append({
                "_original_experience": exp,
                "_error": str(e),
                "optimized_position": exp.position,
                "bullets": exp.achievements,
                "highlighted_technologies": exp.technologies,
                "alignment_score": 0,
                "alignment_notes": f"Alignment failed: {e}",
            })

    print()
    summary_prompt = SUMMARY_PROMPT.format(
        current_title=cv.personal_info.get("current_title", ""),
        original_summary=cv.summary or "(no original summary)",
        years=_estimate_years(cv),
        tech_match=", ".join(_tech_match(cv, analysis.get("hard_skills", []))) or "(none explicit)",
        industries=", ".join(_industries(cv)) or "(unspecified)",
        target_position=analysis.get("position", ""),
        seniority=analysis.get("seniority", ""),
        hard_skills=", ".join(analysis.get("hard_skills", [])),
        responsibilities=", ".join(analysis.get("key_responsibilities", [])),
    )
    summary = stream_text(
        main_client, summary_prompt, SUMMARY_SYSTEM,
        max_tokens=400, label="Writing summary", temperature=0.5,
    )

    skills_prompt = SKILLS_PROMPT.format(
        candidate_skills=json.dumps(cv.skills, ensure_ascii=False, indent=2),
        offer_hard_skills=json.dumps(analysis.get("hard_skills", []), ensure_ascii=False),
    )
    skills = stream_json(
        main_client, skills_prompt, SKILLS_SYSTEM,
        max_tokens=1500, label="Reordering skills", temperature=0.2,
    )

    # ── Gap-closing plan (LLM, ~3000 tokens) ──
    print()
    try:
        plan = generate_gap_plan(cv, offer, main_client)
    except Exception as e:
        _warn(f"Gap plan generation failed: {e}")
        plan = None

    # ── Export ──
    formats = parse_format_list(args.format)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    md = generate_markdown(cv, summary, aligned, skills, analysis)
    cv_dict_out = build_optimized_cv_dict(cv, summary, aligned, skills, analysis)
    written = export_all(formats, md, cv_dict_out, output_path)

    # Report = alignment report + gap plan (if any)
    report_md = generate_report(aligned, skills, analysis)
    if plan is not None:
        report_md += "\n" + render_gap_plan_markdown(plan)
    report_path = output_path.with_name(output_path.stem + "_report.md")
    report_path.write_text(report_md, encoding="utf-8")

    print()
    print(_bold("Outputs:"))
    if "md" in written:    _ok(f"  Markdown: {written['md']}")
    if "json" in written:  _ok(f"  JSON:     {written['json']}")
    if "docx" in written:  _ok(f"  DOCX:     {written['docx']}")
    if "docx_error" in written: _warn(f"  DOCX skipped: {written['docx_error']}")
    if "pdf" in written:   _ok(f"  PDF:      {written['pdf']}")
    if "pdf_error" in written: _warn(f"  PDF skipped: {written['pdf_error']}")
    _ok(f"  Report:   {report_path}")

    scores = [e.get("alignment_score", 0) for e in aligned]
    if scores:
        avg = sum(scores) / len(scores)
        print()
        print(_bold(_magenta(f"  Average alignment score: {avg:.0f}/100")))
        print()
    return 0


# ──────────────────────────────────────────────────────────────────────
# Helpers (kept here to avoid circular imports with cli.py)
# ──────────────────────────────────────────────────────────────────────
def _copy_into_data(input_path: Path, kind: str) -> Path:
    """Mirror of cli._ensure_in_data_folder — duplicated here on purpose
    to avoid importing cli.py during package init."""
    target_dir = _DATA_DIRS[kind]
    target_dir.mkdir(parents=True, exist_ok=True)

    abs_input = input_path.resolve()
    abs_target_dir = target_dir.resolve()
    try:
        if abs_input.parent == abs_target_dir:
            return input_path
    except OSError:
        pass

    target = target_dir / input_path.name
    if target.exists():
        try:
            if target.resolve() == abs_input or _files_equal(target, input_path):
                return target
        except OSError:
            pass
        from datetime import datetime
        stem, suffix = target.stem, target.suffix
        target = target_dir / f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"

    import shutil
    shutil.copy2(input_path, target)
    _info(f"Copied CV → {target}")
    return target


def _slug_from_url(url: str, max_len: int = 50) -> str:
    """URL → a filesystem-safe slug like 'linkedin_com-jobs-1234-abc12345'."""
    import hashlib
    import re
    from urllib.parse import urlparse
    parsed = urlparse(url)
    raw = (parsed.netloc + parsed.path).replace("/", "-")
    raw = re.sub(r"[^a-zA-Z0-9._-]+", "", raw).strip("-")[:max_len]
    suffix = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{raw or 'offer'}-{suffix}"


def _files_equal(a: Path, b: Path, chunk: int = 65536) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    with a.open("rb") as fa, b.open("rb") as fb:
        while True:
            ca, cb = fa.read(chunk), fb.read(chunk)
            if ca != cb:
                return False
            if not ca:
                return True
