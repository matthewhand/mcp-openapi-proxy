"""
Regression tests for the mcp 2.x dependency pin (issue #65).

0.3.4 capped mcp at <2 because 2.x crashed both server modes at import.
0.4.0 ports to mcp 2.x / protocol 2026-07-28. These tests fail closed if
the declared constraint slips back to 1.x-only or unbounded 3.x.
"""

import re
from importlib import metadata
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _declared_mcp_specifier() -> SpecifierSet:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'"mcp(?:\[[^\]]*\])?\s*([><=!~][^"]+)"', text)
    assert match, "mcp dependency with version specifier not found in pyproject.toml"
    return SpecifierSet(match.group(1))


def test_declared_constraint_requires_mcp_2x():
    spec = _declared_mcp_specifier()
    for two_x in ("2.0.0", "2.0.1", "2.1.1"):
        assert spec.contains(two_x), (
            f"pyproject.toml mcp constraint {spec!r} rejects mcp {two_x}"
        )
    assert not spec.contains("1.29.1"), (
        f"pyproject.toml mcp constraint {spec!r} still allows mcp 1.x"
    )
    assert not spec.contains("3.0.0"), (
        f"pyproject.toml mcp constraint {spec!r} permits mcp 3.x"
    )


def test_installed_mcp_is_2x():
    installed = Version(metadata.version("mcp"))
    assert installed.major == 2, (
        f"Installed mcp is {installed}, but mcp-openapi-proxy 0.4 requires mcp 2.x"
    )
    declared = _declared_mcp_specifier()
    assert declared.contains(str(installed)), (
        f"Installed mcp {installed} violates declared constraint {declared!r}"
    )


def test_mcp_2x_server_api_surface_present():
    from mcp import types  # noqa: F401
    from mcp.server.mcpserver import MCPServer  # noqa: F401
    from mcp.server.lowlevel import Server  # noqa: F401
    from mcp.server.models import InitializationOptions  # noqa: F401
    from mcp.server.stdio import stdio_server  # noqa: F401
    from mcp.server import CacheHint  # noqa: F401

    resource = types.Resource(
        uri="file:///openapi_spec.json",
        name="OpenAPI Specification",
        mime_type="application/json",
    )
    assert resource.uri == "file:///openapi_spec.json"


def test_both_server_modes_import():
    import importlib

    for mod in (
        "mcp_openapi_proxy.server_lowlevel",
        "mcp_openapi_proxy.server_fastmcp",
    ):
        importlib.import_module(mod)


def test_uv_lock_pins_mcp_2x():
    lock_path = PYPROJECT.parent / "uv.lock"
    if not lock_path.exists():
        pytest.skip("uv.lock not present")
    text = lock_path.read_text(encoding="utf-8")
    match = re.search(r'name = "mcp"\nversion = "([^"]+)"', text)
    assert match, "mcp entry not found in uv.lock"
    locked = Version(match.group(1))
    assert locked.major == 2, f"uv.lock resolves mcp to {locked}, expected 2.x"
    assert _declared_mcp_specifier().contains(str(locked))
