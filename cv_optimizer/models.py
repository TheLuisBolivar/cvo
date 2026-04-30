"""
Data models. We use plain dataclasses since the CV JSON is intentionally flexible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
