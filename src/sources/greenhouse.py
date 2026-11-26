"""Adapter for configured Greenhouse public job boards."""

from __future__ import annotations

from typing import Any

from src.models import Job
from src.sources.base import JobSource, clean_html, text_or_none


class GreenhouseSource(JobSource):
    name = "greenhouse"

    def fetch(self) -> list[Job]:
        boards = self.options.get("boards", [])
        if not isinstance(boards, list):
            raise ValueError("Greenhouse boards must be a list of board tokens")
        result = []
        for board in boards:
            token = str(board).strip()
            if not token or not token.replace("-", "").replace("_", "").isalnum():
                raise ValueError("Invalid Greenhouse board token")
            data: Any = self.get(
                f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                params={"content": "true"},
            ).json()
            if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                raise ValueError(f"Greenhouse board {token} returned an invalid response")
            company_name = str(self.options.get("company_names", {}).get(token, token))
            for item in data["jobs"]:
                if not isinstance(item, dict):
                    continue
                title, url = text_or_none(item.get("title")), text_or_none(item.get("absolute_url"))
                if not title or not url:
                    continue
                location_data = item.get("location") or {}
                result.append(
                    Job(
                        source=self.name,
                        source_job_id=text_or_none(item.get("id")),
                        title=title,
                        company=company_name,
                        url=url,
                        location=text_or_none(location_data.get("name")),
                        description=clean_html(item.get("content")),
                        published_at=text_or_none(item.get("updated_at")),
                    )
                )
        return result
