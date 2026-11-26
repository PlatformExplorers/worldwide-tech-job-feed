"""YAML configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.utils.url_utils import valid_discord_webhook_url


@dataclass(slots=True)
class AppConfig:
    raw: dict[str, Any]
    state_path: str
    discord_webhook_url: str | None
    max_posts_per_run: int
    max_job_age_days: int
    first_run_backfill: bool
    request_timeout: float
    request_retries: int
    logging_level: str

    @property
    def sources(self) -> dict[str, Any]:
        return self.raw.get("sources", {})

    @property
    def filters(self) -> dict[str, Any]:
        return self.raw.get("filters", {})


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    with Path(path).open(encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    if not isinstance(raw, dict):
        raise ValueError("Configuration root must be a YAML mapping")

    runtime = raw.get("runtime", {})
    discord = raw.get("discord", {})
    sources = raw.get("sources", {})
    filters = raw.get("filters", {})
    logging_options = raw.get("logging", {})
    if not all(
        isinstance(section, dict)
        for section in (runtime, discord, sources, filters, logging_options)
    ):
        raise ValueError("runtime, discord, sources, filters, and logging must be mappings")
    maximum = runtime.get("max_posts_per_run", 40)
    age = runtime.get("max_job_age_days", 30)
    timeout = runtime.get("request_timeout_seconds", 20)
    retries = runtime.get("request_retries", 3)
    if not isinstance(maximum, int) or not 1 <= maximum <= 200:
        raise ValueError("runtime.max_posts_per_run must be an integer from 1 to 200")
    if not isinstance(age, int) or age < 0:
        raise ValueError("runtime.max_job_age_days must be a non-negative integer")
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
        raise ValueError("runtime.request_timeout_seconds must be from 0 to 120")
    if not isinstance(retries, int) or not 0 <= retries <= 8:
        raise ValueError("runtime.request_retries must be an integer from 0 to 8")
    backfill = runtime.get("first_run_backfill", False)
    if not isinstance(backfill, bool):
        raise ValueError("runtime.first_run_backfill must be a boolean")

    for name, options in sources.items():
        if not isinstance(options, dict) or not isinstance(options.get("enabled", False), bool):
            raise ValueError(f"sources.{name} must be a mapping with boolean enabled")
        interval = options.get("poll_interval_minutes", 60)
        if not isinstance(interval, int) or not 1 <= interval <= 1440:
            raise ValueError(f"sources.{name}.poll_interval_minutes must be from 1 to 1440")
        source_retries = options.get("request_retries", retries)
        if not isinstance(source_retries, int) or not 0 <= source_retries <= 8:
            raise ValueError(f"sources.{name}.request_retries must be an integer from 0 to 8")
        if name == "arbeitnow" and (
            not isinstance(options.get("max_pages", 2), int)
            or not 1 <= options.get("max_pages", 2) <= 10
        ):
            raise ValueError("sources.arbeitnow.max_pages must be an integer from 1 to 10")
        if name == "jobicy" and (
            not isinstance(options.get("count", 50), int) or not 1 <= options.get("count", 50) <= 50
        ):
            raise ValueError("sources.jobicy.count must be an integer from 1 to 50")
        if name == "remotive" and (
            not isinstance(options.get("limit", 100), int)
            or not 1 <= options.get("limit", 100) <= 100
        ):
            raise ValueError("sources.remotive.limit must be an integer from 1 to 100")
        if name == "himalayas" and (
            not isinstance(options.get("max_pages", 5), int)
            or not 1 <= options.get("max_pages", 5) <= 10
        ):
            raise ValueError("sources.himalayas.max_pages must be an integer from 1 to 10")
        if name == "remotive" and options.get("enabled", False) and interval < 360:
            raise ValueError("sources.remotive.poll_interval_minutes must be at least 360")
        if name == "himalayas" and options.get("enabled", False) and interval < 120:
            raise ValueError("sources.himalayas.poll_interval_minutes must be at least 120")
        if name == "remotive" and options.get("enabled", False) and source_retries != 0:
            raise ValueError("Enabled Remotive sources require request_retries: 0")
        for list_name, list_maximum in (("boards", 100), ("sites", 100), ("feeds", 50)):
            values = options.get(list_name)
            if values is not None and (not isinstance(values, list) or len(values) > list_maximum):
                raise ValueError(
                    f"sources.{name}.{list_name} must be a list with at most {list_maximum} entries"
                )
    for key in ("include_keywords", "job_titles", "exclude_keywords", "countries"):
        value = filters.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"filters.{key} must be a list of strings")
    if not isinstance(filters.get("remote_only", False), bool):
        raise ValueError("filters.remote_only must be a boolean")

    if discord.get("webhook_url"):
        raise ValueError("Configure Discord credentials only through DISCORD_WEBHOOK_URL")
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if webhook and not valid_discord_webhook_url(webhook):
        raise ValueError("Discord webhook URL must use the official Discord webhook endpoint")
    discord_retries = discord.get("retries", 4)
    if not isinstance(discord_retries, int) or not 0 <= discord_retries <= 8:
        raise ValueError("discord.retries must be an integer from 0 to 8")

    return AppConfig(
        raw=raw,
        state_path=os.getenv("STATE_PATH", runtime.get("state_path", "data/seen-hashes.json")),
        discord_webhook_url=webhook,
        max_posts_per_run=maximum,
        max_job_age_days=age,
        first_run_backfill=backfill,
        request_timeout=float(timeout),
        request_retries=retries,
        logging_level=str(logging_options.get("level", "INFO")),
    )
