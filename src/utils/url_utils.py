"""Canonicalize links while preserving application-relevant query parameters."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "apikey",
    "api_key",
    "auth",
    "authorization",
    "key",
    "password",
    "passwd",
    "session",
    "sessionid",
    "sig",
    "signature",
    "token",
}


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Job URL must be an absolute HTTP(S) URL")
    host = parsed.hostname.lower()
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/") or "/"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
    ]
    return urlunsplit((parsed.scheme.lower(), host, path, urlencode(query), ""))


def valid_http_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlsplit(url.strip())
        host = parsed.hostname
        if (
            parsed.scheme.lower() != "https"
            or not host
            or any(ord(char) < 32 or char.isspace() for char in url)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or host.lower().endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
            or host.lower() in {"localhost", "metadata.google.internal"}
        ):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address or "." not in host:
            return False
        if any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
            return False
        canonicalize_url(url)
    except (ValueError, TypeError, UnicodeError):
        return False
    return True


def valid_discord_webhook_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"discord.com", "discordapp.com"}
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.query == ""
            and parsed.fragment == ""
            and re.fullmatch(r"/api/webhooks/\d+/[A-Za-z0-9_-]+", parsed.path) is not None
        )
    except (ValueError, TypeError):
        return False
