"""Logging setup: one line per event, key=value context, secrets never printed."""

import logging
import re
import sys

_SECRET_RE = re.compile(r"(Bearer\s+|Token[\"':=\s]+|x-api-key[\"':=\s]+)[A-Za-z0-9._\-:]{6,}", re.IGNORECASE)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _SECRET_RE.sub(r"\1***", super().format(record))


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
