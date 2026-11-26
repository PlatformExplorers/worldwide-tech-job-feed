"""Adapter for the publicly documented Arbeitnow job board API."""

from __future__ import annotations

from typing import Any

from src.models import Job
from src.sources.base import JobSource, clean_html, list_or_empty, text_or_none


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    endpoint = "https://www.arbeitnow.com/api/job-board-api"

    def fetch(self) -> list[Job]:
        result: list[Job] = []
        page_limit = min(int(self.options.get("max_pages", 2)), 10)
        for page in range(1, page_limit + 1):
            data: Any = self.get(self.endpoint, params={"page": page}).json()
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise ValueError("Arbeitnow response did not contain a jobs list")
            for item in data["data"]:
                job = self._normalize(item)
                if job:
                    result.append(job)
            if not (data.get("links") or {}).get("next"):
                break
        return result

    def _normalize(self, item: Any) -> Job | None:
        if not isinstance(item, dict):
            return None
        url = text_or_none(item.get("url"))
        title = text_or_none(item.get("title"))
        company = text_or_none(item.get("company_name"))
        if not url or not title or not company:
            return None
        location = text_or_none(item.get("location"))
        remote = bool(item.get("remote"))
        return Job(
            source=self.name,
            source_website="https://www.arbeitnow.com",
            source_job_id=text_or_none(item.get("slug")),
            title=title,
            company=company,
            url=url,
            location=location,
            remote_eligibility="Remote; geographic restrictions not specified" if remote else None,
            work_arrangement="remote" if remote else None,
            employment_type=", ".join(list_or_empty(item.get("job_types"))) or None,
            category=", ".join(list_or_empty(item.get("tags"))) or None,
            skills=list_or_empty(item.get("tags")),
            description=clean_html(item.get("description")),
            published_at=text_or_none(item.get("created_at")),
        )
