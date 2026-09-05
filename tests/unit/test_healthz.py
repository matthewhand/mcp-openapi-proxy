"""GET /healthz on native Streamable HTTP (issue #66).

Process-local probe: 200 JSON {ok, name, port}. No OpenAPI spec fetch,
no MCP initialize, no Mcp-Session-Id, no Streamable-HTTP request lock.
"""

from __future__ import annotations

import json

import pytest

from mcp_openapi_proxy.protocol import (
    HEADER_SESSION_ID,
    healthz_body,
    healthz_route,
    modern_headers,
    modern_request_meta,
    transport_security,
)

TINY_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "healthz-test", "version": "1.0.0"},
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


def test_healthz_body_uses_env_name_and_port(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_NAME", "gpt-terminal-plus")
    monkeypatch.setenv("MCP_PORT", "8815")
    assert healthz_body() == {"ok": True, "name": "gpt-terminal-plus", "port": 8815}


def test_healthz_body_fallback_name_and_default_port(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_NAME", raising=False)
    monkeypatch.delenv("OPENAPI_SERVER_NAME", raising=False)
    monkeypatch.delenv("OPENAPI_SPEC_URL", raising=False)
    monkeypatch.delenv("MCP_PORT", raising=False)
    body = healthz_body()
    assert body == {"ok": True, "name": "openapi-proxy", "port": 8000}


def test_healthz_route_is_get_only_sibling():
    route = healthz_route()
    assert route.path == "/healthz"
    assert route.methods == {"GET"}


def test_http_healthz_200_body_shape(spec_env, monkeypatch):
    from starlette.testclient import TestClient
    import mcp_openapi_proxy.server_lowlevel as sl
    import mcp_openapi_proxy.openapi as openapi
    import mcp_openapi_proxy.utils as utils

    def _boom(*_a, **_k):
        raise AssertionError("healthz must not fetch the OpenAPI spec")

    monkeypatch.setenv("MCP_SERVER_NAME", "gpt-terminal-plus")
    monkeypatch.setenv("MCP_PORT", "8815")
    monkeypatch.setattr(openapi, "fetch_openapi_spec", _boom)
    monkeypatch.setattr(utils, "fetch_openapi_spec", _boom)
    monkeypatch.setattr(sl, "fetch_openapi_spec", _boom)

    sl.mcp = sl.build_server()
    app = sl.build_streamable_http_app(host="testserver", path="/mcp")
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200, resp.text
        assert resp.headers.get("content-type", "").startswith("application/json")
        assert resp.json() == {"ok": True, "name": "gpt-terminal-plus", "port": 8815}
        assert sl.openapi_spec_data is None
        assert HEADER_SESSION_ID.lower() not in {k.lower() for k in resp.headers}


def test_http_healthz_does_not_break_mcp_path(spec_env):
    from starlette.testclient import TestClient
    import mcp_openapi_proxy.server_lowlevel as sl

    sl.mcp = sl.build_server()
    app = sl.build_streamable_http_app(host="testserver", path="/mcp")
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {"_meta": modern_request_meta()},
    }
    with TestClient(app) as client:
        listed = client.post("/mcp", json=body, headers=modern_headers("tools/list"))
        assert listed.status_code == 200, listed.text
        healthy = client.get("/healthz")
        assert healthy.status_code == 200
        assert healthy.json()["ok"] is True


def test_fastmcp_healthz_200_body_shape(monkeypatch):
    from starlette.testclient import TestClient
    from mcp_openapi_proxy import server_fastmcp as fm

    monkeypatch.setenv("MCP_SERVER_NAME", "simple-mode")
    monkeypatch.setenv("MCP_PORT", "9000")
    app = fm.mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(),
        host="testserver",
    )
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True, "name": "simple-mode", "port": 9000}
