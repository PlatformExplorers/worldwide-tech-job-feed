"""Adapter for Himalayas' public remote jobs API."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from src.models import Job
from src.sources.base import JobSource, clean_html, list_or_empty, text_or_none


class HimalayasSource(JobSource):
    name = "himalayas"
    endpoint = "https://himalayas.app/jobs/api"

    def fetch(self) -> list[Job]:
        maximum = max(1, min(int(self.options.get("max_pages", 5)), 10))
        params: dict[str, Any] = {"limit": 20}
        cursors: set[str] = set()
        jobs: list[Job] = []
        for _ in range(maximum):
            data: Any = self.get(self.endpoint, params=params.copy()).json()
            if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                raise ValueError("Himalayas response did not contain a jobs list")
            for item in data["jobs"][:20]:
                if job := self._normalize(item):
                    jobs.append(job)
            cursor = data.get("nextCursor")
            if not cursor or not data["jobs"]:
                break
            if not isinstance(cursor, str) or cursor in cursors:
                raise ValueError("Himalayas returned an invalid or repeated pagination cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        return jobs

    def _normalize(self, item: Any) -> Job | None:
        if not isinstance(item, dict):
            return None
        title = text_or_none(item.get("title"))
        company = text_or_none(item.get("companyName"))
        url = text_or_none(item.get("applicationLink"))
        if not title or not company or not url:
            return None
        expiry = _timestamp(item.get("expiryDate"))
        if expiry and datetime.fromisoformat(expiry) <= datetime.now(timezone.utc):
            return None
        location = ", ".join(list_or_empty(item.get("locationRestrictions"))) or "Worldwide"
        categories = list_or_empty(item.get("categories"))
        return Job(
            source=self.name,
            source_job_id=text_or_none(item.get("guid")),
            title=title,
            company=company,
            url=url,
            source_website=url,
            company_logo_url=text_or_none(item.get("companyLogo")),
            location=location,
            remote_eligibility=location,
            work_arrangement="remote",
            employment_type=text_or_none(item.get("employmentType")),
            experience_level=text_or_none(item.get("seniority")),
            salary_min=_salary(item.get("minSalary")),
            salary_max=_salary(item.get("maxSalary")),
            salary_currency=text_or_none(item.get("currency")),
            salary_period=text_or_none(item.get("salaryPeriod")),
            category=", ".join(categories) or None,
            description=clean_html(item.get("description") or item.get("excerpt")),
            published_at=_timestamp(item.get("pubDate")),
        )


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("Himalayas returned an invalid timestamp")
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _salary(value: Any) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("Himalayas returned an invalid salary")
    return float(value)
