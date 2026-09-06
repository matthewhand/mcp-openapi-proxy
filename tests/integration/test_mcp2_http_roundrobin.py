"""Round-robin / multi-instance tests for stateless Streamable HTTP.

Two independent server processes, no sticky routing, no Mcp-Session-Id.
A tools/list on instance A must be usable as a tools/call on instance B.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from mcp_openapi_proxy.protocol import (
    HEADER_SESSION_ID,
    modern_headers,
    modern_request_meta,
)

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "rr-test", "version": "1.0.0"},
    "servers": [{"url": "http://example.test"}],
    "paths": {
        "/ping": {
            "get": {
                "summary": "Ping",
                "operationId": "ping",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _rpc(url: str, method: str, params=None, name=None, rpc_id=1, timeout=8.0):
    body = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": method,
        "params": {**(params or {}), "_meta": modern_request_meta()},
    }
    headers = modern_headers(method, name=name)
    headers.setdefault("Accept", "application/json, text/event-stream")
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        header_map = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status, json.loads(raw), header_map


def _wait_ready(url: str, timeout=20.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            status, payload, _ = _rpc(url, "tools/list", rpc_id=0)
            if status == 200 and "result" in payload:
                return payload
        except Exception as exc:
            last = exc
            time.sleep(0.2)
    raise TimeoutError(f"server at {url} not ready: {last}")


@pytest.fixture
def two_http_servers(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SPEC))
    procs = []
    urls = []
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    try:
        for _ in range(2):
            port = _free_port()
            env = dict(os.environ)
            env.update({
                "OPENAPI_SPEC_URL": spec_path.as_uri(),
                "MCP_TRANSPORT": "streamable-http",
                "MCP_HOST": "127.0.0.1",
                "MCP_PORT": str(port),
                "MCP_PATH": "/mcp",
                "MCP_JSON_RESPONSE": "true",
                "MCP_ALLOWED_HOSTS": "*",
                "DEBUG": "false",
                "PYTHONPATH": repo + os.pathsep + env.get("PYTHONPATH", ""),
            })
            proc = subprocess.Popen(
                [sys.executable, "-c", "from mcp_openapi_proxy import main; main()"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            procs.append(proc)
            urls.append(f"http://127.0.0.1:{port}/mcp")
        for url in urls:
            _wait_ready(url)
        yield urls
    finally:
        for proc in procs:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


def test_round_robin_list_then_call(two_http_servers, monkeypatch):
    """Instance A lists tools; instance B calls one. No session header."""
    url_a, url_b = two_http_servers
    status, listed, headers_a = _rpc(url_a, "tools/list", rpc_id=1)
    assert status == 200, listed
    assert HEADER_SESSION_ID.lower() not in headers_a
    tools = listed["result"]["tools"]
    assert tools
    name = tools[0]["name"]

    # Alternate: even retries go to B, the instance that never saw the list.
    status, called, headers_b = _rpc(
        url_b,
        "tools/call",
        params={"name": name, "arguments": {}},
        name=name,
        rpc_id=2,
    )
    assert status == 200, called
    assert HEADER_SESSION_ID.lower() not in headers_b
    # Upstream example.test is not up; a protocol-level result or tool error
    # is success. A session/handshake error is not.
    err = called.get("error")
    if err:
        msg = json.dumps(err).lower()
        assert "initialize" not in msg
        assert "session" not in msg


def test_round_robin_retries_same_id(two_http_servers):
    url_a, url_b = two_http_servers
    payload_id = 99
    _, first, _ = _rpc(url_a, "tools/list", rpc_id=payload_id)
    _, second, _ = _rpc(url_b, "tools/list", rpc_id=payload_id)
    assert "result" in first and "result" in second
    assert first["result"]["tools"] and second["result"]["tools"]
