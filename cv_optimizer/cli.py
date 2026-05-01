"""
cvo — cv-optimizer command-line entrypoint.

Subcommands:
    cvo start        Interactive guided pipeline (recommended for new users)
    cvo run          Full pipeline: CV (PDF or JSON) + offer → optimized CV
    cvo parse-pdf    Just parse a CV PDF into the standard JSON
    cvo setup        Interactive provider + API-key wizard

Examples:
    cvo run --offer offer.txt                     # auto-detect CV in data/
    cvo run --pdf  my_cv.pdf  --offer offer.txt   # any path; copied to data/pdfs/
    cvo run --docx my_cv.docx --offer offer.txt   # any path; copied to data/docx/
    cvo run --cv   examples/cv_example.json --offer examples/offer_example.txt
    cvo run --offer offer.txt --provider gemini --format pdf,docx
    cvo run --pdf my_cv.pdf --offer offer.txt --quiet
    cvo parse-pdf --pdf my_cv.pdf
    cvo setup
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from . import (
    CV,
    align_all,
    analyze_offer,
    build_optimized_cv_dict,
    ensure_provider_configured,
    export_all,
    extract_pdf_text,
    generate_markdown,
    generate_report,
    generate_summary,
    has_api_key,
    make_client,
    parse_docx_to_cv,
    parse_format_list,
    parse_pdf_to_cv,
    provider_meta,
    reorder_skills,
    resolve_active_provider,
    run_wizard,
)
from .docx_parser import extract_docx_text
from .banner import print_banner
from .client import _extract_json
from .deepseek_client import DEFAULT_DEEPSEEK_MODEL
from .interactive import select
from .providers import LLMClient, PROVIDER_ORDER
from .start import cmd_start
from .prompts import (
    ALIGNER_PROMPT,
    ALIGNER_SYSTEM,
    ANALYZER_PROMPT,
    ANALYZER_SYSTEM,
    CV_PARSER_PROMPT,
    CV_PARSER_SYSTEM,
    SKILLS_PROMPT,
    SKILLS_SYSTEM,
    SUMMARY_PROMPT,
    SUMMARY_SYSTEM,
)
from .summary import _estimate_years, _industries, _tech_match


# ──────────────────────────────────────────────────────────────────────
# Tiny ANSI helpers (no extra deps)
# ──────────────────────────────────────────────────────────────────────
def _supports_color() -> bool:
    return sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _supports_color() else text


def cyan(s: str)    -> str: return _c(s, "36")
def green(s: str)   -> str: return _c(s, "32")
def yellow(s: str)  -> str: return _c(s, "33")
def red(s: str)     -> str: return _c(s, "31")
def magenta(s: str) -> str: return _c(s, "1;35")
def dim(s: str)     -> str: return _c(s, "2;37")
def bold(s: str)    -> str: return _c(s, "1")


def info(msg: str): print(cyan(f"ℹ  {msg}"))
def ok(msg: str):   print(green(f"✓  {msg}"))
def warn(msg: str): print(yellow(f"⚠  {msg}"))
def err(msg: str):  print(red(f"✗  {msg}"))


def section(title: str, idx: int | None = None, total: int | None = None):
    prefix = f"[{idx}/{total}] " if idx is not None and total is not None else ""
    bar = "─" * max(0, 60 - len(prefix) - len(title) - 2)
    print()
    print(bold(magenta(f"── {prefix}{title} {bar}")))


# ──────────────────────────────────────────────────────────────────────
# Streaming helpers
# ──────────────────────────────────────────────────────────────────────
def _stream_to_stdout(stream: Iterator[str], label: str) -> str:
    print(dim(f"┌─ live {label} ──────"))
    print(dim("│ "), end="", flush=True)
    buf: list[str] = []
    started = time.time()
    char_count = 0
    line_width = 0
    for token in stream:
        buf.append(token)
        char_count += len(token)
        for ch in token:
            if ch == "\n":
                print()
                print(dim("│ "), end="", flush=True)
                line_width = 0
            else:
                sys.stdout.write(dim(ch))
                line_width += 1
                if line_width >= 100:
                    print()
                    print(dim("│ "), end="", flush=True)
                    line_width = 0
        sys.stdout.flush()
    print()
    elapsed = time.time() - started
    print(dim(f"└─ {char_count} chars in {elapsed:.1f}s"))
    return "".join(buf)


def _stream_json(client: LLMClient, prompt: str, system: str, label: str, max_tokens: int = 4096, temperature: float = 0.2) -> dict[str, Any]:
    raw = _stream_to_stdout(
        client.call_stream(prompt, system=system, max_tokens=max_tokens, temperature=temperature),
        label,
    )
    return _extract_json(raw)


def _stream_text(client: LLMClient, prompt: str, system: str, label: str, max_tokens: int = 1024, temperature: float = 0.5) -> str:
    return _stream_to_stdout(
        client.call_stream(prompt, system=system, max_tokens=max_tokens, temperature=temperature),
        label,
    ).strip()


# ──────────────────────────────────────────────────────────────────────
# Data folder layout + copy logic
# ──────────────────────────────────────────────────────────────────────
DATA_DIRS: dict[str, Path] = {
    "json": Path("data/json"),
    "pdf":  Path("data/pdfs"),
    "docx": Path("data/docx"),
}


def _list_data_files() -> dict[str, list[Path]]:
    """Return {kind: sorted file list} for json / pdf / docx."""
    return {
        "json": sorted(DATA_DIRS["json"].glob("*.json")) if DATA_DIRS["json"].is_dir() else [],
        "pdf":  sorted(DATA_DIRS["pdf"].glob("*.pdf"))   if DATA_DIRS["pdf"].is_dir()  else [],
        "docx": sorted(DATA_DIRS["docx"].glob("*.docx")) if DATA_DIRS["docx"].is_dir() else [],
    }


def _pick_data_file(found: dict[str, list[Path]]) -> tuple[str, Path] | None:
    """
    Show a picker. JSON gets priority (no re-parse). Returns (kind, path) or None.
    """
    items: list[tuple[str, Path]] = (
        [("json", p) for p in found["json"]]
        + [("pdf",  p) for p in found["pdf"]]
        + [("docx", p) for p in found["docx"]]
    )
    if not items:
        return None
    if len(items) == 1:
        kind, p = items[0]
        info(f"Auto-detected single CV: {p}")
        return kind, p

    choices: list[tuple[str, tuple[str, Path]]] = [
        (f"[{kind.upper():4}] {p}", (kind, p)) for kind, p in items
    ]
    return select("Found multiple CVs in data/. Pick one:", choices, default=items[0])


def _ensure_in_data_folder(input_path: Path, kind: str) -> Path:
    """
    Copy `input_path` into `data/<kind>/` so all CVs we work with live in
    the project. Returns the path that should be used downstream:
      - same path, if it's already inside the right folder.
      - the new copy's path otherwise.

    On filename collision with different content, appends a timestamp
    instead of overwriting.
    """
    target_dir = DATA_DIRS[kind]
    target_dir.mkdir(parents=True, exist_ok=True)

    abs_input = input_path.resolve()
    abs_target_dir = target_dir.resolve()

    # Already inside data/<kind>/ → no copy needed.
    try:
        if abs_input.parent == abs_target_dir:
            return input_path
    except OSError:
        pass

    target = target_dir / input_path.name
    if target.exists():
        # Same name already in data/. If contents match, just reuse it.
        try:
            if target.resolve() == abs_input or _files_equal(target, input_path):
                return target
        except OSError:
            pass
        # Different content → keep both, suffix the new one with a timestamp.
        from datetime import datetime
        stem, suffix = target.stem, target.suffix
        target = target_dir / f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"

    import shutil
    shutil.copy2(input_path, target)
    info(f"Copied CV → {target}")
    return target


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


# ──────────────────────────────────────────────────────────────────────
# Live pipeline phases
# ──────────────────────────────────────────────────────────────────────
def _run_parser_phase_live(
    input_path: Path,
    kind: str,
    parser_client: LLMClient,
    intermediate_json: Path,
    idx: int,
    total: int,
    provider_label: str,
) -> dict[str, Any]:
    label = "PDF" if kind == "pdf" else "DOCX"
    section(f"Parse {label} → CV JSON  ({provider_label} · {parser_client.model})", idx, total)
    info(f"Reading: {input_path}")
    text = extract_pdf_text(input_path) if kind == "pdf" else extract_docx_text(input_path)
    ok(f"Extracted {len(text)} chars of raw text")

    info("Streaming structured CV JSON from the model…")
    truncated = text[:60_000]
    prompt = CV_PARSER_PROMPT.format(pdf_text=truncated)
    cv_dict = _stream_json(parser_client, prompt, CV_PARSER_SYSTEM, provider_label, max_tokens=8000, temperature=0.1)

    intermediate_json.parent.mkdir(parents=True, exist_ok=True)
    intermediate_json.write_text(json.dumps(cv_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    name = cv_dict.get("personal_info", {}).get("name", "(no name)")
    n_exp = len(cv_dict.get("experiences", []))
    ok(f"Parsed: {name} · {n_exp} experience(s)")
    ok(f"Saved intermediate JSON to: {intermediate_json}")
    return cv_dict


def _run_analyzer_phase_live(offer_text: str, client: LLMClient, idx: int, total: int, provider_label: str) -> dict[str, Any]:
    section(f"Analyze offer  ({provider_label} · {client.model})", idx, total)
    prompt = ANALYZER_PROMPT.format(offer=offer_text.strip())
    analysis = _stream_json(client, prompt, ANALYZER_SYSTEM, provider_label, max_tokens=3000, temperature=0.2)
    ok(f"Position: {analysis.get('position','?')} · {analysis.get('seniority','?')}")
    ok(f"  hard_skills: {len(analysis.get('hard_skills', []))} · ats_keywords: {len(analysis.get('ats_keywords', []))}")
    return analysis


def _run_aligner_phase_live(cv: CV, analysis: dict[str, Any], client: LLMClient, idx: int, total: int, provider_label: str) -> list[dict[str, Any]]:
    section(f"Align experiences  ({provider_label} · {client.model})", idx, total)
    aligned: list[dict[str, Any]] = []
    n = len(cv.experiences)
    for i, exp in enumerate(cv.experiences, start=1):
        info(f"  ({i}/{n}) {exp.position} @ {exp.company}")
        achievements_fmt = "\n".join(f"- {a}" for a in exp.achievements) or "(no bullets provided)"
        techs_fmt = ", ".join(exp.technologies) or "(unspecified)"
        prompt = ALIGNER_PROMPT.format(
            company=exp.company,
            position=exp.position,
            start_date=exp.start_date,
            end_date=exp.end_date,
            location=exp.location or "unspecified",
            description=exp.description or "(no description provided)",
            achievements=achievements_fmt,
            technologies=techs_fmt,
            offer_analysis=json.dumps(analysis, ensure_ascii=False, indent=2),
        )
        try:
            result = _stream_json(client, prompt, ALIGNER_SYSTEM, f"{provider_label} (exp {i})", max_tokens=2500, temperature=0.2)
            result["_original_experience"] = exp
            ok(f"  → score {result.get('alignment_score', 0)}/100")
            aligned.append(result)
        except Exception as e:
            err(f"  alignment failed: {e}")
            aligned.append({
                "_original_experience": exp,
                "_error": str(e),
                "optimized_position": exp.position,
                "bullets": exp.achievements,
                "highlighted_technologies": exp.technologies,
                "alignment_score": 0,
                "alignment_notes": f"Alignment failed: {e}",
            })
    return aligned


def _run_summary_phase_live(cv: CV, analysis: dict[str, Any], client: LLMClient, idx: int, total: int, provider_label: str) -> str:
    section(f"Professional summary  ({provider_label} · {client.model})", idx, total)
    prompt = SUMMARY_PROMPT.format(
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
    return _stream_text(client, prompt, SUMMARY_SYSTEM, provider_label, max_tokens=400, temperature=0.5)


def _run_skills_phase_live(cv: CV, analysis: dict[str, Any], client: LLMClient, idx: int, total: int, provider_label: str) -> dict[str, Any]:
    section(f"Reorder skills  ({provider_label} · {client.model})", idx, total)
    prompt = SKILLS_PROMPT.format(
        candidate_skills=json.dumps(cv.skills, ensure_ascii=False, indent=2),
        offer_hard_skills=json.dumps(analysis.get("hard_skills", []), ensure_ascii=False),
    )
    return _stream_json(client, prompt, SKILLS_SYSTEM, provider_label, max_tokens=1500, temperature=0.2)


# ──────────────────────────────────────────────────────────────────────
# Subcommand: cvo run
# ──────────────────────────────────────────────────────────────────────
def cmd_run(args: argparse.Namespace) -> int:
    offer_path = Path(args.offer)
    output_path = Path(args.output)

    if not offer_path.exists():
        err(f"Offer not found: {offer_path}"); return 1

    # ── Resolve provider + ensure key is set (wizard if missing) ──
    try:
        provider = ensure_provider_configured(args.provider)
    except KeyboardInterrupt:
        print(); err("Setup cancelled."); return 130
    meta = provider_meta(provider)
    if not has_api_key(provider):
        err(f"Still no {meta['env_key']} after setup. Aborting."); return 1

    chosen_model = args.model or meta["default_model"]
    main_client: LLMClient = make_client(provider, chosen_model)
    provider_label = meta["display_name"].split(" ")[0]  # short label for logs

    # ── Format selection ──
    try:
        formats = parse_format_list(args.format)
    except ValueError as e:
        err(str(e)); return 2

    # ── Resolve input: explicit flag, or auto-detect in data/ ──
    explicit = [(k, getattr(args, k)) for k in ("pdf", "docx", "cv") if getattr(args, k)]
    if len(explicit) > 1:
        err("Pass only one of --pdf / --docx / --cv."); return 2
    input_kind: str | None = None
    input_path: Path | None = None
    if explicit:
        flag, value = explicit[0]
        input_kind = "json" if flag == "cv" else flag
        input_path = Path(value)
        if not input_path.exists():
            err(f"{flag.upper()} not found: {input_path}"); return 1
    else:
        picked = _pick_data_file(_list_data_files())
        if picked is None:
            err("No CV provided and none found in data/json/, data/pdfs/, or data/docx/."); return 1
        input_kind, input_path = picked

    # Copy input into data/<kind>/ if it lives outside the project.
    input_path = _ensure_in_data_folder(input_path, input_kind)
    needs_parsing = input_kind in ("pdf", "docx")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print_banner(subtitle="cv-optimizer · ready to align")
    info(f"Mode:           {'quiet' if args.quiet else 'live (streaming)'}")
    info(f"Provider:       {meta['display_name']}  (model: {chosen_model})")
    info(f"Output formats: {', '.join(formats)}")

    # ── Pick the parser client when we need to parse PDF/DOCX ──
    parser_client: LLMClient | None = None
    parser_label: str = provider_label
    if needs_parsing:
        pdf_provider = args.pdf_provider
        if not pdf_provider:
            pdf_provider = "deepseek" if has_api_key("deepseek") else provider
        if not has_api_key(pdf_provider):
            err(
                f"Parsing {input_kind.upper()} requires an API key for {pdf_provider}. "
                f"Set {provider_meta(pdf_provider)['env_key']} (re-run `cvo setup` "
                f"and pick {pdf_provider}), or pass --pdf-provider."
            ); return 1
        parser_model = args.deepseek_model if pdf_provider == "deepseek" else None
        parser_client = make_client(pdf_provider, parser_model)
        parser_label = provider_meta(pdf_provider)["display_name"].split(" ")[0]
        info(f"Doc parser:     {provider_meta(pdf_provider)['display_name']}  (model: {parser_client.model})")

    # ── Load CV ──
    if needs_parsing:
        intermediate = DATA_DIRS["json"] / (input_path.stem + ".json")
        intermediate.parent.mkdir(parents=True, exist_ok=True)
        if args.quiet:
            info(f"Parsing {input_kind.upper()} → JSON ({parser_client.model})…")
            if input_kind == "pdf":
                cv_dict = parse_pdf_to_cv(input_path, parser_client, output_path=intermediate)
            else:
                cv_dict = parse_docx_to_cv(input_path, parser_client, output_path=intermediate)
            ok(f"Saved intermediate JSON to: {intermediate}")
        else:
            cv_dict = _run_parser_phase_live(
                input_path, input_kind, parser_client, intermediate,
                1, _total_phases(needs_parsing), parser_label,
            )
        cv = CV.from_dict(cv_dict)
    else:
        info(f"Loading CV from {input_path}")
        cv = CV.from_json_file(input_path)
        ok(f"CV loaded: {len(cv.experiences)} experience(s)")

    info(f"Reading offer: {offer_path}")
    offer_text = offer_path.read_text(encoding="utf-8")
    ok(f"Offer loaded ({len(offer_text)} chars)")

    # ── Run the rest of the pipeline (live or quiet) ──
    if args.quiet:
        info("Analyzing offer…")
        analysis = analyze_offer(offer_text, main_client)
        ok(f"Position: {analysis.get('position','?')} · {analysis.get('seniority','?')}")

        info(f"Aligning {len(cv.experiences)} experience(s)…")
        def progress(i: int, total: int, exp): info(f"  [{i}/{total}] {exp.position} @ {exp.company}")
        aligned = align_all(cv.experiences, analysis, main_client, on_progress=progress)
        ok("Experiences aligned")

        info("Generating professional summary…")
        summary = generate_summary(cv, analysis, main_client)
        ok("Summary generated")

        info("Reordering skills…")
        skills = reorder_skills(cv, analysis, main_client)
        ok("Skills reordered")
    else:
        total_phases = _total_phases(needs_parsing)
        next_idx = 2 if needs_parsing else 1
        if not needs_parsing:
            section("Load CV from JSON", 1, total_phases)
            ok(f"Loaded: {len(cv.experiences)} experience(s)")
        analysis = _run_analyzer_phase_live(offer_text, main_client, next_idx, total_phases, provider_label); next_idx += 1
        aligned  = _run_aligner_phase_live(cv, analysis, main_client, next_idx, total_phases, provider_label); next_idx += 1
        summary  = _run_summary_phase_live(cv, analysis, main_client, next_idx, total_phases, provider_label); next_idx += 1
        skills   = _run_skills_phase_live(cv, analysis, main_client, next_idx, total_phases, provider_label); next_idx += 1
        section("Assemble outputs", next_idx, total_phases)

    # ── Final assembly ──
    md = generate_markdown(cv, summary, aligned, skills, analysis)
    cv_dict_out = build_optimized_cv_dict(cv, summary, aligned, skills, analysis)

    written = export_all(formats, md, cv_dict_out, output_path)

    # Always also write the report.
    report_path = Path(args.report) if args.report else output_path.with_name(output_path.stem + "_report.md")
    report_md = generate_report(aligned, skills, analysis)
    report_path.write_text(report_md, encoding="utf-8")

    # ── Summary ──
    print()
    print(bold("Outputs:"))
    if "md" in written:    ok(f"  Markdown: {written['md']}")
    if "json" in written:  ok(f"  JSON:     {written['json']}")
    if "docx" in written:  ok(f"  DOCX:     {written['docx']}")
    if "docx_error" in written:
        warn(f"  DOCX skipped: {written['docx_error']}")
    if "pdf" in written:   ok(f"  PDF:      {written['pdf']}")
    if "pdf_error" in written:
        warn(f"  PDF skipped: {written['pdf_error']}")
    ok(f"  Report:   {report_path}")

    scores = [e.get("alignment_score", 0) for e in aligned]
    if scores:
        average = sum(scores) / len(scores)
        print()
        print(bold(magenta(f"  Average alignment score: {average:.0f}/100")))
        print()
    return 0


def _total_phases(needs_parsing: bool) -> int:
    return 6 if needs_parsing else 5


# ──────────────────────────────────────────────────────────────────────
# Subcommand: cvo parse-pdf
# ──────────────────────────────────────────────────────────────────────
def cmd_parse_pdf(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        err(f"PDF not found: {pdf_path}"); return 1
    if pdf_path.suffix.lower() != ".pdf":
        err(f"File is not a PDF: {pdf_path}"); return 1

    # Resolve provider for PDF parsing
    pdf_provider = args.provider or ("deepseek" if has_api_key("deepseek") else None)
    if not pdf_provider:
        pdf_provider = ensure_provider_configured(None)
    elif not has_api_key(pdf_provider):
        ensure_provider_configured(pdf_provider)

    chosen_model = args.model or provider_meta(pdf_provider)["default_model"]
    client = make_client(pdf_provider, chosen_model)

    if args.output:
        output_path = Path(args.output)
    elif Path("data/json").is_dir():
        output_path = Path("data/json") / (pdf_path.stem + ".json")
    else:
        output_path = pdf_path.with_suffix(".json")

    info(f"Provider: {provider_meta(pdf_provider)['display_name']} · Model: {chosen_model}")
    info(f"Reading PDF: {pdf_path}")

    try:
        cv_dict = parse_pdf_to_cv(pdf_path, client, output_path=output_path)
    except Exception as e:
        err(str(e)); return 1

    n_exp = len(cv_dict.get("experiences", []))
    name = cv_dict.get("personal_info", {}).get("name", "(no name)")
    ok(f"CV parsed: {name} · {n_exp} experience(s)")
    ok(f"JSON written to: {output_path}")
    info("Review the JSON before passing it to `cvo run` — the LLM may have made mistakes.")
    return 0


# ──────────────────────────────────────────────────────────────────────
# Subcommand: cvo setup
# ──────────────────────────────────────────────────────────────────────
def cmd_setup(args: argparse.Namespace) -> int:
    try:
        run_wizard(preselected_provider=args.provider, force=args.force)
    except KeyboardInterrupt:
        print(); err("Setup cancelled."); return 130
    return 0


# ──────────────────────────────────────────────────────────────────────
# Argparse + main
# ──────────────────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cvo",
        description="cv-optimizer — tailor your CV to a specific job offer using LLMs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="<command>")

    # cvo start
    p_start = sub.add_parser(
        "start",
        help="Guided interactive pipeline (recommended). Walks through CV pick → parse → offer → align.",
        description="Interactive wizard: pick a CV (path or file dialog), choose to parse it, "
                    "pick the offer, then run the alignment with a per-experience BEFORE/AFTER view.",
    )
    p_start.add_argument("--provider", choices=PROVIDER_ORDER, default=None,
                         help="LLM provider override (default: $CVO_PROVIDER from .env, or 'claude').")
    p_start.add_argument("--model", default=None, help="Model override for the active provider.")
    p_start.add_argument("--output", default="output/cv_optimized.md",
                         help="Base output path (default: output/cv_optimized.md).")
    p_start.add_argument("--format", default="md,json",
                         help="Output formats. Options: md, json, pdf, docx, or 'all'. Default: md,json.")
    p_start.add_argument("--no-cache", action="store_true",
                         help="Skip the SQLite parse cache; force a fresh PDF/DOCX → JSON parse.")
    p_start.set_defaults(func=cmd_start)

    # cvo run
    p_run = sub.add_parser(
        "run",
        help="Run the full pipeline: CV (PDF or JSON) + offer → optimized CV",
        description="Run the full pipeline. Streams output by default; pass --quiet for scripted runs.",
    )
    src = p_run.add_mutually_exclusive_group(required=False)
    src.add_argument("--pdf",  help="Path to a CV PDF (parsed to JSON first)")
    src.add_argument("--docx", help="Path to a CV .docx (parsed to JSON first)")
    src.add_argument("--cv",   help="Path to a CV JSON (skip the parsing phase)")
    p_run.add_argument("--offer", required=True, help="Path to the job offer (.txt or .md)")
    p_run.add_argument("--output", default="output/cv_optimized.md", help="Path for the optimized CV (default: output/cv_optimized.md)")
    p_run.add_argument("--report", default=None, help="Path for the alignment report (default: alongside --output)")
    p_run.add_argument("--provider", choices=PROVIDER_ORDER, default=None,
                       help="LLM provider for analysis/alignment/summary/skills. "
                            "Default: $CVO_PROVIDER from .env, or 'claude'.")
    p_run.add_argument("--model", default=None, help="Model override for the active provider (default: provider's default).")
    p_run.add_argument("--pdf-provider", choices=PROVIDER_ORDER, default=None,
                       help="Provider used for PDF→JSON parsing. Default: deepseek if configured, else the active provider.")
    p_run.add_argument("--deepseek-model", default=DEFAULT_DEEPSEEK_MODEL, help=f"DeepSeek model (used only when DeepSeek parses the PDF). Default: {DEFAULT_DEEPSEEK_MODEL}")
    p_run.add_argument("--format", default="md,json",
                       help="Output formats, comma-separated. Options: md, json, pdf, docx, or 'all'. Default: md,json.")
    p_run.add_argument("--quiet", action="store_true", help="Disable streaming; concise output for scripts")
    p_run.set_defaults(func=cmd_run)

    # cvo parse-pdf
    p_pdf = sub.add_parser(
        "parse-pdf",
        help="Parse a CV PDF into the standard JSON (no alignment, no offer needed)",
        description="Parse a CV PDF into the standard JSON schema.",
    )
    p_pdf.add_argument("--pdf", required=True, help="Path to the CV PDF")
    p_pdf.add_argument("--output", default=None, help="Output JSON path (default: data/json/<same_name>.json)")
    p_pdf.add_argument("--provider", choices=PROVIDER_ORDER, default=None,
                       help="Provider used for parsing (default: deepseek if configured, else active provider).")
    p_pdf.add_argument("--model", default=None, help="Model override (default: provider's default).")
    p_pdf.set_defaults(func=cmd_parse_pdf)

    # cvo setup
    p_setup = sub.add_parser(
        "setup",
        help="Interactive provider + API-key wizard. Writes to .env (gitignored).",
        description="Pick which LLM provider to use (Claude / ChatGPT / Gemini / DeepSeek), "
                    "paste its API key, and store it in .env.",
    )
    p_setup.add_argument("--provider", choices=PROVIDER_ORDER, default=None,
                         help="Skip the picker and configure this provider directly.")
    p_setup.add_argument("--force", action="store_true",
                         help="Re-prompt for the API key even if one is already set.")
    p_setup.set_defaults(func=cmd_setup)

    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
