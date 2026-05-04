"""
Gap-closing plan: given a CV and an Offer, generate an actionable plan
to close the missing-skills gap (courses, demo projects, time estimates).

Used in two places:
- `cvo start` appends a "Gap-closing plan" section to the report.
- `cvo gaps` standalone subcommand for re-running on existing artifacts.
"""

from __future__ import annotations

from typing import Any

from ._progress import stream_json
from .match_score import compute_match
from .models import CV, Offer
from .prompts import GAP_PLAN_PROMPT, GAP_PLAN_SYSTEM
from .providers import LLMClient
from .summary import _estimate_years


def _candidate_skill_strings(cv: CV) -> list[str]:
    out: list[str] = []
    if isinstance(cv.skills, dict):
        for items in cv.skills.values():
            out.extend(items)
    elif isinstance(cv.skills, list):
        out.extend(cv.skills)
    return out


def _candidate_tech_strings(cv: CV) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for exp in cv.experiences:
        for t in exp.technologies:
            key = t.lower().strip()
            if key and key not in seen:
                seen.add(key)
                out.append(t)
    return out


def generate_gap_plan(
    cv: CV,
    offer: Offer,
    client: LLMClient,
    label: str = "Gap-closing plan",
) -> dict[str, Any]:
    """
    Compute missing skills locally (deterministic match), then ask the LLM
    for a concrete action plan. Returns the parsed JSON dict.
    """
    report = compute_match(cv, offer)
    missing: list[str] = []
    seen: set[str] = set()
    for cat in (report.must_have, report.hard_skills, report.ats_keywords):
        for s in cat.missing:
            key = s.lower().strip()
            if key and key not in seen:
                seen.add(key)
                missing.append(s)

    if not missing:
        # Nothing to close — return a trivial OK plan.
        return {
            "summary": "No major gaps detected — the CV already covers the offer's requirements.",
            "total_estimate": "0 weekends",
            "gaps": [],
        }

    prompt = GAP_PLAN_PROMPT.format(
        years=_estimate_years(cv),
        current_title=cv.personal_info.get("current_title", ""),
        candidate_skills=", ".join(_candidate_skill_strings(cv)) or "(none declared)",
        candidate_tech=", ".join(_candidate_tech_strings(cv)) or "(none declared)",
        position=offer.position or "(unknown)",
        seniority=offer.seniority or "(unspecified)",
        must_have=", ".join(offer.must_have) or "(none)",
        hard_skills=", ".join(offer.hard_skills) or "(none)",
        nice_to_have=", ".join(offer.nice_to_have) or "(none)",
        missing=", ".join(missing),
    )
    return stream_json(
        client, prompt, GAP_PLAN_SYSTEM,
        max_tokens=3000,
        label=label,
        temperature=0.4,
        max_retry_tokens=6000,
    )


def render_gap_plan_markdown(plan: dict[str, Any]) -> str:
    """Pretty-print a gap plan dict as Markdown for inclusion in the report."""
    lines: list[str] = []
    lines.append("## Gap-closing plan")
    lines.append("")

    summary = (plan.get("summary") or "").strip()
    total = plan.get("total_estimate") or ""
    if summary:
        lines.append(summary)
        lines.append("")
    if total:
        lines.append(f"**Total estimate:** {total}")
        lines.append("")

    gaps = plan.get("gaps") or []
    if not gaps:
        lines.append("_No gaps to close._")
        return "\n".join(lines) + "\n"

    for g in gaps:
        skill = g.get("skill", "(unknown skill)")
        prio = g.get("priority", "")
        time = g.get("time_to_ready", "")
        action = g.get("first_action", "")
        bridge = g.get("bridge", "")
        demo = g.get("demo_project", "")

        head = f"### {skill}"
        meta_bits = [b for b in (prio, time) if b]
        if meta_bits:
            head += f"  *{' · '.join(meta_bits)}*"
        lines.append(head)
        lines.append("")
        if action:
            lines.append(f"- **First step:** {action}")
        if demo:
            lines.append(f"- **Demo project:** {demo}")
        if bridge:
            lines.append(f"- **Bridge:** {bridge}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
