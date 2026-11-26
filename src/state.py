"""Persist only hashed identifiers needed to suppress repeat job listings."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from src.models import Job, normalize_text
from src.utils.url_utils import canonicalize_url

_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def fingerprints(job: Job) -> set[str]:
    candidates = [f"url\x1f{canonicalize_url(job.url)}"]
    if job.source_job_id:
        candidates.append(f"source\x1f{job.source}\x1f{job.source_job_id}")

    title, company, location = job.normalized_key()
    description = normalize_text(job.description)
    if title and company and location and len(description.split()) >= 8:
        candidates.append(f"role\x1f{title}\x1f{company}\x1f{location}\x1f{description}")

    return {hashlib.sha256(candidate.encode("utf-8")).hexdigest() for candidate in candidates}


class JobState:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.seen: set[str] = set()
        self.initialized_sources: set[str] = set()
        self.last_success: dict[str, str] = {}
        self.last_attempt: dict[str, str] = {}
        if self.path.is_file():
            self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read deduplication state: {type(exc).__name__}") from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported deduplication state format")
        fingerprints_data = data.get("fingerprints")
        sources = data.get("initialized_sources")
        last_success = data.get("last_success")
        last_attempt = data.get("last_attempt", {})
        if not isinstance(fingerprints_data, list) or not all(
            isinstance(item, str) and _FINGERPRINT_PATTERN.fullmatch(item)
            for item in fingerprints_data
        ):
            raise ValueError("Deduplication state contains invalid fingerprints")
        if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
            raise ValueError("Deduplication state contains invalid source markers")
        if not isinstance(last_success, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in last_success.items()
        ):
            raise ValueError("Deduplication state contains invalid polling markers")
        self.seen = set(fingerprints_data)
        self.initialized_sources = set(sources)
        self.last_success = last_success
        if not isinstance(last_attempt, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in last_attempt.items()
        ):
            raise ValueError("Deduplication state contains invalid polling attempt markers")
        self.last_attempt = last_attempt

    def has_seen(self, job: Job) -> bool:
        return bool(self.seen.intersection(fingerprints(job)))

    def mark_seen(self, job: Job) -> None:
        self.seen.update(fingerprints(job))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "initialized_sources": sorted(self.initialized_sources),
            "last_success": self.last_success,
            "last_attempt": self.last_attempt,
            "fingerprints": sorted(self.seen),
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                json.dump(payload, file, separators=(",", ":"), sort_keys=True)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
