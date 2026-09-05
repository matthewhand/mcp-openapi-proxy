"""INFO logging of inbound JSON-RPC method on native Streamable HTTP.

One line per POST: ``mcp rpc method=tools/list`` or
``mcp rpc method=tools/call name=get_ping``. Arguments, Authorization,
and request bodies must never appear.
"""

from __future__ import annotations

import json
import logging

import pytest

from mcp_openapi_proxy.protocol import (
    format_rpc_log_line,
    inbound_rpc_identity,
    modern_headers,
    modern_request_meta,
)

TINY_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "rpc-log-test", "version": "1.0.0"},
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


def test_identity_from_jsonrpc_body():
    method, name = inbound_rpc_identity(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    assert method == "tools/list"
    assert format_rpc_log_line(method, name) == "mcp rpc method=tools/list"


def test_identity_tools_call_name_without_arguments():
    method, name = inbound_rpc_identity(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_server_list",
                "arguments": {"token": "SECRET", "Authorization": "Bearer leak"},
            },
        }
    )
    line = format_rpc_log_line(method, name)
    assert line == "mcp rpc method=tools/call name=get_server_list"
    assert "SECRET" not in line
    assert "Bearer" not in line
    assert "arguments" not in line
    assert "Authorization" not in line


def test_identity_falls_back_to_mcp_headers():
    method, name = inbound_rpc_identity(
        None,
        {
            "mcp-method": "tools/call",
            "mcp-name": "get_server_list",
            "authorization": "Bearer SECRET",
        },
    )
    line = format_rpc_log_line(method, name)
    assert line == "mcp rpc method=tools/call name=get_server_list"
    assert "SECRET" not in line


def test_identity_rejects_unsafe_tokens():
    method, name = inbound_rpc_identity(
        {
            "method": "tools/call\nAuthorization: Bearer SECRET",
            "params": {"name": "ok"},
        }
    )
    assert method is None
    assert format_rpc_log_line(method, name) is None


def test_format_omits_name_except_tools_call():
    assert format_rpc_log_line("prompts/get", "some_prompt") == "mcp rpc method=prompts/get"
    assert format_rpc_log_line("tools/call", None) == "mcp rpc method=tools/call"


def test_http_logs_list_and_call_without_secrets(spec_env, monkeypatch, caplog):
    from starlette.testclient import TestClient
    import mcp_openapi_proxy.server_lowlevel as sl
    import requests

    class Dummy:
        text = '{"pong": true}'

        def raise_for_status(self):
            return None

    monkeypatch.setattr(requests, "request", lambda *a, **k: Dummy())
    sl.mcp = sl.build_server()
    app = sl.build_streamable_http_app(host="testserver", path="/mcp")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")

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
        name = listed.json()["result"]["tools"][0]["name"]
        called = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": {"api_key": "SUPERSECRET", "token": "also-secret"},
                    "_meta": modern_request_meta(),
                },
            },
            headers={
                **modern_headers("tools/call", name=name),
                "Authorization": "Bearer SUPERSECRET",
            },
        )
        assert called.status_code == 200, called.text
        healthy = client.get("/healthz")
        assert healthy.status_code == 200

    messages = [r.message for r in caplog.records if r.message.startswith("mcp rpc ")]
    assert "mcp rpc method=tools/list" in messages
    assert f"mcp rpc method=tools/call name={name}" in messages
    blob = "\n".join(r.message for r in caplog.records)
    assert "SUPERSECRET" not in blob
    assert "also-secret" not in blob
    assert "api_key" not in blob
    assert not any(m.startswith("mcp rpc ") and "healthz" in m for m in messages)


def test_http_logs_method_from_body_without_mcp_headers(spec_env, caplog):
    """Body peek still logs when Mcp-Method is absent (SDK then rejects -32020)."""
    from starlette.testclient import TestClient
    import mcp_openapi_proxy.server_lowlevel as sl

    sl.mcp = sl.build_server()
    app = sl.build_streamable_http_app(host="testserver", path="/mcp")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": modern_request_meta()},
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2026-07-28",
            },
        )
        assert resp.status_code == 400
        err = resp.json().get("error") or {}
        assert err.get("code") == -32020

    messages = [r.message for r in caplog.records if r.message.startswith("mcp rpc ")]
    assert messages == ["mcp rpc method=tools/list"]
