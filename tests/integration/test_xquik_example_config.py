import json
from pathlib import Path

import pytest
import requests

from mcp_openapi_proxy.openapi import register_functions


@pytest.mark.integration
def test_xquik_example_config_points_to_search_openapi(monkeypatch):
    config_path = Path("examples/xquik-claude_desktop_config.json")
    config = json.loads(config_path.read_text())

    env = config["mcpServers"]["xquik"]["env"]
    assert env["OPENAPI_SPEC_URL"] == "https://xquik.com/openapi.json"
    assert env["TOOL_WHITELIST"] == "/api/v1/x/tweets/search"
    assert env["API_AUTH_TYPE"] == "api-key"
    assert env["API_AUTH_HEADER"] == "x-api-key"

    response = requests.get(env["OPENAPI_SPEC_URL"], timeout=10)
    response.raise_for_status()
    spec = response.json()

    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == "Xquik API"
    assert "/api/v1/x/tweets/search" in spec["paths"]

    monkeypatch.setenv("TOOL_WHITELIST", env["TOOL_WHITELIST"])
    tools = register_functions(spec)
    assert any(tool.name == "get_v1_x_tweets_search" for tool in tools)
