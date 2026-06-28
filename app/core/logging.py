from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from typing import Any

from app.config import settings
from app.core.redaction import redact


class TomewardenFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "level": record.levelname,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, Mapping):
            event.update(redact(extra))

        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)

        if settings.log_format == "json":
            return json.dumps(event, sort_keys=True, separators=(",", ":"))

        parts = [f"level={event.pop('level')}", f"message={json.dumps(event.pop('message'))}"]
        parts.extend(f"{key}={json.dumps(value)}" for key, value in sorted(event.items()))
        return " ".join(parts)


def configure_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(settings.log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(TomewardenFormatter())
    root.addHandler(handler)


def log_info(message: str, **fields: Any) -> None:
    logging.getLogger("tomewarden").info(message, extra={"fields": fields})


def log_error(message: str, **fields: Any) -> None:
    logging.getLogger("tomewarden").error(message, extra={"fields": fields})

