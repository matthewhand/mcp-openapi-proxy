import os

from mcp_openapi_proxy.protocol import advertised_server_name, advertised_server_title


def test_explicit_mcp_server_name(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_NAME", "gpt-terminal-plus")
    monkeypatch.setenv("OPENAPI_SPEC_URL", "https://example.com/openapi.json")
    assert advertised_server_name() == "gpt-terminal-plus"


def test_openapi_server_name_alias(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_NAME", raising=False)
    monkeypatch.setenv("OPENAPI_SERVER_NAME", "netbox")
    assert advertised_server_name() == "netbox"


def test_file_url_uses_stem(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_NAME", raising=False)
    monkeypatch.delenv("OPENAPI_SERVER_NAME", raising=False)
    monkeypatch.setenv("OPENAPI_SPEC_URL", "file:///home/chatgpt/mcp-gateway/specs/wordpress-dev.json")
    assert advertised_server_name() == "wordpress-dev"


def test_http_url_uses_host(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_NAME", raising=False)
    monkeypatch.delenv("OPENAPI_SERVER_NAME", raising=False)
    monkeypatch.setenv("OPENAPI_SPEC_URL", "https://glama.ai/api/mcp/openapi.json")
    assert advertised_server_name() == "glama.ai"


def test_fallback_without_spec(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_NAME", raising=False)
    monkeypatch.delenv("OPENAPI_SERVER_NAME", raising=False)
    monkeypatch.delenv("OPENAPI_SPEC_URL", raising=False)
    assert advertised_server_name() == "openapi-proxy"


def test_title_optional(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_TITLE", raising=False)
    assert advertised_server_title() is None
    monkeypatch.setenv("MCP_SERVER_TITLE", "GPT Terminal Plus")
    assert advertised_server_title() == "GPT Terminal Plus"


def test_build_server_uses_env_name(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_NAME", "apisguru")
    monkeypatch.setenv("OPENAPI_SPEC_URL", "http://dummy.com")
    from mcp_openapi_proxy.server_lowlevel import build_server

    server = build_server()
    assert server.name == "apisguru"
