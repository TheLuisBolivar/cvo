"""
Optimized CV generator.

Primary output: ATS-friendly Markdown (no tables, no images, standard headings,
single column).

Secondary output: alignment report with scores and per-experience diff.
"""

from __future__ import annotations

from typing import Any

from .models import CV


def build_optimized_cv_dict(
    cv: CV,
    optimized_summary: str,
    aligned_experiences: list[dict[str, Any]],
    reordered_skills: dict[str, Any],
    offer_analysis: dict[str, Any],
) -> dict[str, Any]:
    """
    Build a JSON-friendly dict representing the optimized CV.

    Same shape as the input CV JSON, but with:
      - summary replaced by the aligned summary
      - experiences holding the rewritten bullets + aligner metadata
      - skills replaced by the prioritized version
      - a `_offer` block with the position the CV was tailored to
    """
    optimized_experiences: list[dict[str, Any]] = []
    for item in aligned_experiences:
        exp = item["_original_experience"]
        optimized_experiences.append({
            "company": exp.company,
            "position": item.get("optimized_position") or exp.position,
            "original_position": exp.position,
            "start_date": exp.start_date,
            "end_date": exp.end_date,
            "location": exp.location,
            "description": exp.description,
            "achievements": list(item.get("bullets", [])),
            "technologies": list(item.get("highlighted_technologies") or exp.technologies),
            "alignment_score": item.get("alignment_score", 0),
            "alignment_notes": item.get("alignment_notes", ""),
            "incorporated_ats_keywords": list(item.get("incorporated_ats_keywords", [])),
        })

    prioritized = reordered_skills.get("prioritized_skills") or cv.skills
    return {
        "personal_info": dict(cv.personal_info),
        "summary": optimized_summary.strip(),
        "experiences": optimized_experiences,
        "education": list(cv.education),
        "skills": prioritized,
        "certifications": list(cv.certifications),
        "languages": list(cv.languages),
        "projects": list(cv.projects),
        "_offer": {
            "position": offer_analysis.get("position", ""),
            "seniority": offer_analysis.get("seniority", ""),
            "ats_keywords": list(offer_analysis.get("ats_keywords", [])),
            "missing_skills": list(reordered_skills.get("offer_skills_no_match", [])),
        },
    }


def generate_markdown(
    cv: CV,
    optimized_summary: str,
    aligned_experiences: list[dict[str, Any]],
    reordered_skills: dict[str, Any],
    offer_analysis: dict[str, Any],
) -> str:
    """Generate the final CV in Markdown."""
    pi = cv.personal_info
    lines: list[str] = []

    # ── Header ──
    name = pi.get("name", "First Last")
    lines.append(f"# {name}")
    title = offer_analysis.get("position") or pi.get("current_title", "")
    if title:
        lines.append(f"**{title}**")
    lines.append("")

    contact: list[str] = []
    for key in ("email", "phone", "location", "linkedin", "github", "portfolio"):
        if pi.get(key):
            contact.append(pi[key])
    if contact:
        lines.append(" · ".join(contact))
        lines.append("")

    # ── Professional summary ──
    lines.append("## Professional summary")
    lines.append("")
    lines.append(optimized_summary.strip())
    lines.append("")

    # ── Experience ──
    lines.append("## Professional experience")
    lines.append("")
    for item in aligned_experiences:
        exp: Any = item["_original_experience"]
        position = item.get("optimized_position") or exp.position
        period = f"{exp.start_date} – {exp.end_date}"
        loc = f" · {exp.location}" if exp.location else ""
        lines.append(f"### {position} — {exp.company}")
        lines.append(f"*{period}{loc}*")
        lines.append("")
        for bullet in item.get("bullets", []):
            lines.append(f"- {bullet}")
        techs = item.get("highlighted_technologies") or []
        if techs:
            lines.append("")
            lines.append(f"**Stack:** {', '.join(techs)}")
        lines.append("")

    # ── Skills ──
    lines.append("## Technical skills")
    lines.append("")
    prioritized = reordered_skills.get("prioritized_skills", {})
    if isinstance(prioritized, dict) and prioritized:
        for cat, items in prioritized.items():
            if items:
                lines.append(f"- **{cat}:** {', '.join(items)}")
    elif isinstance(prioritized, list):
        lines.append(", ".join(prioritized))
    lines.append("")

    # ── Education ──
    if cv.education:
        lines.append("## Education")
        lines.append("")
        for ed in cv.education:
            degree = ed.get("degree", "")
            inst = ed.get("institution", "")
            period = ed.get("period", "")
            lines.append(f"- **{degree}** — {inst} *({period})*")
        lines.append("")

    # ── Certifications ──
    if cv.certifications:
        lines.append("## Certifications")
        lines.append("")
        for c in cv.certifications:
            cname = c.get("name", "")
            issuer = c.get("issuer", "")
            year = c.get("year", "")
            issuer_str = f" — {issuer}" if issuer else ""
            year_str = f" *({year})*" if year else ""
            lines.append(f"- {cname}{issuer_str}{year_str}")
        lines.append("")

    # ── Languages ──
    if cv.languages:
        lines.append("## Languages")
        lines.append("")
        for lang in cv.languages:
            lines.append(f"- **{lang.get('language','')}:** {lang.get('level','')}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_report(
    aligned_experiences: list[dict[str, Any]],
    reordered_skills: dict[str, Any],
    offer_analysis: dict[str, Any],
) -> str:
    """Audit report: scores, what was left out, what the offer asks for and you don't have."""
    lines: list[str] = []
    lines.append("# Alignment report")
    lines.append("")
    lines.append(f"**Target position:** {offer_analysis.get('position','')}")
    lines.append(f"**Seniority:** {offer_analysis.get('seniority','')}")
    lines.append("")

    # Average score
    scores = [e.get("alignment_score", 0) for e in aligned_experiences]
    if scores:
        average = sum(scores) / len(scores)
        lines.append(f"**Average alignment score:** {average:.0f}/100")
        lines.append("")

    lines.append("## Score per experience")
    lines.append("")
    for item in aligned_experiences:
        exp: Any = item["_original_experience"]
        score = item.get("alignment_score", 0)
        notes = item.get("alignment_notes", "")
        lines.append(f"- **{exp.position} @ {exp.company}:** {score}/100 — {notes}")
    lines.append("")

    # Skills you don't have
    no_match = reordered_skills.get("offer_skills_no_match", [])
    if no_match:
        lines.append("## Skills the offer asks for but you do NOT declare")
        lines.append("")
        lines.append("Consider whether you have experience with this and just didn't add it, or whether it's worth learning:")
        lines.append("")
        for s in no_match:
            lines.append(f"- {s}")
        lines.append("")

    # ATS keywords incorporated
    lines.append("## ATS keywords incorporated per experience")
    lines.append("")
    for item in aligned_experiences:
        exp = item["_original_experience"]
        kws = item.get("incorporated_ats_keywords", [])
        lines.append(f"- **{exp.position} @ {exp.company}:** {', '.join(kws) if kws else '(none)'}")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
