import os
import json
import asyncio
import pytest
from unittest.mock import patch
from mcp_openapi_proxy.server_lowlevel import list_prompts, get_prompt
from mcp_openapi_proxy.server_fastmcp import list_functions, call_function
from types import SimpleNamespace

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.delenv("OPENAPI_SPEC_URL", raising=False)
    monkeypatch.setenv("OPENAPI_SPEC_URL", "http://dummy.com")

def test_lowlevel_list_prompts(mock_env):
    request = SimpleNamespace(params=SimpleNamespace())
    result = asyncio.run(list_prompts(request))
    assert len(result.prompts) > 0, "Expected at least one prompt"
    assert any(p.name == "summarize_spec" for p in result.prompts), "summarize_spec not found"

def test_lowlevel_get_prompt_valid(mock_env):
    request = SimpleNamespace(params=SimpleNamespace(name="summarize_spec", arguments={}))
    result = asyncio.run(get_prompt(request))
    assert "blueprint" in result.messages[0].content.text, "Expected 'blueprint' in prompt response"

def test_fastmcp_list_prompts(mock_env):
    with patch('mcp_openapi_proxy.server_fastmcp.fetch_openapi_spec', return_value={"paths": {}}):
        tools_json = list_functions(env_key="OPENAPI_SPEC_URL")
        tools = json.loads(tools_json)
        assert any(t["name"] == "list_prompts" for t in tools), "list_prompts not found"
        result = call_function(function_name="list_prompts", parameters={}, env_key="OPENAPI_SPEC_URL")
        prompts = json.loads(result)
        assert len(prompts) > 0, "Expected at least one prompt"
        assert any(p["name"] == "summarize_spec" for p in prompts), "summarize_spec not found"
