"""Bounded outbound tool execution; no retries, redirects or private diagnostics.

A disposable process bounds DNS/connect/read/decompression and total execution.
Async handlers run it off the event loop and cancel/reap it when cancelled.
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
HARD_DEADLINE_SECONDS = 15
MAX_CONCURRENT = 4
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


class DispatchFailure(requests.exceptions.RequestException):
    """A fixed, sanitized execution failure."""


@dataclass
class ResponseSnapshot:
    text: str
    status_code: int

    def raise_for_status(self):
        if self.status_code >= 400:
            raise DispatchFailure("Upstream request failed")


def _worker(payload):

    try:
        # Bound decompressor/parser memory on platforms with resource limits.
        try:
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            cap = 512 * 1024 * 1024
            bounded = tuple(cap if value == resource.RLIM_INFINITY else min(value, cap)
                            for value in (soft, hard))
            resource.setrlimit(resource.RLIMIT_AS, bounded)
        except ImportError:
            pass
        options = dict(payload)
        options.update(timeout=(3, 5), stream=True)
        with requests.request(allow_redirects=False, **options) as response:
            status = response.status_code
            if type(status) is not int or not 100 <= status < 600:
                raise DispatchFailure("Invalid upstream status")
            if 300 <= status < 400:
                return {"ok": False, "error": "redirect"}
            if status < 200:
                raise DispatchFailure("Invalid final upstream status")
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            # HEAD describes a hypothetical GET body, not transferred bytes.
            if length is not None and str(options.get("method", "")).upper() != "HEAD":
                if not length.isascii() or not length.isdecimal() or len(length) > 10:
                    raise DispatchFailure("Invalid upstream length")
                if int(length) > MAX_RESPONSE_BYTES:
                    raise DispatchFailure("Upstream response too large")
            data = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise DispatchFailure("Upstream response too large")
                data.extend(chunk)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if data and (content_type == "application/json" or content_type.endswith("+json")):
                json.loads(bytes(data))
            return {"ok": True, "status": response.status_code,
                    "text": bytes(data).decode(response.encoding or "utf-8",
                                              errors="replace")}
    except Exception:
        return {"ok": False}


def _worker_environment():
    # No unrelated API credentials or dotenv discovery in the disposable worker.
    names = {"PATH", "PYTHONPATH", "PYTHONHOME", "SYSTEMROOT", "WINDIR",
             "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
             "CURL_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
             "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    env = {key: value for key, value in os.environ.items() if key in names}
    env.update(PYTHON_DOTENV_DISABLED="1", PYTHONDONTWRITEBYTECODE="1",
               NETRC=os.devnull)
    return env


def bounded_request(_cancel=None, **kwargs):
    """One process per call, fail fast when full, and always kill/reap on exit."""
    allowed = {"method", "url", "headers", "params", "json", "verify"}
    if (not kwargs.get("method") or not kwargs.get("url")
            or set(kwargs) - allowed):
        raise DispatchFailure("Invalid outbound request")
    try:
        body = json.dumps(kwargs, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise DispatchFailure("Invalid outbound request") from None
    if len(body) > MAX_REQUEST_BYTES:
        raise DispatchFailure("Outbound request too large")
    if not _slots.acquire(blocking=False):
        raise DispatchFailure("Outbound concurrency limit exceeded")
    child = None
    try:
        if _cancel is not None and _cancel.is_set():
            raise DispatchFailure("Outbound request cancelled")
        deadline = time.monotonic() + HARD_DEADLINE_SECONDS
        child = subprocess.Popen(
            [sys.executable, "-B", str(Path(__file__).resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=_worker_environment(),
        )
        first = True
        while True:
            remaining = deadline - time.monotonic()
            if _cancel is not None and _cancel.is_set():
                raise DispatchFailure("Outbound request cancelled")
            if remaining <= 0:
                raise DispatchFailure("Upstream total deadline exceeded")
            try:
                output, _ = child.communicate(
                    body if first else None, timeout=min(remaining, 0.05))
                break
            except subprocess.TimeoutExpired:
                first = False
        if child.returncode != 0 or len(output) > MAX_RESPONSE_BYTES * 6 + 1024:
            raise DispatchFailure("Upstream worker failed")
        try:
            result = json.loads(output)
            if type(result) is dict and result.get("error") == "redirect":
                from .request_security import RedirectRefused
                raise RedirectRefused("Upstream redirect refused")
            if (type(result) is not dict or result.get("ok") is not True
                    or type(result.get("text")) is not str
                    or type(result.get("status")) is not int
                    or not 200 <= result["status"] < 300
                    or len(result["text"].encode("utf-8")) > MAX_RESPONSE_BYTES * 3):
                raise ValueError
        except (ValueError, UnicodeError, TypeError):
            raise DispatchFailure("Upstream request failed") from None
        return ResponseSnapshot(result["text"], result["status"])
    except OSError as error:
        if isinstance(error, requests.exceptions.RequestException):
            raise
        raise DispatchFailure("Upstream worker unavailable") from None
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate()
        _slots.release()


async def run_cancellable(function, **kwargs):
    """Keep MCP discovery responsive; cancellation terminates the worker."""
    cancel = threading.Event()
    task = asyncio.create_task(
        asyncio.to_thread(function, _cancel=cancel, **kwargs))
    def observe(done):
        if not done.cancelled():
            done.exception()
    task.add_done_callback(observe)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        try:
            await asyncio.shield(task)
        except Exception:
            pass
        raise


async def bounded_request_async(**kwargs):
    return await run_cancellable(bounded_request, **kwargs)


if __name__ == "__main__":
    try:
        payload = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        if len(payload) > MAX_REQUEST_BYTES:
            raise ValueError
        args = json.loads(payload)
        if type(args) is not dict:
            raise ValueError
        result = _worker(args)
        sys.stdout.write(json.dumps(result, ensure_ascii=True))
    except Exception:
        sys.stdout.write('{"ok":false}')
