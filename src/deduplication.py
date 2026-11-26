"""Conservative cross-board duplicate comparison."""

from __future__ import annotations

from src.models import Job, normalize_text


def description_similarity(left: str | None, right: str | None) -> float:
    normalized_left = normalize_text(left)
    normalized_right = normalize_text(right)
    if normalized_left and normalized_left == normalized_right:
        return 1.0
    left_words = set(normalized_left.split())
    right_words = set(normalized_right.split())
    if min(len(left_words), len(right_words)) < 12:
        return 0.0
    intersection = len(left_words & right_words)
    return intersection / max(len(left_words | right_words), 1)


def likely_duplicate(candidate: Job, existing: Job, threshold: float = 0.88) -> bool:
    # Exact title, employer, and location are mandatory to avoid merging distinct openings.
    if candidate.normalized_key() != existing.normalized_key():
        return False
    return description_similarity(candidate.description, existing.description) >= threshold
