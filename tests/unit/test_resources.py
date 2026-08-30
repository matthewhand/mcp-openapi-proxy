import os
import json
import asyncio
import pytest
from unittest.mock import patch
from types import SimpleNamespace

import mcp_openapi_proxy.types as t
# Globally patch model constructors in types to bypass pydantic validation.
t.TextContent = lambda **kwargs: {"type": kwargs.get("type"), "text": kwargs.get("text"), "uri": "dummy-uri"}
t.ReadResourceResult = lambda **kwargs: kwargs
t.ServerResult = lambda **kwargs: kwargs
# Alias ListResourcesResult to ReadResourceResult if needed.
t.ListResourcesResult = t.ReadResourceResult

from mcp_openapi_proxy.server_lowlevel import list_resources, read_resource
from mcp_openapi_proxy.server_fastmcp import list_functions, call_function

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.delenv("OPENAPI_SPEC_URL", raising=False)
    monkeypatch.setenv("OPENAPI_SPEC_URL", "http://dummy.com")

def to_dict(obj):
    # Try to convert an object to dict.
    if isinstance(obj, dict):
        return obj
    elif hasattr(obj, "dict"):
        return obj.dict()
    elif hasattr(obj, "__dict__"):
        return vars(obj)
    return obj

def test_lowlevel_list_resources(mock_env):
    # Patch the types in server_lowlevel to use our patched types.
    import mcp_openapi_proxy.server_lowlevel as sl
    sl.types = t
    request = SimpleNamespace(params=SimpleNamespace())
    result = asyncio.run(list_resources(request))
    res = to_dict(result)
    assert len(res["resources"]) == 1, "Expected one resource"
    # Convert the resource object to dict if needed.
    resource = res["resources"][0]
    if not isinstance(resource, dict):
        resource = vars(resource)
    assert resource["name"] == "spec_file", "Expected spec_file resource"

# def test_lowlevel_read_resource_valid(mock_env):
#     import mcp_openapi_proxy.server_lowlevel as sl
#     sl.types = t
#     sl.openapi_spec_data = {"dummy": "spec"}
#     # Simulate resource creation.
#     sl.resources = [SimpleNamespace(uri="file:///openapi_spec.json", name="spec_file")]
#     request = SimpleNamespace(params=SimpleNamespace(uri="file:///openapi_spec.json"))
#     result = asyncio.run(sl.read_resource(request))
#     res = to_dict(result)
#     expected = json.dumps({"dummy": "spec"}, indent=2)
#     assert res["contents"][0]["text"] == expected, "Expected spec JSON"

def test_fastmcp_list_resources(mock_env):
    import mcp_openapi_proxy.server_fastmcp as fm
    fm.types = t
    with patch("mcp_openapi_proxy.server_fastmcp.fetch_openapi_spec", return_value='{"paths":{},"tools":[{"name": "list_resources"}]}'):
        tools_json = list_functions(env_key="OPENAPI_SPEC_URL")
        tools = json.loads(tools_json)
        assert any(item["name"] == "list_resources" for item in tools), "list_resources not found"
        assert not any(item["name"] == "get_tasks_id" for item in tools), "pathless spec exposed a synthetic endpoint"
        result = call_function(function_name="list_resources", parameters={}, env_key="OPENAPI_SPEC_URL")
        resources = json.loads(result)
        assert len(resources) == 1, "Expected one resource"
        assert resources[0]["name"] == "spec_file", "Expected spec_file resource"

def test_fastmcp_read_resource_valid(mock_env):
    import mcp_openapi_proxy.server_fastmcp as fm
    from unittest.mock import patch
    fm.types = t
    with patch("mcp_openapi_proxy.server_fastmcp.spec", new=None):
        with patch("mcp_openapi_proxy.server_fastmcp.fetch_openapi_spec", return_value={"dummy": "spec"}):
            result = call_function(function_name="read_resource", parameters={"uri": "file:///openapi_spec.json"}, env_key="OPENAPI_SPEC_URL")
            assert json.loads(result) == {"dummy": "spec"}, "Expected spec JSON"
