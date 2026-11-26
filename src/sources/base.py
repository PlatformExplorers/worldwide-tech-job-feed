"""Common HTTP handling for public job feeds."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import requests

from src.config import AppConfig
from src.models import Job
from src.utils.retry import retry_delay

LOGGER = logging.getLogger(__name__)


class JobSource(ABC):
    name: str

    def __init__(self, config: AppConfig, options: dict[str, Any]) -> None:
        self.config = config
        self.options = options
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "WorldwideTechJobFeed/0.1 (+https://github.com)"}
        )

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Fetch and normalize listings."""

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        attempts = int(self.options.get("request_retries", self.config.request_retries)) + 1
        for attempt in range(attempts):
            response: requests.Response | None = None
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.config.request_timeout,
                    allow_redirects=allow_redirects,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 < attempts:
                        time.sleep(retry_delay(response, attempt))
                        continue
                if 300 <= response.status_code < 400 and not allow_redirects:
                    raise ValueError("Redirects are not allowed for configured RSS feeds")
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(retry_delay(response, attempt))
        raise RuntimeError(f"{self.name} request exhausted retries")


def clean_html(value: str | None, limit: int = 3000) -> str | None:
    if not value:
        return None
    import re
    from html import unescape

    text = unescape(re.sub(r"<[^>]*>", " ", value))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def text_or_none(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def list_or_empty(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []
