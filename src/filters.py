"""Configurable technology and location filtering."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from src.config import AppConfig
from src.models import Job, normalize_text


def _contains_term(text: str, term: str) -> bool:
    normalized_term = normalize_text(term)
    if not normalized_term:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", text))


def is_relevant(job: Job, config: AppConfig) -> bool:
    filters = config.filters
    searchable = normalize_text(
        " ".join((job.title, job.category or "", job.description or "", *job.skills))
    )
    exclusions = filters.get("exclude_keywords", [])
    if any(_contains_term(searchable, term) for term in exclusions):
        return False
    inclusions = filters.get("include_keywords", [])
    titles = filters.get("job_titles", [])
    if inclusions or titles:
        if not any(_contains_term(searchable, term) for term in inclusions + titles):
            return False
    countries = filters.get("countries", [])
    if countries and not any(
        _contains_term(normalize_text(f"{job.country or ''} {job.location or ''}"), country)
        for country in countries
    ):
        return False
    remote_filter = filters.get("remote_only", False)
    if remote_filter and not job.remote_eligibility and job.work_arrangement != "remote":
        return False
    return True


def is_recent(job: Job, max_age_days: int) -> bool:
    if max_age_days == 0 or not job.published_at:
        return True
    try:
        published = datetime.fromisoformat(job.published_at.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    age = datetime.now(timezone.utc) - published.astimezone(timezone.utc)
    return age.days <= max_age_days
