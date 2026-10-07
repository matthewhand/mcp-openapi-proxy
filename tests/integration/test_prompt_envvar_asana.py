import os
import json
import pytest
from mcp_openapi_proxy.server_lowlevel import prompts, list_prompts, get_prompt
from types import SimpleNamespace
import asyncio


@pytest.mark.integration
def test_prompt_envvar_asana(monkeypatch):
    # Skip if ASANA_API_KEY is missing or placeholder
    asana_api_key = os.getenv("ASANA_API_KEY")
    if not asana_api_key or "your_key" in asana_api_key.lower():
        pytest.skip("ASANA_API_KEY missing or placeholder—please set it in .env!")

    # Set up the PROMPT envvar
    custom_prompt = {
        "name": "asana_prompt",
        "description": "A test prompt for Asana integration.",
        "messages": [
            {
                "user": "What is Asana?",
                "assistant": "Asana is a work management platform.",
            }
        ],
    }
    monkeypatch.setenv("PROMPT", json.dumps(custom_prompt))
    monkeypatch.setenv("ENABLE_PROMPTS", "true")
    monkeypatch.setenv(
        "OPENAPI_SPEC_URL",
        "https://raw.githubusercontent.com/Asana/openapi/refs/heads/master/defs/asana_oas.yaml",
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
        "asana_prompt" in prompt_names
    ), f"Custom prompt not found in list: {prompt_names}"

    # Get the custom prompt
    get_req = SimpleNamespace(params=SimpleNamespace(name="asana_prompt", arguments={}))
    get_result = asyncio.run(lowlevel.get_prompt(get_req))
    messages = get_result.messages
    assert any(
        m.role == "assistant"
        and "Asana is a work management platform." in m.content.text
        for m in messages
    ), f"Custom prompt message missing: {messages}"
