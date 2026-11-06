"""Real fictional loopback HTTP, hard limits, lifecycle and event-loop checks."""
import asyncio
import contextlib
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mcp_openapi_proxy import bounded_http as transport
from mcp_openapi_proxy.request_security import RedirectRefused


@pytest.fixture
def api():
    started = threading.Event()
    started.authorizations = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_GET(self):
            started.authorizations.append(self.headers.get("Authorization"))
            path = self.path.split("?", 1)[0]
            if path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://forbidden.invalid/SYNTHETIC_SECRET")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = int(path[1:]) if path[1:].isdigit() else 200
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if path == "/large":
                self.send_header("Content-Length", str(transport.MAX_RESPONSE_BYTES + 1))
            elif path not in ("/trickle", "/unbounded", "/slow"):
                body = (b"not-json" if path == "/bad-json" else
                        b"" if status == 204 else b'{"ok":true}')
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            started.set()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                if path == "/trickle":
                    for _ in range(100):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.05)
                elif path == "/slow":
                    time.sleep(1.0)
                    self.wfile.write(b'{"ok":true}')
                elif path == "/unbounded":
                    for _ in range(140):
                        self.wfile.write(b" " * 8192)
                elif path != "/large":
                    self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as http:
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{http.server_port}", started
        finally:
            http.shutdown()
            thread.join(timeout=2)


def test_success_and_empty_are_success(api):
    base, _ = api
    assert json.loads(transport.bounded_request(method="GET", url=base+"/ok").text) == {"ok": True}
    result = transport.bounded_request(method="GET", url=base+"/204")
    assert result.status_code == 204 and result.text == ""


@pytest.mark.parametrize("path", ["/401", "/403", "/429", "/500", "/bad-json",
                                 "/large", "/unbounded"])
def test_http_and_body_failures_are_sanitized(path, api):
    base, _ = api
    with pytest.raises(transport.DispatchFailure) as error:
        transport.bounded_request(method="GET", url=base+path)
    assert "127.0.0.1" not in str(error.value)


def test_redirect_does_not_dispatch_to_forbidden_origin(api):
    base, _ = api
    with pytest.raises(RedirectRefused, match="redirect refused"):
        transport.bounded_request(method="GET", url=base+"/redirect")


def test_trickling_body_has_a_whole_request_deadline(api, monkeypatch):
    base, _ = api
    monkeypatch.setattr(transport, "HARD_DEADLINE_SECONDS", 0.5)
    before = time.monotonic()
    with pytest.raises(transport.DispatchFailure, match="total deadline"):
        transport.bounded_request(method="GET", url=base+"/trickle")
    assert time.monotonic() - before < 2


@pytest.mark.asyncio
async def test_cancel_reaps_worker_and_event_loop_stays_responsive(api, monkeypatch):
    base, started = api
    children = []
    original = subprocess.Popen
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(transport.subprocess, "Popen", spawn)
    task = asyncio.create_task(transport.bounded_request_async(method="GET", url=base+"/slow"))
    before = time.monotonic()
    await asyncio.sleep(0.05)
    assert time.monotonic() - before < 0.5
    while not started.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert children and all(child.poll() is not None for child in children)
    assert transport._slots.acquire(blocking=False)
    transport._slots.release()


def test_full_concurrency_limit_rejects_without_spawning(monkeypatch):
    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    monkeypatch.setattr(transport, "_slots", sem)
    def forbidden(*_args, **_kwargs):
        pytest.fail("must reject before launching another worker")
    monkeypatch.setattr(transport.subprocess, "Popen", forbidden)
    with pytest.raises(transport.DispatchFailure, match="concurrency"):
        transport.bounded_request(method="GET", url="http://fictional.invalid")


def test_invalid_and_oversized_requests_fail_before_network():
    for kwargs in [{"method": "GET"}, {"method": "GET", "url": "http://fictional.invalid", "timeout": None},
                   {"method": "POST", "url": "http://fictional.invalid", "json": "x"*transport.MAX_REQUEST_BYTES}]:
        with pytest.raises(transport.DispatchFailure):
            transport.bounded_request(**kwargs)


def test_concurrent_fastmcp_calls_keep_their_own_spec_and_origin(monkeypatch):
    """A paused A dispatch must not read B's global spec after B completes."""
    from concurrent.futures import ThreadPoolExecutor
    from mcp_openapi_proxy import server_fastmcp as fast
    spec_a = {"openapi": "3.0.3", "servers": [{"url": "https://a.synthetic.invalid"}],
              "paths": {"/safe": {"get": {}}}}
    spec_b = {"openapi": "3.0.3", "servers": [{"url": "https://b.synthetic.invalid"}],
              "paths": {"/safe": {"get": {}}}}
    monkeypatch.setattr(fast, "_SPEC_SNAPSHOTS", {"file:///synthetic/a.json": spec_a, "file:///synthetic/b.json": spec_b})
    original_identity = fast._identity
    monkeypatch.setenv("OPENAPI_SPEC_URL_A", "file:///synthetic/a.json")
    monkeypatch.setenv("OPENAPI_SPEC_URL_B", "file:///synthetic/b.json")
    monkeypatch.setenv("TOOL_WHITELIST", "/safe")
    monkeypatch.setattr(fast, "spec", None)
    monkeypatch.setattr(fast, "_load_valid_spec",
                        lambda url: spec_a if url.endswith("/a.json") else spec_b)
    catalog_a = json.loads(fast.list_functions(env_key="OPENAPI_SPEC_URL_A"))
    catalog_b = json.loads(fast.list_functions(env_key="OPENAPI_SPEC_URL_B"))
    name_a = next(item["handle"] for item in catalog_a if item.get("path") == "/safe")
    name_b = next(item["handle"] for item in catalog_b if item.get("path") == "/safe")
    a_paused, b_done = threading.Event(), threading.Event()
    def identity(url, loaded):
        if url.endswith("/a.json"):
            a_paused.set()
            assert b_done.wait(2)
        return original_identity(url, loaded)
    monkeypatch.setattr(fast, "_identity", identity)
    def dispatch(**kwargs):
        return transport.ResponseSnapshot(json.dumps({"origin": kwargs["url"]}), 200)
    monkeypatch.setattr(fast, "bounded_request", dispatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(fast.call_function, function_name=name_a, env_key="OPENAPI_SPEC_URL_A", _cancel=threading.Event())
        assert a_paused.wait(2)
        try:
            b = fast.call_function(function_name=name_b, env_key="OPENAPI_SPEC_URL_B", _cancel=threading.Event())
        finally:
            b_done.set()
        assert json.loads(b)["origin"] == "https://b.synthetic.invalid/safe"
        assert json.loads(a.result(timeout=2))["origin"] == "https://a.synthetic.invalid/safe"


def test_concurrent_catalog_publication_is_complete_and_atomic(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from mcp_openapi_proxy import server_fastmcp as fast
    a = {"openapi": "3.0.3", "servers": [{"url": "https://a.synthetic.invalid"}],
         "paths": {"/a": {"get": {}}}}
    b = {"openapi": "3.0.3", "servers": [{"url": "https://b.synthetic.invalid"}],
         "paths": {"/b": {"get": {}}}}
    monkeypatch.setenv("OPENAPI_SPEC_URL_A", "file:///synthetic/a.json")
    monkeypatch.setenv("OPENAPI_SPEC_URL_B", "file:///synthetic/b.json")
    monkeypatch.setenv("TOOL_WHITELIST", "/a,/b")
    monkeypatch.setattr(fast, "_FUNCTION_OPERATIONS", {"sentinel": {}})
    monkeypatch.setattr(fast, "_SPEC_SNAPSHOTS", {})
    monkeypatch.setattr(fast, "_load_valid_spec", lambda url: a if url.endswith("/a.json") else b)
    paused, resume = threading.Event(), threading.Event()
    normalize = fast.normalize_tool_name
    def pause_a(raw):
        if raw == "GET /a":
            paused.set()
            assert resume.wait(2)
        return normalize(raw)
    monkeypatch.setattr(fast, "normalize_tool_name", pause_a)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(fast.list_functions, env_key="OPENAPI_SPEC_URL_A")
        assert paused.wait(2)
        try:
            assert set(fast._FUNCTION_OPERATIONS) == {"sentinel"}
            catalog_b = json.loads(fast.list_functions(env_key="OPENAPI_SPEC_URL_B"))
            assert {x["path"] for x in fast._FUNCTION_OPERATIONS.values()} == {"/b"}
        finally:
            resume.set()
        catalog_a = json.loads(pending.result(timeout=2))
    assert {x["path"] for x in fast._FUNCTION_OPERATIONS.values()} == {"/a"}
    assert any(x.get("path") == "/a" for x in catalog_a)
    assert any(x.get("path") == "/b" for x in catalog_b)


@pytest.mark.asyncio
async def test_runtime_tools_never_fetch_an_unloaded_spec(monkeypatch):
    from mcp_openapi_proxy import server_fastmcp as fast
    from mcp.server.mcpserver.exceptions import ToolError
    monkeypatch.setenv("OPENAPI_SPEC_URL", "https://synthetic.invalid/slow-spec")
    monkeypatch.setattr(fast, "_SPEC_SNAPSHOTS", {})
    def forbidden(*_args, **_kwargs):
        pytest.fail("runtime tool tried to fetch an unbounded remote spec")
    monkeypatch.setattr(fast, "_load_valid_spec", forbidden)
    with pytest.raises(ToolError):
        await fast.list_functions_tool()
    with pytest.raises(ToolError):
        await fast.call_function_tool(function_name="get_synthetic")


def test_worker_never_uses_ambient_netrc_credentials(api, tmp_path, monkeypatch):
    base, seen = api
    netrc = tmp_path / "fictional.netrc"
    netrc.write_text("machine 127.0.0.1 login SYNTHETIC_USER password SYNTHETIC_SECRET\n")
    netrc.chmod(0o600)
    monkeypatch.setenv("NETRC", str(netrc))
    transport.bounded_request(method="GET", url=base+"/ok")
    assert seen.authorizations == [None]

def test_worker_respects_an_inherited_lower_memory_limit(api):
    pytest.importorskip("resource")
    import sys
    base, _ = api
    code = """
import resource, sys
soft, hard = resource.getrlimit(resource.RLIMIT_AS)
cap = 384 * 1024 * 1024
if hard != resource.RLIM_INFINITY:
    cap = min(cap, hard)
resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
from mcp_openapi_proxy.bounded_http import bounded_request
result = bounded_request(method="GET", url=sys.argv[1])
assert result.status_code == 200
print(result.status_code)
"""
    result = subprocess.run([sys.executable, "-B", "-c", code, base+"/ok"],
                            capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "200"
