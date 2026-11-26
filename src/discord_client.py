"""Discord webhook embed formatting and bounded delivery retries."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import requests

from src.config import AppConfig
from src.models import Job
from src.utils.retry import retry_delay
from src.utils.url_utils import valid_discord_webhook_url, valid_http_url

LOGGER = logging.getLogger(__name__)

CATEGORY_COLORS = {
    "cybersecurity": 0xD7263D,
    "software engineering": 0x5865F2,
    "cloud computing": 0x00A6A6,
    "data science": 0x7B2CBF,
    "it support": 0xF4A261,
}


class DiscordDeliveryError(RuntimeError):
    """Raised when Discord rejects a webhook message after bounded retries."""


def build_embed(job: Job, config: AppConfig) -> dict[str, Any]:
    if not valid_http_url(job.url):
        raise ValueError("Job application link must be a safe HTTPS URL")
    location = job.location or ", ".join(filter(None, (job.city, job.country))) or "Not specified"
    fields = [
        {"name": "Position", "value": _clip(job.title, 256), "inline": True},
        {"name": "Company", "value": _clip(job.company, 256), "inline": True},
        {"name": "Location", "value": _clip(location, 256), "inline": True},
        {
            "name": "Work arrangement",
            "value": _clip(job.work_arrangement or job.remote_eligibility or "Not specified", 256),
            "inline": True,
        },
        {"name": "Salary", "value": _clip(_salary(job), 256), "inline": True},
        {
            "name": "Employment",
            "value": _clip(job.employment_type or "Not specified", 256),
            "inline": True,
        },
    ]
    if job.experience_level:
        fields.append(
            {"name": "Experience", "value": _clip(job.experience_level, 256), "inline": True}
        )
    if job.skills:
        fields.append(
            {"name": "Skills", "value": _clip(", ".join(job.skills), 1024), "inline": False}
        )
    if job.published_at:
        fields.append({"name": "Posted", "value": _clip(job.published_at, 256), "inline": True})
    source_value = (
        f"[{job.source.title()}]({job.source_website})"
        if valid_http_url(job.source_website)
        else job.source.title()
    )
    fields.append({"name": "Source", "value": _clip(source_value, 256), "inline": True})
    fields.append(
        {
            "name": "Apply / original listing",
            "value": f"[Open source link]({job.url})",
            "inline": False,
        }
    )
    fields = fields[:25]

    embed: dict[str, Any] = {
        "title": f"🌍 NEW TECHNOLOGY JOB OPPORTUNITY · {_clip(job.title, 180)}",
        "url": job.url,
        "color": _color(job.category),
        "fields": fields,
        "description": _clip(job.description or "No description provided by the source.", 1000),
        "footer": {"text": "Apply at the original listing"},
    }
    if job.company_logo_url and valid_http_url(job.company_logo_url):
        embed["thumbnail"] = {"url": job.company_logo_url}
    if config.raw.get("discord", {}).get("show_timestamp", True):
        embed["timestamp"] = _timestamp(job.published_at)
    return embed


def _clip(value: str, maximum: int) -> str:
    return value if len(value) <= maximum else value[: maximum - 1].rstrip() + "…"


def _salary(job: Job) -> str:
    if job.salary_min is None and job.salary_max is None:
        return "Not disclosed"
    amount = " - ".join(
        f"{value:,.0f}" for value in (job.salary_min, job.salary_max) if value is not None
    )
    return " ".join(filter(None, (job.salary_currency, amount, job.salary_period)))


def _color(category: str | None) -> int:
    text = (category or "").lower()
    for label, color in CATEGORY_COLORS.items():
        if label in text:
            return color
    return 0x2F3136


def _timestamp(value: str | None) -> str:
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            pass
    return datetime.now().astimezone().isoformat()


class DiscordClient:
    def __init__(self, config: AppConfig, session: requests.Session | None = None) -> None:
        if not config.discord_webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL is not configured")
        if not valid_discord_webhook_url(config.discord_webhook_url):
            raise ValueError("DISCORD_WEBHOOK_URL is not a valid Discord webhook URL")
        self.config = config
        self.url = config.discord_webhook_url
        self.session = session or requests.Session()
        self.retries = int(config.raw.get("discord", {}).get("retries", 4))

    def send_job(self, job: Job) -> str | None:
        payload = {
            "embeds": [build_embed(job, self.config)],
            "allowed_mentions": {"parse": []},
        }
        return self._send(payload)

    def send_test(self) -> str | None:
        preview = Job(
            source="Test preview",
            title="TEST PREVIEW — Software Engineer",
            company="Example Company (not real)",
            url="https://example.com/test-job",
            location="Remote (test)",
            work_arrangement="Remote",
            employment_type="Full-time (test)",
            category="software engineering",
            skills=["Python", "REST APIs"],
            description="Preview only. This is sample content, not a real vacancy.",
        )
        return self._send(
            {
                "content": "TEST PREVIEW — sample embed only; this is not a real vacancy.",
                "embeds": [build_embed(preview, self.config)],
                "allowed_mentions": {"parse": []},
            }
        )

    def _send(self, payload: dict[str, Any]) -> str | None:
        attempts = self.retries + 1
        for attempt in range(attempts):
            response: requests.Response | None = None
            try:
                response = self.session.post(
                    self.url,
                    params={"wait": "true"},
                    json=payload,
                    timeout=self.config.request_timeout,
                )
                if (
                    response.status_code == 429 or response.status_code >= 500
                ) and attempt + 1 < attempts:
                    time.sleep(retry_delay(response, attempt))
                    continue
                if (
                    response.status_code >= 400
                    and response.status_code < 500
                    and response.status_code != 429
                ):
                    raise DiscordDeliveryError(
                        f"Discord rejected the message with HTTP {response.status_code}"
                    )
                response.raise_for_status()
                if response.status_code == 204:
                    return None
                try:
                    body = response.json()
                except ValueError:
                    return None
                return str(body["id"]) if isinstance(body, dict) and body.get("id") else None
            except DiscordDeliveryError:
                raise
            except requests.RequestException as exc:
                if attempt + 1 >= attempts:
                    status = response.status_code if response else "network error"
                    raise DiscordDeliveryError(
                        f"Discord webhook delivery failed with HTTP {status}"
                    ) from exc
                time.sleep(retry_delay(response, attempt))
        raise DiscordDeliveryError("Discord webhook delivery retries exhausted")
