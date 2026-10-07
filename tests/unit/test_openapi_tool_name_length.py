import pytest
from mcp_openapi_proxy import openapi
from mcp_openapi_proxy.utils import normalize_tool_name


@pytest.mark.parametrize(
    "path,method",
    [
        ("/short", "get"),
        (
            "/this/is/a/very/long/path/that/should/trigger/the/length/limit/check/and/fail/if/not/truncated",
            "get",
        ),
        ("/foo/bar/baz/" + "x" * 80, "post"),
    ],
)
def test_tool_name_length_enforced(path, method):
    raw_name = f"{method.upper()} {path}"
    tool_name = normalize_tool_name(raw_name)
    assert (
        len(tool_name) <= 64
    ), f"Tool name too long: {tool_name} ({len(tool_name)} chars)"


def test_register_functions_tool_names_do_not_exceed_limit():
    # Spec with intentionally long paths
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/short": {"get": {"summary": "Short path"}},
            "/this/is/a/very/long/path/that/should/trigger/the/length/limit/check/and/fail/if/not/truncated": {
                "get": {"summary": "Long path"}
            },
            "/foo/bar/baz/" + "x" * 80: {"post": {"summary": "Extremely long path"}},
        },
    }
    tools = openapi.register_functions(spec)
    for tool in tools:
        assert (
            len(tool.name) <= 64
        ), f"Registered tool name too long: {tool.name} ({len(tool.name)} chars)"
