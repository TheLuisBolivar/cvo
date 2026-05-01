"""
Local CV ↔ Offer match score.

100% deterministic, no LLM calls — runs in milliseconds. Gives an early
signal before committing tokens to the full optimization pipeline.

Weighted combination of four signals:
    40%  Hard skills overlap          (offer.hard_skills    ∩ CV)
    30%  Must-have coverage           (offer.must_have      ∩ CV)
    20%  ATS keywords coverage        (offer.ats_keywords   ⊂ CV text)
    10%  Seniority alignment          (cv years ↔ offer.seniority)

Per-category breakdown lists what matched and what's missing, so the
user can decide whether to push through or rework their CV first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import CV, Offer
from .summary import _estimate_years


# Years-of-experience ranges per seniority level. Tuned so a 7-year senior
# scores 100, a 1-year mid scores below 100 (underqualified), etc.
_SENIORITY_YEARS = {
    "junior":    (0, 2),
    "mid":       (2, 5),
    "senior":    (5, 9),
    "lead":      (7, 13),
    "staff":     (8, 15),
    "principal": (12, 30),
}

WEIGHTS = {
    "hard_skills":  0.40,
    "must_have":    0.30,
    "ats_keywords": 0.20,
    "seniority":    0.10,
}


@dataclass
class CategoryScore:
    score: float                                  # 0–100
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    note: str = ""                                # extra context (seniority)


@dataclass
class MatchReport:
    overall: int
    hard_skills:  CategoryScore
    must_have:    CategoryScore
    ats_keywords: CategoryScore
    seniority:    CategoryScore


# ──────────────────────────────────────────────────────────────────────
# Normalization + lookup helpers
# ──────────────────────────────────────────────────────────────────────
def _normalize(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9+#./ ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cv_vocabulary(cv: CV) -> set[str]:
    """Normalized set of 'skills' the CV explicitly claims."""
    out: set[str] = set()
    if isinstance(cv.skills, dict):
        for items in cv.skills.values():
            for s in items:
                out.add(_normalize(s))
    elif isinstance(cv.skills, list):
        for s in cv.skills:
            out.add(_normalize(s))
    for exp in cv.experiences:
        for t in exp.technologies:
            out.add(_normalize(t))
    out.discard("")
    return out


def _cv_full_text(cv: CV) -> str:
    """All free-form CV text concatenated and normalized — for ATS-keyword search."""
    parts: list[str] = [cv.summary or ""]
    for exp in cv.experiences:
        parts.extend([exp.position, exp.company, exp.description])
        parts.extend(exp.achievements)
        parts.extend(exp.technologies)
    if isinstance(cv.skills, dict):
        for items in cv.skills.values():
            parts.extend(items)
    elif isinstance(cv.skills, list):
        parts.extend(cv.skills)
    return _normalize(" ".join(p for p in parts if p))


def _matches(item: str, vocab: set[str], full_text: str) -> bool:
    """An offer term matches if it appears in the CV's skill vocab or anywhere in its text."""
    n = _normalize(item)
    if not n:
        return False
    if n in vocab:
        return True
    # Substring both directions: handles 'kubernetes' vs 'kubernetes (k8s)' and similar.
    for v in vocab:
        if n in v or v in n:
            return True
    # Whole-word match in concatenated text.
    return bool(re.search(r"(^|\W)" + re.escape(n) + r"(\W|$)", full_text))


def _category(items: list[str], vocab: set[str], full_text: str) -> CategoryScore:
    if not items:
        return CategoryScore(score=100.0)  # nothing required → don't penalize
    matched, missing = [], []
    for item in items:
        if not item:
            continue
        (matched if _matches(item, vocab, full_text) else missing).append(item)
    total = len(matched) + len(missing)
    pct = (len(matched) / total * 100.0) if total else 100.0
    return CategoryScore(score=round(pct, 1), matched=matched, missing=missing)


def _seniority_score(cv: CV, offer: Offer) -> CategoryScore:
    target = (offer.seniority or "").lower().strip()
    years = _estimate_years(cv)
    if target not in _SENIORITY_YEARS:
        return CategoryScore(score=80.0, note=f"{years}y experience (offer seniority unspecified)")
    lo, hi = _SENIORITY_YEARS[target]
    if lo <= years <= hi:
        return CategoryScore(score=100.0, note=f"{years}y aligns with {target} ({lo}–{hi}y)")
    if years < lo:
        gap = lo - years
        return CategoryScore(
            score=max(30.0, 100.0 - gap * 15.0),
            note=f"{years}y is {gap}y below {target} range ({lo}–{hi}y)",
        )
    gap = years - hi
    return CategoryScore(
        score=max(70.0, 100.0 - gap * 5.0),  # overqualified penalized less
        note=f"{years}y exceeds {target} range ({lo}–{hi}y) by {gap}y",
    )


def compute_match(cv: CV, offer: Offer) -> MatchReport:
    vocab = _cv_vocabulary(cv)
    full = _cv_full_text(cv)

    hs = _category(offer.hard_skills,  vocab, full)
    mh = _category(offer.must_have,    vocab, full)
    kw = _category(offer.ats_keywords, vocab, full)
    se = _seniority_score(cv, offer)

    overall = (
        hs.score * WEIGHTS["hard_skills"]
        + mh.score * WEIGHTS["must_have"]
        + kw.score * WEIGHTS["ats_keywords"]
        + se.score * WEIGHTS["seniority"]
    )
    return MatchReport(
        overall=round(overall),
        hard_skills=hs,
        must_have=mh,
        ats_keywords=kw,
        seniority=se,
    )
