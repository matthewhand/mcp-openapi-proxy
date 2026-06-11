# -*- coding: utf-8 -*-
"""Regression tests for MCP discovery: list_tools/list_resources/list_prompts,
get_prompt, and capability advertisement.

These guard the bugs that broke strict MCP clients (e.g. Gemini): a bare
non-serializable object returned from list_resources, an invalid get_prompt
message shape, and capabilities advertised as empty so clients saw "no tools".
"""
from types import SimpleNamespace

import pytest

import mcp_openapi_proxy.server_lowlevel as s
from mcp_openapi_proxy.server_lowlevel import (
    list_tools,
    list_resources,
    list_prompts,
    get_prompt,
    build_capabilities,
    types,
)


@pytest.mark.asyncio
async def test_list_tools_returns_valid_result():
    result = await list_tools(SimpleNamespace(params=SimpleNamespace()))
    assert isinstance(result, types.ListToolsResult)
    assert isinstance(result.tools, list)


@pytest.mark.asyncio
async def test_list_resources_returns_serializable_result():
    """Regression: used to return a bare ResourcesHolder() that cannot be
    serialized over MCP, aborting client discovery."""
    result = await list_resources(SimpleNamespace(params=SimpleNamespace()))
    assert isinstance(result, types.ListResourcesResult)
    assert len(result.resources) >= 1
    assert all(isinstance(r, types.Resource) for r in result.resources)
    # Must round-trip through pydantic serialization (what the MCP transport does).
    result.model_dump_json()


@pytest.mark.asyncio
async def test_list_prompts_returns_valid_result():
    result = await list_prompts(SimpleNamespace(params=SimpleNamespace()))
    assert isinstance(result, types.ListPromptsResult)
    result.model_dump_json()


@pytest.mark.asyncio
async def test_get_prompt_unknown_builds_valid_message():
    """Regression: error path used role='system' + a dict content, both invalid
    for types.PromptMessage."""
    req = SimpleNamespace(params=SimpleNamespace(name="does-not-exist", arguments={}))
    result = await get_prompt(req)
    assert isinstance(result, types.GetPromptResult)
    msg = result.messages[0]
    assert msg.role in ("assistant", "user")
    assert isinstance(msg.content, types.TextContent)
    result.model_dump_json()


@pytest.mark.asyncio
async def test_get_prompt_known_template():
    s.PROMPT_TEMPLATES["unit_test_prompt"] = lambda args: [
        types.PromptMessage(
            role="assistant",
            content=types.TextContent(type="text", text="hello"),
        )
    ]
    try:
        req = SimpleNamespace(params=SimpleNamespace(name="unit_test_prompt", arguments={}))
        result = await get_prompt(req)
        assert isinstance(result, types.GetPromptResult)
        assert result.messages[0].content.text == "hello"
        result.model_dump_json()
    finally:
        s.PROMPT_TEMPLATES.pop("unit_test_prompt", None)


def test_capabilities_advertise_tools_by_default():
    """Regression: capabilities were gated on CAPABILITIES_* (default false), so a
    server WITH tools advertised an empty capability set and strict clients saw none."""
    caps = build_capabilities()
    assert caps.tools is not None, "tools must be advertised when ENABLE_TOOLS (default on)"
    # serializes cleanly
    caps.model_dump_json()
