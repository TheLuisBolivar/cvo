"""
Aligner: for each experience, deeply aligns it with the offer without
inventing anything. Returns rewritten bullets + match metrics.

Provider-agnostic — accepts any LLMClient.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .models import Experience
from .providers import LLMClient
from .prompts import ALIGNER_PROMPT, ALIGNER_SYSTEM


def align_experience(
    experience: Experience,
    offer_analysis: dict[str, Any],
    client: LLMClient,
) -> dict[str, Any]:
    """Align ONE experience. Returns dict with bullets, score, notes."""
    achievements_fmt = (
        "\n".join(f"- {a}" for a in experience.achievements)
        or "(no bullets provided)"
    )
    techs_fmt = ", ".join(experience.technologies) or "(unspecified)"

    prompt = ALIGNER_PROMPT.format(
        company=experience.company,
        position=experience.position,
        start_date=experience.start_date,
        end_date=experience.end_date,
        location=experience.location or "unspecified",
        description=experience.description or "(no description provided)",
        achievements=achievements_fmt,
        technologies=techs_fmt,
        offer_analysis=json.dumps(offer_analysis, ensure_ascii=False, indent=2),
    )
    return client.call_json(prompt, system=ALIGNER_SYSTEM, max_tokens=2500)


def align_all(
    experiences: list[Experience],
    offer_analysis: dict[str, Any],
    client: LLMClient,
    on_progress: Callable[[int, int, Experience], None] | None = None,
) -> list[dict[str, Any]]:
    """Process all experiences sequentially. Errors do not abort the run."""
    results: list[dict[str, Any]] = []
    total = len(experiences)
    for i, exp in enumerate(experiences, start=1):
        if on_progress:
            on_progress(i, total, exp)
        try:
            result = align_experience(exp, offer_analysis, client)
            result["_original_experience"] = exp
            results.append(result)
        except Exception as e:
            results.append({
                "_original_experience": exp,
                "_error": str(e),
                "optimized_position": exp.position,
                "bullets": exp.achievements,
                "highlighted_technologies": exp.technologies,
                "alignment_score": 0,
                "alignment_notes": f"Alignment failed: {e}",
            })
    return results
