"""ADDITIONAL_RESOURCES: user-defined resources served from local files (issue #33)."""
import asyncio
import importlib

import pytest


def _reload_server(monkeypatch, env_value):
    monkeypatch.setenv("OPENAPI_SPEC_URL", "file:///dev/null")
    monkeypatch.setenv("ADDITIONAL_RESOURCES", env_value)
    import mcp_openapi_proxy.server_lowlevel as srv
    return importlib.reload(srv)


def test_additional_resources_listed_and_read(monkeypatch, tmp_path):
    policy = tmp_path / "policy.md"
    policy.write_text("# Naming Policy\nUse lowercase hostnames.")
    srv = _reload_server(monkeypatch, f"netbox-naming-policy={policy}")

    names = [r.name for r in srv.resources]
    assert "spec_file" in names
    assert "netbox-naming-policy" in names

    from mcp import types
    req = types.ReadResourceRequest(
        method="resources/read",
        params=types.ReadResourceRequestParams(uri="file:///netbox-naming-policy"),
    )
    result = asyncio.get_event_loop().run_until_complete(srv.read_resource(req))
    assert "lowercase hostnames" in result.contents[0].text
    assert result.contents[0].mimeType == "text/markdown"


def test_additional_resources_missing_file(monkeypatch, tmp_path):
    srv = _reload_server(monkeypatch, f"ghost={tmp_path}/nope.md")
    req_cls = __import__("mcp", fromlist=["types"]).types
    req = req_cls.ReadResourceRequest(
        method="resources/read",
        params=req_cls.ReadResourceRequestParams(uri="file:///ghost"),
    )
    result = asyncio.get_event_loop().run_until_complete(srv.read_resource(req))
    assert "unavailable" in result.contents[0].text


def test_additional_resources_malformed_entries_ignored(monkeypatch):
    srv = _reload_server(monkeypatch, "no-equals-sign,=,name=")
    assert [r.name for r in srv.resources] == ["spec_file"]


def test_no_env_keeps_default_only(monkeypatch):
    srv = _reload_server(monkeypatch, "")
    assert [r.name for r in srv.resources] == ["spec_file"]
