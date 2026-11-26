"""Adapter for Jobicy's public remote jobs API."""

from __future__ import annotations

from typing import Any

from src.models import Job
from src.sources.base import JobSource, clean_html, list_or_empty, text_or_none


class JobicySource(JobSource):
    name = "jobicy"
    endpoint = "https://jobicy.com/api/v2/remote-jobs"

    def fetch(self) -> list[Job]:
        params = {"count": max(1, min(int(self.options.get("count", 50)), 50))}
        if self.options.get("geo"):
            params["geo"] = self.options["geo"]
        response: Any = self.get(self.endpoint, params=params).json()
        if not isinstance(response, dict) or not isinstance(response.get("jobs"), list):
            raise ValueError("Jobicy response did not contain a jobs list")
        return [job for item in response["jobs"] if (job := self._normalize(item))]

    def _normalize(self, item: Any) -> Job | None:
        if not isinstance(item, dict):
            return None
        title = text_or_none(item.get("jobTitle"))
        company = text_or_none(item.get("companyName"))
        url = text_or_none(item.get("url"))
        if not title or not company or not url:
            return None
        return Job(
            source=self.name,
            source_job_id=text_or_none(item.get("id")),
            title=title,
            company=company,
            url=url,
            source_website=url,
            company_website=text_or_none(item.get("companyUrl")),
            company_logo_url=text_or_none(item.get("companyLogo")),
            location=text_or_none(item.get("jobGeo")),
            remote_eligibility=text_or_none(item.get("jobGeo")),
            work_arrangement="remote",
            employment_type=text_or_none(item.get("jobType")),
            experience_level=text_or_none(item.get("jobLevel")),
            salary_min=_number(item.get("salaryMin")),
            salary_max=_number(item.get("salaryMax")),
            salary_currency=text_or_none(item.get("salaryCurrency")),
            category=", ".join(list_or_empty(item.get("jobIndustry"))) or None,
            skills=list_or_empty(item.get("jobIndustry")),
            description=clean_html(item.get("jobDescription")),
            published_at=text_or_none(item.get("pubDate")),
        )


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
