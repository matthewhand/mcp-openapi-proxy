"""
Unit tests for additional headers functionality in mcp-openapi-proxy.
"""

import os
import json
import asyncio
import pytest
from unittest.mock import patch
from mcp_openapi_proxy.utils import get_additional_headers, setup_logging
from mcp_openapi_proxy.server_lowlevel import dispatcher_handler, tools, openapi_spec_data
from mcp_openapi_proxy.server_fastmcp import call_function
import requests
from types import SimpleNamespace

DUMMY_SPEC = {
    "servers": [{"url": "http://dummy.com"}],
    "paths": {
        "/test": {
            "get": {
                "summary": "Test",
                "operationId": "get_test"  # Match tool name
            }
        }
    }
}

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.delenv("EXTRA_HEADERS", raising=False)
    monkeypatch.delenv("OPENAPI_SPEC_URL", raising=False)
    monkeypatch.setenv("OPENAPI_SPEC_URL", "http://dummy.com")

@pytest.fixture
def mock_requests(monkeypatch):
    def mock_request(method, url, **kwargs):
        class MockResponse:
            def __init__(self):
                self.text = "Mocked response"
            def raise_for_status(self):
                pass
        return MockResponse()
    monkeypatch.setattr(requests, "request", mock_request)

def test_get_additional_headers_empty(mock_env):
    headers = get_additional_headers()
    assert headers == {}, "Expected empty headers when EXTRA_HEADERS not set"

def test_get_additional_headers_single(mock_env):
    os.environ["EXTRA_HEADERS"] = "X-Test: Value"
    headers = get_additional_headers()
    assert headers == {"X-Test": "Value"}, "Single header not parsed correctly"

def test_get_additional_headers_multiple(mock_env):
    os.environ["EXTRA_HEADERS"] = "X-Test: Value\nX-Another: More"
    headers = get_additional_headers()
    assert headers == {"X-Test": "Value", "X-Another": "More"}, "Multiple headers not parsed correctly"

def test_get_additional_headers_literal_backslash_n_separator(mock_env):
    # Literal two-character "\n" sequence (e.g. from configs that cannot
    # express real newlines) must also act as a header separator. See issue #17.
    os.environ["EXTRA_HEADERS"] = "X-Test: Value\\nX-Another: More"
    headers = get_additional_headers()
    assert headers == {"X-Test": "Value", "X-Another": "More"}, \
        "Multiple headers separated by literal \\n not parsed correctly"

def test_get_additional_headers_literal_backslash_n_value_with_colon(mock_env):
    # Values containing colons (tokens, cookies) must survive splitting.
    os.environ["EXTRA_HEADERS"] = "x-csrf-token: abc:123\\nCookie: session=a:b"
    headers = get_additional_headers()
    assert headers == {"x-csrf-token": "abc:123", "Cookie": "session=a:b"}, \
        "Header values containing colons not parsed correctly with literal \\n separator"

def test_get_additional_headers_mixed_separators(mock_env):
    # Real newlines and literal "\n" sequences can be mixed.
    os.environ["EXTRA_HEADERS"] = "X-One: 1\nX-Two: 2\\nX-Three: 3"
    headers = get_additional_headers()
    assert headers == {"X-One": "1", "X-Two": "2", "X-Three": "3"}, \
        "Mixed real-newline and literal \\n separators not parsed correctly"

@pytest.mark.asyncio
async def test_lowlevel_dispatcher_with_headers(mock_env, mock_requests, monkeypatch):
    os.environ["EXTRA_HEADERS"] = "X-Custom: Foo"
    tools.clear()
    monkeypatch.setattr("mcp_openapi_proxy.server_lowlevel.openapi_spec_data", DUMMY_SPEC)
    # Use the mcp.types.Tool type
    from mcp import types as mcp_types
    tools.append(mcp_types.Tool(name="get_test", description="Test tool", inputSchema={"type": "object", "properties": {}}))
    # Use the actual CallToolRequest type and provide method
    from mcp.types import CallToolRequest, CallToolRequestParams
    request = CallToolRequest(method="tools/call", params=CallToolRequestParams(name="get_test", arguments={})) # Correct method value
    with patch('mcp_openapi_proxy.server_fastmcp.fetch_openapi_spec', return_value=DUMMY_SPEC):
        result = await dispatcher_handler(request)
    assert result.content[0].text == "Mocked response", "Dispatcher failed with headers"

from unittest.mock import patch
def test_fastmcp_call_function_with_headers(mock_env, mock_requests):
    os.environ["EXTRA_HEADERS"] = "X-Custom: Bar"
    os.environ["API_KEY"] = "dummy"
    from unittest.mock import patch
    from mcp_openapi_proxy import server_fastmcp
    # Patch the fetch_openapi_spec in server_fastmcp so it returns DUMMY_SPEC.
    with patch('mcp_openapi_proxy.server_fastmcp.fetch_openapi_spec', return_value=DUMMY_SPEC):
        from types import SimpleNamespace
        with patch('mcp_openapi_proxy.utils.normalize_tool_name', side_effect=lambda raw_name: "get_test"), \
             patch('mcp_openapi_proxy.server_fastmcp.requests.request', return_value=SimpleNamespace(text='"Mocked response"', raise_for_status=lambda: None)):
            result = server_fastmcp.call_function(function_name="get_test", parameters={}, env_key="OPENAPI_SPEC_URL")
            print(f"DEBUG: Call function result: {result}")
    assert json.loads(result) == "Mocked response", "Call function failed with headers"
