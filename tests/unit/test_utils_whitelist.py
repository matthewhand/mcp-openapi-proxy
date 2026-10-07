def test_is_tool_whitelisted_multiple(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted

    monkeypatch.delenv("TOOL_WHITELIST", raising=False)
    monkeypatch.setenv("TOOL_WHITELIST", "/foo,/bar/{id}")
    assert is_tool_whitelisted("/foo/abc")
    assert is_tool_whitelisted("/bar/123")
    assert not is_tool_whitelisted("/baz/999")
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)
