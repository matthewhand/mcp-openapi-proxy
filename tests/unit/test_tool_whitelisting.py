import os
import pytest
from mcp_openapi_proxy.utils import is_tool_whitelisted


@pytest.fixture(autouse=True)
def reset_tool_whitelist_env(monkeypatch):
    monkeypatch.delenv("TOOL_WHITELIST", raising=False)


def test_no_whitelist_allows_any_endpoint():
    assert is_tool_whitelisted("/anything") is True
    assert is_tool_whitelisted("/tasks/123") is True


def test_simple_prefix_whitelist(monkeypatch):
    monkeypatch.setenv("TOOL_WHITELIST", "/tasks")
    assert is_tool_whitelisted("/tasks") is True
    assert is_tool_whitelisted("/tasks/123") is True
    assert is_tool_whitelisted("/projects") is False


def test_multiple_prefixes(monkeypatch):
    monkeypatch.setenv("TOOL_WHITELIST", "/tasks, /projects")
    assert is_tool_whitelisted("/tasks/abc") is True
    assert is_tool_whitelisted("/projects/xyz") is True
    assert is_tool_whitelisted("/collections") is False


def test_placeholder_whitelist(monkeypatch):
    monkeypatch.setenv("TOOL_WHITELIST", "/collections/{collection_id}")
    assert is_tool_whitelisted("/collections/abc123") is True
    assert is_tool_whitelisted("/collections/") is False
    assert is_tool_whitelisted("/collections/abc123/items") is True


def test_multiple_placeholders(monkeypatch):
    monkeypatch.setenv("TOOL_WHITELIST", "/company/{company_id}/project/{project_id}")
    assert is_tool_whitelisted("/company/comp123/project/proj456") is True
    assert is_tool_whitelisted("/company//project/proj456") is False
    assert is_tool_whitelisted("/company/comp123/project") is False
