import pytest
from mcp_openapi_proxy.openapi import register_functions

from mcp_openapi_proxy.utils import normalize_tool_name

def test_register_functions_basic():
    spec = {
        "paths": {
            "/foo": {
                "get": {
                    "operationId": "foo",
                    "summary": "desc",
                    "parameters": [
                        {"name": "id", "in": "query", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
        "servers": [{"url": "http://localhost"}]
    }
    tools = register_functions(spec)
    assert isinstance(tools, list)
    normalized_name = normalize_tool_name("GET /foo")
    assert any(t.name == normalized_name for t in tools)
    assert tools[0].inputSchema["properties"]["id"]["type"] == "string"

def test_register_functions_missing_fields():
    spec = {"paths": {"/bar": {"get": {}}}, "servers": [{"url": "http://localhost"}]}
    tools = register_functions(spec)
    assert isinstance(tools, list)
    # Should not raise, but may produce incomplete tool definitions

def test_register_functions_invalid_schema():
    spec = {
        "paths": {
            "/baz": {
                "get": {
                    "operationId": "baz",
                    "summary": "desc",
                    "parameters": [
                        {"name": "id", "in": "query", "required": True, "schema": None},
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
        "servers": [{"url": "http://localhost"}]
    }
    tools = register_functions(spec)
    assert isinstance(tools, list)
