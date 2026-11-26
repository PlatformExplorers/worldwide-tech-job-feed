"""Source scheduling, baseline handling, filtering, and publication orchestration."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timezone
from typing import Any

from src.config import AppConfig
from src.discord_client import DiscordClient, DiscordDeliveryError
from src.filters import is_recent, is_relevant
from src.models import Job
from src.state import JobState, fingerprints
from src.utils.url_utils import valid_http_url

LOGGER = logging.getLogger(__name__)

SOURCE_MODULES = {
    "arbeitnow": ("src.sources.arbeitnow", "ArbeitnowSource"),
    "jobicy": ("src.sources.jobicy", "JobicySource"),
    "remotive": ("src.sources.remotive", "RemotiveSource"),
    "greenhouse": ("src.sources.greenhouse", "GreenhouseSource"),
    "lever": ("src.sources.lever", "LeverSource"),
    "rss": ("src.sources.rss", "RSSSource"),
}


def source_instance(name: str, config: AppConfig):
    if name not in SOURCE_MODULES:
        raise ValueError(f"Unknown source: {name}")
    module_name, class_name = SOURCE_MODULES[name]
    source_class = getattr(importlib.import_module(module_name), class_name)
    return source_class(config, config.sources.get(name, {}))


def _interval_elapsed(last_success: str | None, interval_minutes: int) -> bool:
    if not last_success:
        return True
    try:
        previous = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
    except ValueError:
        return True
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - previous.astimezone(timezone.utc)
    return elapsed.total_seconds() >= interval_minutes * 60


def collect_sources(
    config: AppConfig,
    state: JobState,
    *,
    source_filter: str | None = None,
    check_only: bool = False,
) -> tuple[dict[str, int | str], list[Job]]:
    outcomes: dict[str, int | str] = {}
    candidates: list[Job] = []
    current_run_fingerprints: set[str] = set()
    names = [source_filter] if source_filter else list(SOURCE_MODULES)
    for name in names:
        options: dict[str, Any] = config.sources.get(name, {})
        if not source_filter and not options.get("enabled", False):
            continue
        if not check_only and not source_filter:
            interval = int(options.get("poll_interval_minutes", 60))
            if not _interval_elapsed(state.last_success.get(name), interval):
                outcomes[name] = "skipped: polling interval"
                continue
        try:
            jobs = source_instance(name, config).fetch()
            if check_only:
                outcomes[name] = len(jobs)
                continue
            baseline = name not in state.initialized_sources
            accepted = 0
            fresh = 0
            for job in jobs:
                if not valid_http_url(job.url):
                    LOGGER.warning(
                        "%s returned an unsafe or invalid job link; listing skipped", name
                    )
                    continue
                if not is_relevant(job, config) or not is_recent(job, config.max_job_age_days):
                    continue
                job_fingerprints = fingerprints(job)
                already_persisted = bool(state.seen.intersection(job_fingerprints))
                duplicate_in_run = bool(current_run_fingerprints.intersection(job_fingerprints))
                current_run_fingerprints.update(job_fingerprints)
                accepted += 1
                if (baseline and not config.first_run_backfill) or already_persisted:
                    state.seen.update(job_fingerprints)
                    continue
                if duplicate_in_run:
                    continue
                candidates.append(job)
                fresh += 1
            if baseline:
                state.initialized_sources.add(name)
            state.last_success[name] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if baseline:
                LOGGER.info("%s baseline fingerprints recorded: %d listings", name, accepted)
            else:
                LOGGER.info("%s fetched %d relevant listings; %d are new", name, accepted, fresh)
            outcomes[name] = fresh
        except Exception as exc:
            LOGGER.error("%s fetch failed: %s", name, type(exc).__name__)
            outcomes[name] = f"error: {type(exc).__name__}"
    return outcomes, candidates


def run(
    config: AppConfig, state: JobState, *, source_filter: str | None = None
) -> dict[str, int | str]:
    if not config.discord_webhook_url:
        LOGGER.error("DISCORD_WEBHOOK_URL is not configured")
        return {"error": "DISCORD_WEBHOOK_URL is not configured"}
    outcomes, candidates = collect_sources(config, state, source_filter=source_filter)
    client = DiscordClient(config)
    published = 0
    for job in candidates[: config.max_posts_per_run]:
        try:
            client.send_job(job)
            state.mark_seen(job)
            published += 1
        except DiscordDeliveryError as exc:
            LOGGER.error("Discord delivery failed: %s", str(exc))
            outcomes["discord_error"] = "delivery failed; job remains eligible next run"
            break
    outcomes["published"] = published
    outcomes["eligible_again_next_run"] = max(len(candidates) - published, 0)
    return outcomes
