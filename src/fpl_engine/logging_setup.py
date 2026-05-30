"""Structured logging with secret redaction.

Emits one JSON object per line (or plain text when ``log_json`` is false).
A redaction filter scrubs any known secret plaintext from every record so
credentials cannot leak into logs even if accidentally interpolated.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from .config import get_settings

_REDACTED = "***REDACTED***"
_RESERVED = set(logging.makeLogRecord({}).__dict__)


class RedactionFilter(logging.Filter):
    """Replace known secret plaintexts anywhere in the formatted message."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        # Longest first so overlapping secrets redact fully.
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            msg = record.getMessage()
            for secret in self._secrets:
                if secret in msg:
                    msg = msg.replace(secret, _REDACTED)
            record.msg = msg
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Promote structured extras passed via logger(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def setup_logging(force: bool = False) -> None:
    """Configure the root logger. Idempotent unless ``force`` is set."""
    global _configured
    if _configured and not force:
        return

    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactionFilter(settings.secret_values()))
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)
    # httpx logs each request URL at INFO; some providers carry their API key as
    # a query param, so silence these to WARNING (the redaction filter is the
    # backstop, this removes the single point of failure).
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
