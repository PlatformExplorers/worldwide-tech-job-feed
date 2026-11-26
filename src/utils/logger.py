"""Logging setup with defensive redaction for credentials and webhook URLs."""

from __future__ import annotations

import logging
import os
import re


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        secret = os.getenv("DISCORD_WEBHOOK_URL", "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
        message = re.sub(
            r"(https://discord(?:app)?\.com/api/webhooks/)[^/\s]+/[^?\s]+",
            r"\1[REDACTED]",
            message,
        )
        record.msg = message
        record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter())
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
        force=True,
    )
