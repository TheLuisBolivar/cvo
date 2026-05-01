"""
Data models. Plain dataclasses — both CV and Offer are intentionally
flexible (extras are preserved, missing fields default sensibly).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class Experience:
    company: str
    position: str
    start_date: str
    end_date: str
    description: str = ""
    achievements: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    location: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Experience":
        return cls(
            company=d.get("company", ""),
            position=d.get("position", ""),
            start_date=d.get("start_date", ""),
            end_date=d.get("end_date", ""),
            description=d.get("description", ""),
            achievements=d.get("achievements", []),
            technologies=d.get("technologies", []),
            location=d.get("location", ""),
        )


@dataclass
class CV:
    personal_info: dict[str, Any]
    summary: str
    experiences: list[Experience]
    education: list[dict[str, Any]] = field(default_factory=list)
    skills: dict[str, list[str]] | list[str] = field(default_factory=dict)
    certifications: list[dict[str, Any]] = field(default_factory=list)
    languages: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "CV":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CV":
        return cls(
            personal_info=data.get("personal_info", {}),
            summary=data.get("summary", ""),
            experiences=[Experience.from_dict(e) for e in data.get("experiences", [])],
            education=data.get("education", []),
            skills=data.get("skills", {}),
            certifications=data.get("certifications", []),
            languages=data.get("languages", []),
            projects=data.get("projects", []),
        )


@dataclass
class Offer:
    """
    Structured representation of a job offer — the same shape produced
    by the ANALYZER prompt. Used downstream by the aligner, summary, and
    skills phases.

    Two ways to construct one:
      - From the analyzer output (text → JSON via the LLM).
      - Directly from a saved .json file (skip the LLM call entirely).

    `_source_*` fields capture provenance for traceability and caching.
    """

    position: str = ""
    seniority: str = ""
    industry: str = ""
    work_mode: str = ""
    hard_skills:          list[str] = field(default_factory=list)
    soft_skills:          list[str] = field(default_factory=list)
    key_responsibilities: list[str] = field(default_factory=list)
    must_have:            list[str] = field(default_factory=list)
    nice_to_have:         list[str] = field(default_factory=list)
    ats_keywords:         list[str] = field(default_factory=list)
    action_verbs:         list[str] = field(default_factory=list)
    valued_metrics:       list[str] = field(default_factory=list)
    tone_culture: str = ""

    # Provenance (not sent to LLMs, just metadata).
    _source: str = ""        # 'file' | 'url' | 'analyzer' | ''
    _source_value: str = ""  # path or URL
    _raw_text: str = ""      # cleaned input text the analyzer ran on

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Offer":
        """Tolerant of extra/missing keys."""
        names = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for k, v in data.items():
            if k in names:
                kwargs[k] = v
        return cls(**kwargs)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "Offer":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    def to_dict(self, include_provenance: bool = True) -> dict[str, Any]:
        d = asdict(self)
        if not include_provenance:
            for k in list(d.keys()):
                if k.startswith("_"):
                    d.pop(k)
        return d

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return p
