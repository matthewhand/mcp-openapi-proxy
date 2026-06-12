"""
Regression tests for issue #11: TOOL_NAME_MAX_LENGTH not respected.

https://github.com/matthewhand/mcp-openapi-proxy/issues/11

The env var must be honoured everywhere tool names are produced:
 - mcp_openapi_proxy.utils.normalize_tool_name (the shared helper)
 - the low-level registration path (mcp_openapi_proxy.openapi.register_functions)
 - the FastMCP path (mcp_openapi_proxy.server_fastmcp.list_functions)

Invalid values ("abc", "-1", "0") must be ignored gracefully.

Crucially, honouring a short limit must not silently drop endpoints: when
truncation makes two distinct operations collide on the same name, both must
still be registered (with unique names within the limit) and remain callable
(lookup_operation_details must resolve the deduplicated names).
"""

import json

import pytest

from mcp_openapi_proxy import openapi, server_fastmcp, server_lowlevel
from mcp_openapi_proxy.utils import normalize_tool_name


def make_spec(paths):
    return {
        "openapi": "3.0.0",
        "info": {"title": "test", "version": "1.0"},
        "paths": paths,
    }


COLLIDING_SPEC = make_spec({
    # Both normalize to "post_communication_n..." and collide when truncated
    # to 20 chars.
    "/communication/notification/email/send": {
        "post": {"summary": "send", "responses": {}}
    },
    "/communication/notification/email/receive": {
        "post": {"summary": "receive", "responses": {}}
    },
})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TOOL_NAME_PREFIX", raising=False)
    monkeypatch.delenv("TOOL_NAME_MAX_LENGTH", raising=False)
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)


def test_normalize_tool_name_respects_env_limit(monkeypatch):
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "10")
    name = normalize_tool_name("GET /some/very/long/path/that/keeps/going")
    assert len(name) <= 10, f"normalize_tool_name ignored TOOL_NAME_MAX_LENGTH: {name!r}"


def test_normalize_tool_name_env_limit_includes_prefix(monkeypatch):
    # Issue #11 reporter used TOOL_NAME_PREFIX together with TOOL_NAME_MAX_LENGTH.
    monkeypatch.setenv("TOOL_NAME_PREFIX", "otrs_")
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "58")
    name = normalize_tool_name(
        "POST /communication/notification/event/transport/email/{NotificationID}/extra"
    )
    assert len(name) <= 58, f"prefixed name exceeds custom limit: {name!r}"
    assert name.startswith("otrs_")


@pytest.mark.parametrize("bad_value", ["abc", "-1", "0"])
def test_invalid_env_values_ignored_gracefully(monkeypatch, bad_value):
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", bad_value)
    # Must not raise, must not truncate below the protocol limit.
    name = normalize_tool_name("GET /users/list")
    assert name == "get_users_list"


def test_register_functions_respects_env_limit(monkeypatch):
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "10")
    spec = make_spec({
        "/services/{serviceId}/custom-domains/{customDomainIdOrName}/verify": {
            "post": {"summary": "verify", "responses": {}}
        },
    })
    tools = openapi.register_functions(spec)
    assert tools, "expected at least one registered tool"
    for tool in tools:
        assert len(tool.name) <= 10, (
            f"registration path ignored TOOL_NAME_MAX_LENGTH: {tool.name!r}"
        )


def test_register_functions_does_not_drop_tools_on_truncation_collision(monkeypatch):
    """Honouring the limit must not silently drop colliding endpoints."""
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "20")
    tools = openapi.register_functions(COLLIDING_SPEC)
    names = [t.name for t in tools]
    assert len(names) == 2, (
        f"expected both operations registered, got {names} - "
        "truncation collision silently dropped a tool"
    )
    assert len(set(names)) == 2, f"tool names are not unique: {names}"
    for name in names:
        assert len(name) <= 20, f"deduplicated name exceeds limit: {name!r}"


def test_lookup_resolves_deduplicated_names(monkeypatch):
    """Every registered (deduplicated) name must remain callable via lookup."""
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "20")
    tools = openapi.register_functions(COLLIDING_SPEC)
    assert len(tools) == 2
    resolved_paths = set()
    for tool in tools:
        details = openapi.lookup_operation_details(tool.name, COLLIDING_SPEC)
        assert details is not None, f"lookup failed for registered tool {tool.name!r}"
        resolved_paths.add(details["path"])
    assert resolved_paths == {
        "/communication/notification/email/send",
        "/communication/notification/email/receive",
    }, f"lookup did not resolve each tool to its own operation: {resolved_paths}"


def test_lowlevel_lookup_resolves_deduplicated_names(monkeypatch):
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "20")
    tools = openapi.register_functions(COLLIDING_SPEC)
    assert len(tools) == 2
    resolved_paths = set()
    for tool in tools:
        details = server_lowlevel.lookup_operation_details(tool.name, COLLIDING_SPEC)
        assert details is not None, (
            f"server_lowlevel lookup failed for registered tool {tool.name!r}"
        )
        resolved_paths.add(details["path"])
    assert len(resolved_paths) == 2, (
        f"server_lowlevel lookup did not resolve each tool to its own operation: {resolved_paths}"
    )


def test_fastmcp_list_functions_respects_env_limit(monkeypatch):
    monkeypatch.setenv("TOOL_NAME_MAX_LENGTH", "20")
    monkeypatch.setenv("OPENAPI_SPEC_URL", "http://dummy.example/spec.json")
    monkeypatch.setattr(server_fastmcp, "fetch_openapi_spec", lambda url: COLLIDING_SPEC)
    functions = json.loads(server_fastmcp.list_functions(env_key="OPENAPI_SPEC_URL"))
    # Only consider functions derived from the spec (list_functions also
    # returns built-in meta functions such as list_resources).
    names = [f["name"] for f in functions if f.get("path") in COLLIDING_SPEC["paths"]]
    for name in names:
        assert len(name) <= 20, f"fastmcp path ignored TOOL_NAME_MAX_LENGTH: {name!r}"
    assert len(names) == len(set(names)), f"fastmcp produced duplicate names: {names}"
    assert len(names) == 2, (
        f"fastmcp list_functions dropped a colliding tool: {names}"
    )
