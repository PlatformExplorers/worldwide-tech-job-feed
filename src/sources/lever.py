"""Adapter for configured Lever public postings sites."""

from __future__ import annotations

from typing import Any

from src.models import Job
from src.sources.base import JobSource, clean_html, text_or_none


class LeverSource(JobSource):
    name = "lever"

    def fetch(self) -> list[Job]:
        sites = self.options.get("sites", [])
        if not isinstance(sites, list):
            raise ValueError("Lever sites must be a list of site names")
        result = []
        for site in sites:
            token = str(site).strip()
            if not token or not token.replace("-", "").replace("_", "").isalnum():
                raise ValueError("Invalid Lever site name")
            payload: Any = self.get(
                f"https://api.lever.co/v0/postings/{token}",
                params={"mode": "json"},
            ).json()
            if not isinstance(payload, list):
                raise ValueError(f"Lever site {token} returned an invalid response")
            company_name = str(self.options.get("company_names", {}).get(token, token))
            for item in payload:
                if not isinstance(item, dict):
                    continue
                title, url = text_or_none(item.get("text")), text_or_none(item.get("hostedUrl"))
                if not title or not url:
                    continue
                categories = item.get("categories") or {}
                result.append(
                    Job(
                        source=self.name,
                        source_job_id=text_or_none(item.get("id")),
                        title=title,
                        company=company_name,
                        url=url,
                        location=text_or_none(categories.get("location")),
                        employment_type=text_or_none(categories.get("commitment")),
                        category=text_or_none(
                            categories.get("team") or categories.get("department")
                        ),
                        description=clean_html(
                            item.get("descriptionPlain") or item.get("description")
                        ),
                        published_at=text_or_none(item.get("createdAt")),
                    )
                )
        return result
