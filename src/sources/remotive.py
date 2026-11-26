"""Adapter for Remotive's public API; configured to poll infrequently."""

from __future__ import annotations

from typing import Any

from src.models import Job
from src.sources.base import JobSource, clean_html, list_or_empty, text_or_none


class RemotiveSource(JobSource):
    name = "remotive"
    endpoint = "https://remotive.com/api/remote-jobs"

    def fetch(self) -> list[Job]:
        limit = max(1, min(int(self.options.get("limit", 100)), 100))
        params = {"limit": limit}
        response: Any = self.get(self.endpoint, params=params).json()
        if not isinstance(response, dict) or not isinstance(response.get("jobs"), list):
            raise ValueError("Remotive response did not contain a jobs list")
        jobs = []
        for item in response["jobs"][:limit]:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            jobs.append(
                Job(
                    source=self.name,
                    source_job_id=text_or_none(item.get("id")),
                    title=str(item.get("title", "")).strip(),
                    company=str(item.get("company_name", "")).strip(),
                    url=str(item["url"]),
                    source_website=str(item["url"]),
                    company_website=text_or_none(item.get("company_url")),
                    company_logo_url=text_or_none(item.get("company_logo")),
                    location=text_or_none(item.get("candidate_required_location")),
                    remote_eligibility=text_or_none(item.get("candidate_required_location")),
                    work_arrangement="remote",
                    employment_type=text_or_none(item.get("job_type")),
                    category=text_or_none(item.get("category")),
                    skills=list_or_empty(item.get("tags")),
                    description=clean_html(item.get("description")),
                    published_at=text_or_none(item.get("publication_date")),
                )
            )
        return [job for job in jobs if job.title and job.company]
