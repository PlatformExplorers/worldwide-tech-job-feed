"""Bounded retry helpers for transient HTTP responses."""

from __future__ import annotations

import random
import time
from email.utils import parsedate_to_datetime

import requests


def retry_delay(response: requests.Response | None, attempt: int, maximum: float = 60.0) -> float:
    if response is not None:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return min(max(float(value), 0.0), maximum)
            except ValueError:
                try:
                    seconds = parsedate_to_datetime(value).timestamp() - time.time()
                    return min(max(seconds, 0.0), maximum)
                except (TypeError, ValueError, OverflowError):
                    pass
    return min((2**attempt) + random.random(), maximum)
