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
    # Corrected expectation: '+' should be replaced by '_'
    assert normalize_tool_name("GET /search+filter/results") == "get_search_filter_results"
    assert normalize_tool_name("GET /user_profiles/active") == "get_user_profiles_active"
    assert normalize_tool_name("INVALID") == "unknown_tool"

def test_detect_response_type_json():
    content, msg = detect_response_type('{"key": "value"}')
    assert content.type == "text"
    # The content.text should now be the stringified JSON
    assert content.text == '{"key": "value"}'
    # The message indicates it was JSON but stringified
    assert "JSON response (stringified)" in msg

def test_detect_response_type_text():
    content, msg = detect_response_type("plain text")
    assert content.type == "text"
    assert content.text == "plain text"
    # Corrected expectation for the log message
    assert "Non-JSON text response" in msg

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

def test_handle_auth_custom_scheme_token(monkeypatch):
    # Unknown API_AUTH_TYPE becomes a custom scheme prefix (NetBox: "Token <key>").
    monkeypatch.setenv("API_KEY", "testkey")
    monkeypatch.setenv("API_AUTH_TYPE", "Token")
    headers = handle_auth({"method": "GET"})
    assert headers == {"Authorization": "Token testkey"}

def test_handle_auth_custom_scheme_preserves_case(monkeypatch):
    # The raw type string is kept verbatim, not lowercased, in the header value.
    monkeypatch.setenv("API_KEY", "testkey")
    monkeypatch.setenv("API_AUTH_TYPE", "ApiKey")
    headers = handle_auth({"method": "GET"})
    assert headers == {"Authorization": "ApiKey testkey"}

def test_handle_auth_capitalized_api_key_preserves_scheme(monkeypatch):
    # API_AUTH_TYPE=Api-Key must send "Authorization: Api-Key <key>" (Zep
    # requires the scheme prefix; lowercase folding previously stripped it).
    monkeypatch.setenv("API_KEY", "testkey")
    monkeypatch.setenv("API_AUTH_TYPE", "Api-Key")
    headers = handle_auth({"method": "GET"})
    assert headers == {"Authorization": "Api-Key testkey"}

def test_handle_auth_lowercase_api_key_stays_raw(monkeypatch):
    # Lowercase `api-key` in the default Authorization header keeps the raw
    # key (x-apikey-style consumers), unchanged behavior.
    monkeypatch.setenv("API_KEY", "testkey")
    monkeypatch.setenv("API_AUTH_TYPE", "api-key")
    headers = handle_auth({"method": "GET"})
    assert headers == {"Authorization": "testkey"}

def test_handle_auth_api_key_custom_header_stays_raw(monkeypatch):
    # api-key + a named header (virustotal x-apikey) keeps the raw key.
    monkeypatch.setenv("API_KEY", "testkey")
    monkeypatch.setenv("API_AUTH_TYPE", "api-key")
    monkeypatch.setenv("API_AUTH_HEADER", "x-apikey")
    headers = handle_auth({"method": "GET"})
    assert headers == {"x-apikey": "testkey"}

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

def test_fetch_openapi_spec_ssl_verification_disabled(mock_requests_get, monkeypatch):
    """Test that SSL verification can be disabled via IGNORE_SSL_SPEC"""
    mock_response = MagicMock()
    mock_response.text = '{"test": "data"}'
    mock_requests_get.return_value = mock_response

    monkeypatch.setenv('IGNORE_SSL_SPEC', 'true')
    fetch_openapi_spec("https://example.com/spec.json")
    # No need to del os.environ with monkeypatch

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
    # No need to import os or the function again
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
    # No need to import os or the function again
    monkeypatch.delenv("TOOL_NAME_PREFIX", raising=False)
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "10")
    raw_name = "GET /users/list" # Normalized: get_users_list (14 chars)
    tool_name = normalize_tool_name(raw_name)
    assert len(tool_name) == 10
    # Expected truncated name
    assert tool_name == "get_users_", f"Expected 'get_users_', got {tool_name}"
    # monkeypatch handles cleanup automatically

def test_tool_name_max_length_invalid(monkeypatch, caplog):
    # No need to import os or the function again
    caplog.set_level("WARNING")
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "abc")
    tool_name = normalize_tool_name("GET /users/list")
    assert tool_name == "get_users_list"
    assert any("Invalid TOOL_NAME_MAX_LENGTH env var: abc" in r.message for r in caplog.records)
    # monkeypatch handles cleanup automatically

def test_tool_name_with_path_param(monkeypatch):
    # No need to import the function again
    monkeypatch.delenv("TOOL_NAME_PREFIX", raising=False)
    tool_name = normalize_tool_name("POST /items/{item_id}")
    assert tool_name == "post_items_by_item_id"

def test_tool_name_malformed(monkeypatch):
    # No need to import the function again
    monkeypatch.delenv("TOOL_NAME_PREFIX", raising=False)
    tool_name = normalize_tool_name("foobar")  # no space, should trigger fallback
    assert tool_name == "unknown_tool"

def test_is_tool_whitelist_set(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelist_set
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)
    assert not is_tool_whitelist_set()
    monkeypatch.setenv("TOOL_WHITELIST", "/foo")
    assert is_tool_whitelist_set()
    # monkeypatch handles cleanup automatically

def test_is_tool_whitelisted_no_whitelist(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)
    assert is_tool_whitelisted("/anything")

def test_is_tool_whitelisted_simple_prefix(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    monkeypatch.setenv("TOOL_WHITELIST", "/foo")
    assert is_tool_whitelisted("/foo/bar")
    assert is_tool_whitelisted("/foo") # Should match exact prefix too
    assert not is_tool_whitelisted("/fo")
    assert not is_tool_whitelisted("/bar/foo")
    # monkeypatch handles cleanup automatically

def test_is_tool_whitelisted_placeholder(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    # This test seems incorrect - it sets TOOL_NAME_PREFIX but checks TOOL_WHITELIST logic
    # Let's fix it to test whitelisting with placeholders
    monkeypatch.setenv("TOOL_WHITELIST", "/foo/{id}/bar,/baz/{name}")
    assert is_tool_whitelisted("/foo/123/bar")
    assert is_tool_whitelisted("/foo/abc/bar/extra") # Matches start
    assert not is_tool_whitelisted("/foo/123") # Doesn't match full pattern
    assert is_tool_whitelisted("/baz/test_name")
    assert not is_tool_whitelisted("/baz")
    # monkeypatch handles cleanup automatically

def test_tool_name_prefix_env(monkeypatch):
    # No need to import the function again
    monkeypatch.setenv("TOOL_NAME_PREFIX", "envprefix_")
    tool_name = normalize_tool_name("GET /foo/bar")
    assert tool_name.startswith("envprefix_")
    assert tool_name == "envprefix_get_foo_bar"
    # monkeypatch handles cleanup automatically

def test_tool_name_max_length_env(monkeypatch):
    # No need to import the function again
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "10")
    tool_name = normalize_tool_name("GET /foo/bar/baz") # get_foo_bar_baz (15 chars)
    assert len(tool_name) <= 10
    assert tool_name == "get_foo_ba" # Expected truncated name
    # monkeypatch handles cleanup automatically

def test_tool_name_max_length_env_invalid(monkeypatch):
    # No need to import the function again
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "notanint")
    tool_name = normalize_tool_name("GET /foo/bar/baz")
    assert tool_name == "get_foo_bar_baz"
    # monkeypatch handles cleanup automatically

def test_fetch_openapi_spec_json_decode_error(tmp_path, monkeypatch):
    # No need to import os or the function again
    # Write invalid JSON to file
    file_path = tmp_path / "spec.json"
    file_path.write_text("{invalid json}")
    monkeypatch.setenv("OPENAPI_SPEC_FORMAT", "json")
    spec = fetch_openapi_spec(f"file://{file_path}")
    assert spec is None
    # monkeypatch handles cleanup automatically

def test_fetch_openapi_spec_yaml_decode_error(tmp_path, monkeypatch):
    # No need to import os or the function again
    # Write invalid YAML to file
    file_path = tmp_path / "spec.yaml"
    file_path.write_text(": : :")
    monkeypatch.setenv("OPENAPI_SPEC_FORMAT", "yaml")
    spec = fetch_openapi_spec(f"file://{file_path}")
    assert spec is None
    # monkeypatch handles cleanup automatically

def test_build_base_url_override_invalid(monkeypatch):
    # No need to import the function again
    monkeypatch.setenv("SERVER_URL_OVERRIDE", "not_a_url")
    url = build_base_url({})
    assert url is None
    # monkeypatch handles cleanup automatically

def test_build_base_url_no_servers(monkeypatch):
    monkeypatch.delenv("SERVER_URL_OVERRIDE", raising=False)
    # No need to import the function again
    url = build_base_url({})
    assert url is None

def test_handle_auth_basic(monkeypatch):
    # No need to import the function again
    monkeypatch.setenv("API_KEY", "basic_key")
    monkeypatch.setenv("API_AUTH_TYPE", "basic")
    headers = handle_auth({})
    assert isinstance(headers, dict)
    # Should not add Authorization header for 'basic' (not implemented)
    assert "Authorization" not in headers
    # monkeypatch handles cleanup automatically

def test_handle_auth_api_key(monkeypatch):
    # No need to import the function again
    monkeypatch.setenv("API_KEY", "api_key_value")
    monkeypatch.setenv("API_AUTH_TYPE", "api-key")
    monkeypatch.setenv("API_AUTH_HEADER", "X-API-KEY")
    headers = handle_auth({})
    assert headers.get("X-API-KEY") == "api_key_value"
    # monkeypatch handles cleanup automatically
