"""
Regression tests for the mcp dependency pin (issue: unpinned mcp>=1.2.0).

mcp 2.x is a breaking rewrite of the Python SDK: `mcp.server.fastmcp` was
renamed to `mcp.server.mcpserver.MCPServer`, and `types.Resource.uri` changed
type, among other changes. With the old unbounded `mcp[cli]>=1.2.0` constraint
a fresh `pip install mcp-openapi-proxy` resolved to mcp 2.x and both server
modes crashed at import time:

- server_fastmcp:  ModuleNotFoundError: No module named 'mcp.server.fastmcp'
- server_lowlevel: pydantic ValidationError constructing types.Resource
                   (uri: "Input should be a valid string", got AnyUrl)

These tests fail closed if mcp 2.x is ever installed alongside this package,
and guard the declared constraint so 2.x cannot be silently selected again.
"""

import re
from importlib import metadata
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _declared_mcp_specifier() -> SpecifierSet:
    """Extract the mcp version specifier declared in pyproject.toml.

    Parsed from the source tree (not installed metadata) so the guard also
    runs correctly when tests execute without the package installed.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'"mcp(?:\[[^\]]*\])?\s*([><=!~][^"]+)"', text)
    assert match, "mcp dependency with version specifier not found in pyproject.toml"
    return SpecifierSet(match.group(1))


def test_declared_constraint_excludes_mcp_2x():
    """The pyproject constraint must not allow any mcp 2.x release."""
    spec = _declared_mcp_specifier()
    for two_x in ("2.0.0", "2.0.1", "2.1.1", "2.99.0"):
        assert not spec.contains(two_x), (
            f"pyproject.toml mcp constraint {spec!r} permits mcp {two_x}; "
            "mcp 2.x breaks both server modes at import (FastMCP renamed, "
            "Resource.uri type change). Keep the <2 upper bound."
        )


def test_declared_constraint_accepts_supported_1x():
    """The constraint must still resolve to the 1.x line this package uses."""
    spec = _declared_mcp_specifier()
    for one_x in ("1.2.0", "1.2.1", "1.29.1"):
        assert spec.contains(one_x), (
            f"pyproject.toml mcp constraint {spec!r} rejects mcp {one_x}"
        )


def test_installed_mcp_is_1x():
    """Fail closed if the environment somehow has mcp 2.x installed."""
    installed = Version(metadata.version("mcp"))
    assert installed.major == 1, (
        f"Installed mcp is {installed}, but mcp-openapi-proxy only supports "
        "mcp 1.x (2.x renamed mcp.server.fastmcp and changed types.Resource)."
    )
    declared = _declared_mcp_specifier()
    assert declared.contains(str(installed)), (
        f"Installed mcp {installed} violates declared constraint {declared!r}"
    )


def test_mcp_1x_server_api_surface_present():
    """Import the exact mcp SDK symbols both server modes depend on.

    Every one of these disappears or breaks on mcp 2.x, so this test crashes
    there instead of letting the proxy fail later at runtime.
    """
    from mcp import types  # noqa: F401
    from mcp.server.fastmcp import FastMCP  # noqa: F401  (gone in 2.x)
    from mcp.server.lowlevel import Server  # noqa: F401
    from mcp.server.models import InitializationOptions  # noqa: F401
    from mcp.server.stdio import stdio_server  # noqa: F401

    # server_lowlevel builds this Resource at import time; on mcp 2.x the
    # uri field type changed and this raises pydantic.ValidationError.
    from pydantic import AnyUrl

    resource = types.Resource(
        uri=AnyUrl("file:///openapi_spec.json"),
        name="OpenAPI Specification",
        mimeType="application/json",
    )
    assert str(resource.uri) == "file:///openapi_spec.json"


def test_both_server_modes_import():
    """The original failure: both server modules crashed at import on mcp 2.x."""
    import importlib

    for mod in (
        "mcp_openapi_proxy.server_lowlevel",
        "mcp_openapi_proxy.server_fastmcp",
    ):
        importlib.import_module(mod)


def test_uv_lock_pins_mcp_1x():
    """uv.lock must lock mcp to a 1.x version consistent with pyproject."""
    lock_path = PYPROJECT.parent / "uv.lock"
    if not lock_path.exists():
        pytest.skip("uv.lock not present")
    text = lock_path.read_text(encoding="utf-8")
    match = re.search(r'name = "mcp"\nversion = "([^"]+)"', text)
    assert match, "mcp entry not found in uv.lock"
    locked = Version(match.group(1))
    assert locked.major == 1, f"uv.lock resolves mcp to {locked}, expected 1.x"
    assert _declared_mcp_specifier().contains(str(locked))
