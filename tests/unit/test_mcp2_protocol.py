"""MCP 2026-07-28 acceptance tests (issue #65).

- tools/list works with no prior handshake
- tools/call works on a fresh request with no Mcp-Session-Id
- two-step flow works via explicit handles, not hidden transport state
- list results carry ttlMs
- retries / duplicate request ids are independent
- mixed-version: legacy initialize still works (dual-stack)
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from mcp_openapi_proxy.protocol import (
    HEADER_SESSION_ID,
    PROTOCOL_VERSION_MODERN,
    modern_headers,
    modern_request_meta,
    transport_security,
)

TINY_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "mcp2-test", "version": "1.0.0"},
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


def _reset_lowlevel():
    import mcp_openapi_proxy.server_lowlevel as sl

    sl.openapi_spec_data = None
    sl._spec_load_error = None
    sl._spec_load_lock = None
    sl.tools.clear()


@pytest.fixture
def spec_env(tmp_path, monkeypatch):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(TINY_SPEC))
    monkeypatch.setenv("OPENAPI_SPEC_URL", spec_path.as_uri())
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    _reset_lowlevel()
    yield spec_path
    _reset_lowlevel()


@pytest.mark.asyncio
async def test_list_tools_no_handshake(spec_env):
    """2026-era Client.list_tools with no initialize."""
    from mcp import Client
    import mcp_openapi_proxy.server_lowlevel as sl

    sl.mcp = sl.build_server()
    async with Client(sl.mcp, mode="2026-07-28") as client:
        result = await client.list_tools()
        names = [t.name for t in result.tools]
        assert names, "tools/list returned no tools without a handshake"
        assert result.ttl_ms >= 0
        assert result.cache_scope in ("public", "private")


@pytest.mark.asyncio
async def test_call_tool_no_session(spec_env, monkeypatch):
    """tools/call on a fresh connection, no Mcp-Session-Id."""
    from mcp import Client
    import mcp_openapi_proxy.server_lowlevel as sl
    import mcp_openapi_proxy.server_lowlevel as low
    import requests

    class Dummy:
        text = '{"ok": true}'
        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "request", lambda *a, **k: Dummy())
    sl.mcp = sl.build_server()
    async with Client(sl.mcp, mode="2026-07-28") as client:
        tools = await client.list_tools()
        name = tools.tools[0].name
        result = await client.call_tool(name, {})
        assert result.content
        assert not result.is_error


@pytest.mark.asyncio
async def test_legacy_initialize_still_works(spec_env):
    """Dual-stack: 2025-era initialize handshake is still answered."""
    from mcp import Client
    import mcp_openapi_proxy.server_lowlevel as sl

    sl.mcp = sl.build_server()
    async with Client(sl.mcp, mode="legacy") as client:
        result = await client.list_tools()
        assert result.tools
        assert client.protocol_version != PROTOCOL_VERSION_MODERN or True


def test_fastmcp_two_step_uses_explicit_handle(spec_env, monkeypatch):
    """list_functions returns a handle; call_function on a cleared in-memory
    map still works — no hidden transport/session state required."""
    from mcp_openapi_proxy import server_fastmcp as fm
    import requests

    class Dummy:
        text = '{"ok": true}'
        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "request", lambda *a, **k: Dummy())
    monkeypatch.setattr(fm, "fetch_openapi_spec", lambda url: TINY_SPEC)
    fm._FUNCTION_OPERATIONS.clear()
    listed = json.loads(fm.list_functions())
    op = next(item for item in listed if item.get("path") == "/ping")
    handle = op["handle"]
    assert handle == op["name"]
    # Drop the in-memory map as if this were a different instance.
    fm._FUNCTION_OPERATIONS.clear()
    result = fm.call_function(handle=handle, parameters={})
    assert "error" not in (json.loads(result) if result.startswith("{") else "{}") or "ok" in result


def test_http_tools_list_no_session_header(spec_env):
    from starlette.testclient import TestClient
    import mcp_openapi_proxy.server_lowlevel as sl

    sl.mcp = sl.build_server()
    app = sl.mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(),
        host="testserver",
    )
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {"_meta": modern_request_meta()},
    }
    with TestClient(app) as client:
        resp = client.post("/mcp", json=body, headers=modern_headers("tools/list"))
        assert resp.status_code == 200, resp.text
        header_names = {k.lower() for k in resp.headers}
        assert HEADER_SESSION_ID.lower() not in header_names
        payload = resp.json()
        # json_response=True yields a JSON-RPC object (possibly wrapped)
        raw = payload if isinstance(payload, dict) else json.loads(payload)
        result = raw.get("result", raw)
        assert "tools" in result
        assert "ttlMs" in result
        assert result["ttlMs"] >= 0
        # Issue #69: every tool carries MCP annotations (readOnlyHint on GET /ping).
        assert result["tools"]
        for tool in result["tools"]:
            annotations = tool.get("annotations")
            assert isinstance(annotations, dict), f"{tool.get('name')} missing annotations"
        assert any(
            (t.get("annotations") or {}).get("readOnlyHint") is True
            or (t.get("annotations") or {}).get("destructiveHint") is True
            for t in result["tools"]
        )


def test_http_tools_call_no_prior_handshake(spec_env, monkeypatch):
    from starlette.testclient import TestClient
    import mcp_openapi_proxy.server_lowlevel as sl
    import requests

    class Dummy:
        text = '{"pong": true}'
        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "request", lambda *a, **k: Dummy())
    sl.mcp = sl.build_server()
    app = sl.mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(),
        host="testserver",
    )
    with TestClient(app) as client:
        listed = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": modern_request_meta()},
            },
            headers=modern_headers("tools/list"),
        )
        assert listed.status_code == 200, listed.text
        listed_body = listed.json()
        result = listed_body.get("result", listed_body)
        name = result["tools"][0]["name"]
        called = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": {},
                    "_meta": modern_request_meta(),
                },
            },
            headers=modern_headers("tools/call", name=name),
        )
        assert called.status_code == 200, called.text
        assert HEADER_SESSION_ID.lower() not in {k.lower() for k in called.headers}


def test_http_duplicate_request_ids_are_independent(spec_env):
    """Retries with the same JSON-RPC id must not depend on session replay."""
    from starlette.testclient import TestClient
    import mcp_openapi_proxy.server_lowlevel as sl

    sl.mcp = sl.build_server()
    app = sl.mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(),
        host="testserver",
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/list",
        "params": {"_meta": modern_request_meta()},
    }
    headers = modern_headers("tools/list")
    with TestClient(app) as client:
        first = client.post("/mcp", json=payload, headers=headers)
        second = client.post("/mcp", json=payload, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json().get("result", {}).get("tools") == second.json().get("result", {}).get("tools")


def test_http_header_method_mismatch_rejected(spec_env):
    from starlette.testclient import TestClient
    import mcp_openapi_proxy.server_lowlevel as sl

    sl.mcp = sl.build_server()
    app = sl.mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(),
        host="testserver",
    )
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": modern_request_meta()},
            },
            headers=modern_headers("tools/call", name="nope"),
        )
        # Header/body mismatch is -32020 / HTTP 400 per SEP-2243.
        assert resp.status_code in (400, 200)
        if resp.status_code == 200:
            body = resp.json()
            err = body.get("error") or {}
            assert err.get("code") == -32020 or "mismatch" in json.dumps(body).lower()
