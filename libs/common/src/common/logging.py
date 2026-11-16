"""Structured JSON logs. One JSON object per line, always with request_id / workspace_id / user_id when known.

Never log tokens, passwords or full request bodies.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Set by the request middleware in each service's main.py; read by the formatter.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
workspace_id_var: ContextVar[str | None] = ContextVar("workspace_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
            "workspace_id": workspace_id_var.get(),
            "user_id": user_id_var.get(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
