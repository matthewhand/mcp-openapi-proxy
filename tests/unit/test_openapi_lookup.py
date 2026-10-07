import pytest
from mcp_openapi_proxy.openapi import lookup_operation_details

from mcp_openapi_proxy.utils import normalize_tool_name

def test_lookup_operation_details_found():
    spec = {
        "paths": {
            "/foo": {
                "get": {"operationId": "foo", "summary": "desc"},
                "post": {"operationId": "bar", "summary": "desc"},
            }
        }
    }
    get_name = normalize_tool_name("GET /foo")
    post_name = normalize_tool_name("POST /foo")
    result = lookup_operation_details(get_name, spec)
    assert result["operation"]["operationId"] == "foo"
    assert result["method"] == "GET"
    assert result["path"] == "/foo"

    result2 = lookup_operation_details(post_name, spec)
    assert result2["operation"]["operationId"] == "bar"
    assert result2["method"] == "POST"
    assert result2["path"] == "/foo"

def test_lookup_operation_details_not_found():
    spec = {"paths": {"/foo": {"get": {"operationId": "foo"}}}}
    result = lookup_operation_details("not_a_real_tool", spec)
    assert result is None

def test_lookup_operation_details_ambiguous():
    from mcp_openapi_proxy.utils import normalize_tool_name
    spec = {
        "paths": {
            "/foo": {"get": {"operationId": "foo"}},
            "/bar": {"get": {"operationId": "foo"}},
        }
    }
    tool_name = normalize_tool_name("GET /foo")
    result = lookup_operation_details(tool_name, spec)
    assert result is not None  # Should return the first match
