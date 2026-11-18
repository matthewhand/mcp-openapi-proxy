"""Bounded, data-independent operational logging for MCP/OpenAPI calls.

Do not log credential/header names or values, spec content, request URLs,
query/body data, prompt text, tool names or exception messages. All dynamic
fields below are converted to a small, explicit set of safe primitives.
"""
import math
import time

from .logging_setup import logger

_HTTP_METHODS = frozenset({
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE",
})
_STAGES = frozenset({"sending", "completed"})


def log_http_event(stage, method=None, status=None, started=None):
    """Log only whitelisted method, numeric HTTP status and elapsed time."""
    safe_stage = stage if type(stage) is str and stage in _STAGES else "unknown"
    safe_method = method if type(method) is str and method in _HTTP_METHODS else "OTHER"
    safe_status = status if type(status) is int and 100 <= status <= 599 else 0
    elapsed = 0
    if type(started) in (int, float) and math.isfinite(started):
        elapsed = min(86_400_000, max(0, int((time.monotonic() - started) * 1000)))
    logger.debug(
        "http_event=%s method=%s status=%d elapsed_ms=%d",
        safe_stage, safe_method, safe_status, elapsed,
    )
