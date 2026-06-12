def test_is_tool_whitelisted_multiple(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)
    monkeypatch.setenv("TOOL_WHITELIST", "/foo,/bar/{id}")
    assert is_tool_whitelisted("/foo/abc")
    assert is_tool_whitelisted("/bar/123")
    assert not is_tool_whitelisted("/baz/999")
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)


def test_is_tool_whitelisted_dot_paths(monkeypatch):
    """Slack-style method paths: /users must match /users.list (issue #27)."""
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    monkeypatch.setenv("TOOL_WHITELIST", "/chat,/users,/conversations")
    assert is_tool_whitelisted("/users.list")
    assert is_tool_whitelisted("/chat.postMessage")
    assert is_tool_whitelisted("/conversations.history")
    # prefix must stop at a delimiter: /chat must NOT match /chatter
    assert not is_tool_whitelisted("/chatter")
    assert not is_tool_whitelisted("/usersearch")
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)


def test_is_tool_whitelisted_slash_still_works(monkeypatch):
    from mcp_openapi_proxy.utils import is_tool_whitelisted
    monkeypatch.setenv("TOOL_WHITELIST", "/ipam/ip-addresses")
    assert is_tool_whitelisted("/ipam/ip-addresses")
    assert is_tool_whitelisted("/ipam/ip-addresses/{id}")
    assert not is_tool_whitelisted("/ipam/ip-ranges")
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)
