import os
import json
import pytest
from mcp_openapi_proxy.server_lowlevel import prompts, list_prompts, get_prompt
from types import SimpleNamespace
import asyncio


@pytest.mark.integration
def test_prompt_envvar_apisguru(monkeypatch):
    # Set up the PROMPT envvar
    custom_prompt = {
        "name": "test_prompt",
        "description": "A test prompt for APIs.guru integration.",
        "messages": [{"user": "Hello?", "assistant": "Hi from APIs.guru!"}],
    }
    monkeypatch.setenv("PROMPT", json.dumps(custom_prompt))
    monkeypatch.setenv("ENABLE_PROMPTS", "true")
    monkeypatch.setenv(
        "OPENAPI_SPEC_URL",
        "https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/apis.guru/2.2.0/openapi.yaml",
    )

    # Clear and reload prompts
    prompts.clear()
    from importlib import reload
    import mcp_openapi_proxy.server_lowlevel as lowlevel

    reload(lowlevel)

    # List prompts and check our custom prompt is present
    request = SimpleNamespace(params=SimpleNamespace())
    result = asyncio.run(lowlevel.list_prompts(request))
    prompt_names = [p.name for p in result.prompts]
    assert (
        "test_prompt" in prompt_names
    ), f"Custom prompt not found in list: {prompt_names}"

    # Get the custom prompt
    get_req = SimpleNamespace(params=SimpleNamespace(name="test_prompt", arguments={}))
    get_result = asyncio.run(lowlevel.get_prompt(get_req))
    messages = get_result.messages
    assert any(
        m.role == "assistant" and "Hi from APIs.guru!" in m.content.text
        for m in messages
    ), f"Custom prompt message missing: {messages}"
