"""
Generation of the professional summary and reordering of skills.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .models import CV
from .providers import LLMClient
from .prompts import (
    SKILLS_PROMPT,
    SKILLS_SYSTEM,
    SUMMARY_PROMPT,
    SUMMARY_SYSTEM,
)


def _estimate_years(cv: CV) -> int:
    """Rough estimate of years of experience by summing date ranges."""
    total_months = 0
    current_year = datetime.now().year
    for exp in cv.experiences:
        start_year = _extract_year(exp.start_date)
        end_year = _extract_year(exp.end_date) or current_year
        if start_year:
            total_months += max(0, (end_year - start_year)) * 12
    return max(1, total_months // 12)


def _extract_year(s: str) -> int | None:
    m = re.search(r"(19|20)\d{2}", s or "")
    return int(m.group(0)) if m else None


def _industries(cv: CV) -> list[str]:
    # Simple heuristic: use companies as proxy. The model reasons over this anyway.
    return [e.company for e in cv.experiences if e.company]


def _tech_match(cv: CV, offer_hard_skills: list[str]) -> list[str]:
    cv_skills: set[str] = set()
    for exp in cv.experiences:
        for t in exp.technologies:
            cv_skills.add(t.lower().strip())
    if isinstance(cv.skills, dict):
        for cat in cv.skills.values():
            for t in cat:
                cv_skills.add(t.lower().strip())
    elif isinstance(cv.skills, list):
        for t in cv.skills:
            cv_skills.add(t.lower().strip())

    return [hs for hs in offer_hard_skills if hs.lower().strip() in cv_skills]


def generate_summary(
    cv: CV,
    offer_analysis: dict[str, Any],
    client: LLMClient,
) -> str:
    prompt = SUMMARY_PROMPT.format(
        current_title=cv.personal_info.get("current_title", ""),
        original_summary=cv.summary or "(no original summary)",
        years=_estimate_years(cv),
        tech_match=", ".join(_tech_match(cv, offer_analysis.get("hard_skills", []))) or "(none explicit)",
        industries=", ".join(_industries(cv)) or "(unspecified)",
        target_position=offer_analysis.get("position", ""),
        seniority=offer_analysis.get("seniority", ""),
        hard_skills=", ".join(offer_analysis.get("hard_skills", [])),
        responsibilities=", ".join(offer_analysis.get("key_responsibilities", [])),
    )
    return client.call(prompt, system=SUMMARY_SYSTEM, max_tokens=400, temperature=0.5)


def reorder_skills(
    cv: CV,
    offer_analysis: dict[str, Any],
    client: LLMClient,
) -> dict[str, Any]:
    prompt = SKILLS_PROMPT.format(
        candidate_skills=json.dumps(cv.skills, ensure_ascii=False, indent=2),
        offer_hard_skills=json.dumps(offer_analysis.get("hard_skills", []), ensure_ascii=False),
    )
    return client.call_json(prompt, system=SKILLS_SYSTEM, max_tokens=1500)
