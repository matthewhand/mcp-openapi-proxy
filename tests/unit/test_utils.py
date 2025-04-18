"""
Unit tests for utility functions in mcp-openapi-proxy.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from mcp_openapi_proxy.utils import normalize_tool_name, detect_response_type, build_base_url, handle_auth, strip_parameters, fetch_openapi_spec

@pytest.fixture
def mock_requests_get():
    with patch('requests.get') as mock_get:
        yield mock_get

def test_normalize_tool_name():
    assert normalize_tool_name("GET /api/v2/users") == "get_v2_users"
    assert normalize_tool_name("POST /users/{id}") == "post_users_by_id"
    assert normalize_tool_name("GET /api/agent/service/list") == "get_agent_service_list"
    assert normalize_tool_name("GET /api/agent/announcement/list") == "get_agent_announcement_list"
    assert normalize_tool_name("GET /section/resources/{param1}.{param2}") == "get_section_resources_by_param1_param2"
    assert normalize_tool_name("GET /resource/{param1}/{param2}-{param3}") == "get_resource_by_param1_by_param2_param3"
    assert normalize_tool_name("GET /{param1}/resources") == "get_by_param1_resources"
    assert normalize_tool_name("GET /resources/{param1}-{param2}.{param3}") == "get_resources_by_param1_param2_param3"
    assert normalize_tool_name("GET /users/{id1}/{id2}") == "get_users_by_id1_by_id2"
    assert normalize_tool_name("GET /users/user_{id}") == "get_users_user_by_id"
    assert normalize_tool_name("GET /search+filter/results") == "get_search+filter_results"
    assert normalize_tool_name("GET /user_profiles/active") == "get_user_profiles_active"
    assert normalize_tool_name("INVALID") == "unknown_tool"

def test_detect_response_type_json():
    content, msg = detect_response_type('{"key": "value"}')
    assert content.type == "text"
    # New behavior: should return the decoded JSON, not a wrapped string
    assert content.text == '{"key": "value"}'
    assert "JSON" in msg

def test_detect_response_type_text():
    content, msg = detect_response_type("plain text")
    assert content.type == "text"
    assert content.text == "plain text"
    assert "non-JSON" in msg

def test_build_base_url_servers(monkeypatch):
    monkeypatch.delenv("SERVER_URL_OVERRIDE", raising=False)
    spec = {"servers": [{"url": "https://api.example.com/v1"}]}
    assert build_base_url(spec) == "https://api.example.com/v1"

def test_build_base_url_host(monkeypatch):
    monkeypatch.delenv("SERVER_URL_OVERRIDE", raising=False)
    spec = {"host": "api.example.com", "schemes": ["https"], "basePath": "/v1"}
    assert build_base_url(spec) == "https://api.example.com/v1"

def test_handle_auth_with_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "testkey")
    headers = handle_auth({"method": "GET"})
    assert headers == {"Authorization": "Bearer testkey"}

def test_handle_auth_no_api_key():
    headers = handle_auth({"method": "GET"})
    assert headers == {}

def test_strip_parameters_with_param(monkeypatch):
    monkeypatch.setenv("STRIP_PARAM", "token")
    params = {"token": "abc123", "channel": "test"}
    result = strip_parameters(params)
    assert result == {"channel": "test"}

def test_fetch_openapi_spec_ssl_verification_enabled(mock_requests_get):
    """Test that SSL verification is enabled by default"""
    mock_response = MagicMock()
    mock_response.text = '{"test": "data"}'
    mock_requests_get.return_value = mock_response

    fetch_openapi_spec("https://example.com/spec.json")

    mock_requests_get.assert_called_once_with(
        "https://example.com/spec.json",
        timeout=10,
        verify=True
    )

def test_fetch_openapi_spec_ssl_verification_disabled(mock_requests_get):
    """Test that SSL verification can be disabled via IGNORE_SSL_SPEC"""
    mock_response = MagicMock()
    mock_response.text = '{"test": "data"}'
    mock_requests_get.return_value = mock_response

    os.environ['IGNORE_SSL_SPEC'] = 'true'
    fetch_openapi_spec("https://example.com/spec.json")
    del os.environ['IGNORE_SSL_SPEC'] # Clean up env var

    mock_requests_get.assert_called_once_with(
        "https://example.com/spec.json",
        timeout=10,
        verify=False
    )

def test_strip_parameters_no_param():
    params = {"channel": "test"}
    result = strip_parameters(params)
    assert result == {"channel": "test"}

def test_tool_name_prefix(monkeypatch):
    """Test that TOOL_NAME_PREFIX env var is respected when generating tool names."""
    import os
    from mcp_openapi_proxy.utils import normalize_tool_name

    # Set prefix in environment
    monkeypatch.setenv("TOOL_NAME_PREFIX", "otrs_")

    # Use correct raw_name format: "METHOD /path"
    raw_name = "GET /users/list"
    tool_name = normalize_tool_name(raw_name)
    prefix = os.getenv("TOOL_NAME_PREFIX", "")
    assert tool_name.startswith(prefix), f"Tool name '{tool_name}' does not start with prefix '{prefix}'"
    # Also check the rest of the name
    assert tool_name == "otrs_get_users_list"

def test_tool_name_max_length(monkeypatch):
    import os
    from mcp_openapi_proxy.utils import normalize_tool_name
    monkeypatch.delenv("TOOL_NAME_PREFIX", raising=False)
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "10")
    raw_name = "GET /users/list"
    tool_name = normalize_tool_name(raw_name)
    assert len(tool_name) == 10
    monkeypatch.delenv("TOOL_NAME_MAX_LENGTH", raising=False)

def test_tool_name_max_length_invalid(monkeypatch, caplog):
    import os
    from mcp_openapi_proxy.utils import normalize_tool_name
    caplog.set_level("WARNING")
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "abc")
    tool_name = normalize_tool_name("GET /users/list")
    assert tool_name.startswith("get_users_list")
    assert any("Invalid TOOL_NAME_MAX_LENGTH" in r.message for r in caplog.records)
    monkeypatch.delenv("TOOL_NAME_MAX_LENGTH", raising=False)

def test_tool_name_with_path_param(monkeypatch):
    from mcp_openapi_proxy.utils import normalize_tool_name
    monkeypatch.delenv("TOOL_NAME_PREFIX", raising=False)
    tool_name = normalize_tool_name("POST /items/{item_id}")
    assert tool_name == "post_items_by_item_id"

def test_tool_name_malformed(monkeypatch):
    from mcp_openapi_proxy.utils import normalize_tool_name
    monkeypatch.delenv("TOOL_NAME_PREFIX", raising=False)
    tool_name = normalize_tool_name("foobar")  # no space, should trigger fallback
    assert tool_name == "unknown_tool"

def test_is_tool_whitelist_set(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelist_set
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)
    assert not is_tool_whitelist_set()
    monkeypatch.setenv("TOOL_WHITELIST", "/foo")
    assert is_tool_whitelist_set()
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)

def test_is_tool_whitelisted_no_whitelist(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)
    assert is_tool_whitelisted("/anything")

def test_is_tool_whitelisted_simple_prefix(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    monkeypatch.setenv("TOOL_WHITELIST", "/foo")
    assert is_tool_whitelisted("/foo/bar")
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)

def test_is_tool_whitelisted_placeholder(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    monkeypatch.setenv("TOOL_WHITELIST", "/foo/{id}")
    assert is_tool_whitelisted("/foo/123")
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)

def test_tool_name_prefix_env(monkeypatch):
    from mcp_openapi_proxy.utils import normalize_tool_name
    monkeypatch.setenv("TOOL_NAME_PREFIX", "envprefix_")
    tool_name = normalize_tool_name("GET /foo/bar")
    assert tool_name.startswith("envprefix_")
    monkeypatch.delenv("TOOL_NAME_PREFIX", raising=False)

def test_tool_name_max_length_env(monkeypatch):
    from mcp_openapi_proxy.utils import normalize_tool_name
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "10")
    tool_name = normalize_tool_name("GET /foo/bar/baz")
    assert len(tool_name) <= 10
    monkeypatch.delenv("TOOL_NAME_MAX_LENGTH", raising=False)

def test_tool_name_max_length_env_invalid(monkeypatch):
    from mcp_openapi_proxy.utils import normalize_tool_name
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "notanint")
    tool_name = normalize_tool_name("GET /foo/bar/baz")
    assert tool_name.startswith("get_foo_bar")
    monkeypatch.delenv("TOOL_NAME_MAX_LENGTH", raising=False)

def test_fetch_openapi_spec_json_decode_error(tmp_path, monkeypatch):
    import os
    from mcp_openapi_proxy.utils import fetch_openapi_spec
    # Write invalid JSON to file
    file_path = tmp_path / "spec.json"
    file_path.write_text("{invalid json}")
    monkeypatch.setenv("OPENAPI_SPEC_FORMAT", "json")
    spec = fetch_openapi_spec(f"file://{file_path}")
    assert spec is None
    monkeypatch.delenv("OPENAPI_SPEC_FORMAT", raising=False)

def test_fetch_openapi_spec_yaml_decode_error(tmp_path, monkeypatch):
    import os
    from mcp_openapi_proxy.utils import fetch_openapi_spec
    # Write invalid YAML to file
    file_path = tmp_path / "spec.yaml"
    file_path.write_text(": : :")
    monkeypatch.setenv("OPENAPI_SPEC_FORMAT", "yaml")
    spec = fetch_openapi_spec(f"file://{file_path}")
    assert spec is None
    monkeypatch.delenv("OPENAPI_SPEC_FORMAT", raising=False)

def test_build_base_url_override_invalid(monkeypatch):
    from mcp_openapi_proxy.utils import build_base_url
    monkeypatch.setenv("SERVER_URL_OVERRIDE", "not_a_url")
    url = build_base_url({})
    assert url is None
    monkeypatch.delenv("SERVER_URL_OVERRIDE", raising=False)

def test_build_base_url_no_servers(monkeypatch):
    monkeypatch.delenv("SERVER_URL_OVERRIDE", raising=False)
    from mcp_openapi_proxy.utils import build_base_url
    url = build_base_url({})
    assert url is None

def test_handle_auth_basic(monkeypatch):
    from mcp_openapi_proxy.utils import handle_auth
    monkeypatch.setenv("API_KEY", "basic_key")
    monkeypatch.setenv("API_AUTH_TYPE", "basic")
    headers = handle_auth({})
    assert isinstance(headers, dict)
    # Should not add Authorization header for 'basic' (not implemented)
    assert "Authorization" not in headers
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_AUTH_TYPE", raising=False)

def test_handle_auth_api_key(monkeypatch):
    from mcp_openapi_proxy.utils import handle_auth
    monkeypatch.setenv("API_KEY", "api_key_value")
    monkeypatch.setenv("API_AUTH_TYPE", "api-key")
    monkeypatch.setenv("API_AUTH_HEADER", "X-API-KEY")
    headers = handle_auth({})
    assert headers.get("X-API-KEY") == "api_key_value"
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_AUTH_TYPE", raising=False)
    monkeypatch.delenv("API_AUTH_HEADER", raising=False)
