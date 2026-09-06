"""MCP ToolAnnotations on OpenAPI-derived tools (issue #69).

Every tools/list entry must carry an annotations object. GET (and clearly
read-ish POST) set readOnlyHint; other methods set destructiveHint. Titles
are humanized from the operation/tool name. additionalProperties stays False.
"""

from __future__ import annotations

import json

import pytest

from mcp_openapi_proxy.openapi import (
    annotations_wire_dict,
    build_tool_annotations,
    human_tool_title,
    register_functions,
)

MIXED_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "annotations-test", "version": "1.0.0"},
    "servers": [{"url": "http://example.test"}],
    "paths": {
        "/users": {
            "get": {
                "summary": "List users",
                "operationId": "listUsers",
                "responses": {"200": {"description": "ok"}},
            },
            "post": {
                "summary": "Create user",
                "operationId": "createUser",
                "responses": {"201": {"description": "created"}},
            },
        },
        "/users/{id}": {
            "put": {
                "summary": "Replace user",
                "operationId": "replaceUser",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "ok"}},
            },
            "delete": {
                "summary": "Delete user",
                "operationId": "deleteUser",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"204": {"description": "gone"}},
            },
        },
        "/search": {
            "post": {
                "summary": "Search users",
                "operationId": "searchUsers",
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}


def test_human_title_prefers_short_summary():
    assert human_tool_title("get_users", {"summary": "List users", "operationId": "listUsers"}) == "List users"


def test_human_title_falls_back_to_operation_id():
    assert human_tool_title("get_users", {"operationId": "listUsers"}) == "List Users"


def test_human_title_falls_back_to_tool_name():
    assert human_tool_title("get_users_by_id", {}) == "Get Users By Id"


def test_get_annotations_are_read_only():
    ann = build_tool_annotations("GET", "get_users", {"summary": "List users"})
    assert ann.title == "List users"
    assert ann.read_only_hint is True
    assert ann.idempotent_hint is True
    assert ann.destructive_hint is None


def test_post_write_is_destructive():
    ann = build_tool_annotations("POST", "post_users", {"summary": "Create user", "operationId": "createUser"})
    assert ann.destructive_hint is True
    assert ann.read_only_hint is None
    assert ann.idempotent_hint is None


def test_readish_post_is_read_only():
    ann = build_tool_annotations("POST", "post_search", {"summary": "Search users", "operationId": "searchUsers"})
    assert ann.read_only_hint is True
    assert ann.idempotent_hint is True
    assert ann.destructive_hint is None


def test_get_or_create_post_stays_destructive():
    ann = build_tool_annotations("POST", "post_users", {"operationId": "getOrCreateUser"})
    assert ann.destructive_hint is True
    assert ann.read_only_hint is None


def test_put_and_delete_are_destructive_and_idempotent():
    put = build_tool_annotations("PUT", "put_users_by_id", {"summary": "Replace user"})
    delete = build_tool_annotations("DELETE", "delete_users_by_id", {"summary": "Delete user"})
    assert put.destructive_hint is True
    assert put.idempotent_hint is True
    assert delete.destructive_hint is True
    assert delete.idempotent_hint is True


def test_wire_dict_uses_camel_case_and_drops_nulls():
    dumped = annotations_wire_dict("GET", "get_ping", {"summary": "Ping"})
    assert dumped == {
        "title": "Ping",
        "readOnlyHint": True,
        "idempotentHint": True,
    }
    write = annotations_wire_dict("POST", "post_users", {"summary": "Create user"})
    assert write["destructiveHint"] is True
    assert "readOnlyHint" not in write


def test_register_functions_attaches_annotations_to_every_tool():
    tools = register_functions(MIXED_SPEC)
    assert tools, "expected OpenAPI-derived tools"
    hinted = False
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} missing annotations"
        assert tool.annotations.title, f"{tool.name} missing annotations.title"
        assert tool.input_schema.get("additionalProperties") is False
        hinted = hinted or (
            tool.annotations.read_only_hint is True or tool.annotations.destructive_hint is True
        )
    assert hinted, "at least one tool must set readOnlyHint or destructiveHint"

    by_name = {t.name: t for t in tools}
    assert by_name["get_users"].annotations.read_only_hint is True
    assert by_name["post_users"].annotations.destructive_hint is True
    assert by_name["post_search"].annotations.read_only_hint is True
    assert by_name["put_users_by_id"].annotations.idempotent_hint is True
    assert by_name["delete_users_by_id"].annotations.destructive_hint is True


def test_list_tools_result_serializes_camel_case_annotations():
    from mcp import types

    tools = register_functions(MIXED_SPEC)
    result = types.ListToolsResult(tools=tools)
    payload = json.loads(result.model_dump_json(by_alias=True, exclude_none=True))
    assert payload["tools"], "serialized tools/list had no tools"
    hinted = False
    for tool in payload["tools"]:
        annotations = tool.get("annotations")
        assert isinstance(annotations, dict), f"{tool.get('name')} missing annotations object"
        assert annotations.get("title")
        hinted = hinted or (
            annotations.get("readOnlyHint") is True or annotations.get("destructiveHint") is True
        )
        # additionalProperties behavior is unchanged on the input schema
        assert tool["inputSchema"].get("additionalProperties") is False
    assert hinted


def test_fastmcp_catalog_includes_annotations(monkeypatch):
    from mcp_openapi_proxy import server_fastmcp as fm

    monkeypatch.setattr(fm, "fetch_openapi_spec", lambda url: MIXED_SPEC)
    monkeypatch.setenv("OPENAPI_SPEC_URL", "http://dummy_annotations")
    listed = json.loads(fm.list_functions())
    assert listed
    hinted = False
    for item in listed:
        annotations = item.get("annotations")
        assert isinstance(annotations, dict), f"{item.get('name')} missing annotations"
        assert annotations.get("title")
        hinted = hinted or (
            annotations.get("readOnlyHint") is True or annotations.get("destructiveHint") is True
        )
        assert item["inputSchema"].get("additionalProperties") is False
    assert hinted


@pytest.mark.asyncio
async def test_http_tools_list_includes_annotations(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from mcp_openapi_proxy.protocol import modern_headers, modern_request_meta, transport_security
    import mcp_openapi_proxy.server_lowlevel as sl

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(MIXED_SPEC))
    monkeypatch.setenv("OPENAPI_SPEC_URL", spec_path.as_uri())
    sl.openapi_spec_data = None
    sl._spec_load_error = None
    sl._spec_load_lock = None
    sl.tools.clear()
    sl.mcp = sl.build_server()
    app = sl.mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(),
        host="testserver",
    )
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {"_meta": modern_request_meta()},
                },
                headers=modern_headers("tools/list"),
            )
            assert resp.status_code == 200, resp.text
            result = resp.json().get("result", resp.json())
            tools = result["tools"]
            assert tools
            hinted = False
            for tool in tools:
                annotations = tool.get("annotations")
                assert isinstance(annotations, dict), f"{tool.get('name')} missing annotations"
                hinted = hinted or (
                    annotations.get("readOnlyHint") is True
                    or annotations.get("destructiveHint") is True
                )
            assert hinted, "tools/list must include readOnlyHint or destructiveHint on at least one tool"
    finally:
        sl.openapi_spec_data = None
        sl._spec_load_error = None
        sl._spec_load_lock = None
        sl.tools.clear()
