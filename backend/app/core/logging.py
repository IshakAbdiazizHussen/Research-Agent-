"""Logging setup (Feature 1: User Identity & Data Foundation).

Per docs/constraints.md ("Data handling rules") and this feature's Security
notes: application logs must never contain a customer's raw email address or
other PII. Two layers of defense here:

1. Callers should log user identity by id, not by email, as a matter of
   convention (e.g. `logger.info("run created", extra={"user_id": user.id})`).
2. As a backstop, `_RedactPIIFilter` scrubs anything that looks like an email
   address out of every log record before it's emitted, so a mistake at the
   call site doesn't leak PII into logs.
"""

import logging
import re
import sys

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_REDACTED = "[REDACTED_EMAIL]"


class _RedactPIIFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.msg)
        if record.args:
            record.args = tuple(self._redact(arg) for arg in record.args)
        return True

    @staticmethod
    def _redact(value: object) -> object:
        if isinstance(value, str) and "@" in value:
            return _EMAIL_RE.sub(_REDACTED, value)
        return value


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging once, at process startup (see app/main.py)."""
    root = logging.getLogger()
    root.setLevel(level)

    # Idempotent: don't stack duplicate handlers if called twice (e.g. tests).
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(_RedactPIIFilter())
    root.addHandler(handler)
