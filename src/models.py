"""Shared job model and normalization helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(" " if unicodedata.category(char)[0] in {"P", "S"} else char for char in value)
    value = value.encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


@dataclass(slots=True)
class Job:
    source: str
    title: str
    company: str
    url: str
    source_job_id: str | None = None
    source_website: str | None = None
    company_website: str | None = None
    company_logo_url: str | None = None
    country: str | None = None
    city: str | None = None
    location: str | None = None
    remote_eligibility: str | None = None
    work_arrangement: str | None = None
    employment_type: str | None = None
    experience_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    category: str | None = None
    skills: list[str] = field(default_factory=list)
    description: str | None = None
    published_at: str | None = None
    first_discovered_at: str = field(default_factory=utc_now)
    last_checked_at: str = field(default_factory=utc_now)

    def normalized_key(self) -> tuple[str, str, str]:
        loc = self.location or ", ".join(filter(None, (self.city, self.country)))
        return normalize_text(self.title), normalize_text(self.company), normalize_text(loc)

    def fingerprint(self) -> str:
        title, company, location = self.normalized_key()
        description = normalize_text(self.description)[:500]
        payload = "\x1f".join((title, company, location, description))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> Job:
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in values.items() if key in allowed})
