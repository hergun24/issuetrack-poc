"""Rate limiting + structured logging."""

import json
import logging
import sys
import threading
import time

logger = logging.getLogger("issuetrack")

# ---------------------------------------------------------------------------
# Sliding-window in-process rate limiter (SEC-002 abuse control, MVP scope)


class SlidingWindowLimiter:
    """Per-key sliding-window counter. Documented limitation: resets on restart."""

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window = window_seconds
        self._buckets: dict[str, list] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(key, [])
            cutoff = now - self.window
            while bucket and bucket[0] < cutoff:
                bucket.pop(0)
            if len(bucket) >= self.max_events:
                return False
            bucket.append(now)
            return True


auth_limiter = SlidingWindowLimiter(max_events=20, window_seconds=60.0)


# ---------------------------------------------------------------------------
# Structured logging without secrets (SEC-033 / NFR-010)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # redact sensitive keys if present in extra
        for k, v in vars(record).items():
            if k in ("token", "password", "authorization"):
                continue
            if k not in ("name", "msg", "args", "levelname", "levelno", "pathname",
                         "filename", "module", "exc_info", "exc_text", "stack_info",
                         "lineno", "funcName", "created", "msecs", "relativeCreated",
                         "thread", "threadName", "process", "processName", "taskName",
                         "message", "asctime"):
                payload[k] = v
        return json.dumps(payload)


def setup_logging():
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
