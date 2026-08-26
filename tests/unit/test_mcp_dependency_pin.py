"""
Regression test for the fresh-install crash caused by an unpinned mcp dependency.

`mcp[cli]>=1.2.0` used to resolve to mcp 2.x on fresh installs, which broke both
server modes at import time:
- FastMCP mode: `mcp.server.fastmcp` was removed in 2.x (FastMCP -> MCPServer).
- Low-level mode: `types.Resource.uri` changed from AnyUrl to str, so the
  module-level Resource construction failed pydantic validation.

These tests assert the installed mcp is a pinned 1.x and that both server modes
actually import against it.
"""

import importlib
import importlib.metadata

from packaging.requirements import Requirement
from packaging.version import Version


def _installed_mcp_version() -> Version:
    return Version(importlib.metadata.version("mcp"))


def test_installed_mcp_is_1x():
    """The environment must resolve mcp to the known-good 1.x line."""
    version = _installed_mcp_version()
    assert version.major == 1, (
        f"mcp {version} is installed; mcp 2.x breaks both server modes "
        "(see pin in pyproject.toml)"
    )


def test_pyproject_pins_mcp_below_2():
    """The declared dependency must exclude mcp 2.x so fresh installs stay on 1.x."""
    requires = importlib.metadata.requires("mcp-openapi-proxy") or []
    mcp_reqs = [
        Requirement(r) for r in requires if Requirement(r).name.lower() == "mcp"
    ]
    assert mcp_reqs, "mcp-openapi-proxy must declare a dependency on mcp"
    for req in mcp_reqs:
        assert not req.specifier.contains("2.0.0", prereleases=True), (
            f"dependency '{req}' permits mcp 2.x, which crashes both server modes; "
            "pin it below 2 (e.g. 'mcp[cli]>=1.2.0,<2')"
        )


def test_lowlevel_server_imports():
    """Low-level mode must import cleanly against the pinned mcp."""
    module = importlib.import_module("mcp_openapi_proxy.server_lowlevel")
    assert hasattr(module, "run_server")


def test_fastmcp_server_imports():
    """FastMCP (simple) mode must import cleanly against the pinned mcp."""
    module = importlib.import_module("mcp_openapi_proxy.server_fastmcp")
    assert hasattr(module, "run_simple_server")
