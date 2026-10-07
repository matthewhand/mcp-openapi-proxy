"""PROMPT env JSON parsing, plus server registration when the MCP SDK imports."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from mcp_openapi_proxy.prompt_env import BUILTIN_PROMPT_NAMES, parse_prompt_env


def test_parse_prompt_env_unset(monkeypatch):
    monkeypatch.delenv("PROMPT", raising=False)
    assert parse_prompt_env() is None
    assert parse_prompt_env("   ") is None


def test_parse_prompt_env_messages(monkeypatch):
    monkeypatch.delenv("PROMPT", raising=False)
    raw = json.dumps(
        {
            "name": "asana_prompt",
            "description": "A test prompt for Asana integration.",
            "messages": [
                {
                    "user": "What is Asana?",
                    "assistant": "Asana is a work management platform.",
                }
            ],
        }
    )
    parsed = parse_prompt_env(raw)
    assert parsed["name"] == "asana_prompt"
    assert parsed["description"] == "A test prompt for Asana integration."
    assert parsed["messages"] == [
        {"role": "user", "text": "What is Asana?"},
        {"role": "assistant", "text": "Asana is a work management platform."},
    ]
    assert "asana_prompt" not in BUILTIN_PROMPT_NAMES


def test_parse_prompt_env_defaults_and_skips_bad_entries():
    parsed = parse_prompt_env(json.dumps({"messages": ["nope", {"assistant": "only assistant"}]}))
    assert parsed["name"] == "custom_prompt"
    assert parsed["description"] == "Custom prompt from PROMPT envvar"
    assert parsed["messages"] == [{"role": "assistant", "text": "only assistant"}]


def test_parse_prompt_env_invalid_json():
    assert parse_prompt_env("{") is None
    assert parse_prompt_env(json.dumps(["not", "an", "object"])) is None
    assert parse_prompt_env(json.dumps({"messages": {"user": "x"}})) is None


def test_builtin_names_are_reserved():
    assert "summarize_spec" in BUILTIN_PROMPT_NAMES
    assert "whimsical_blog" in BUILTIN_PROMPT_NAMES


def _import_lowlevel():
    try:
        from mcp_openapi_proxy import server_lowlevel as lowlevel
    except ImportError as exc:
        pytest.skip(f"low-level server not importable in this environment: {exc}")
    return lowlevel


def test_lowlevel_registers_env_prompt(monkeypatch):
    lowlevel = _import_lowlevel()
    monkeypatch.setenv("ENABLE_PROMPTS", "true")
    raw = json.dumps(
        {
            "name": "unit_env_prompt",
            "description": "unit",
            "messages": [{"user": "What is Asana?", "assistant": "Asana is a work management platform."}],
        }
    )
    lowlevel.register_env_prompt(raw)
    try:
        listed = asyncio.run(lowlevel.list_prompts(SimpleNamespace(params=SimpleNamespace())))
        assert any(p.name == "unit_env_prompt" for p in listed.prompts)
        got = asyncio.run(
            lowlevel.get_prompt(
                SimpleNamespace(params=SimpleNamespace(name="unit_env_prompt", arguments={}))
            )
        )
        assert any(
            m.role == "assistant" and "Asana is a work management platform." in m.content.text
            for m in got.messages
        )
        before = [p.name for p in lowlevel.prompts]
        lowlevel.register_env_prompt(json.dumps({"name": "summarize_spec", "messages": []}))
        assert [p.name for p in lowlevel.prompts] == before
        assert "blueprint" in asyncio.run(
            lowlevel.get_prompt(
                SimpleNamespace(params=SimpleNamespace(name="summarize_spec", arguments={}))
            )
        ).messages[0].content.text
    finally:
        lowlevel.prompts[:] = [p for p in lowlevel.prompts if p.name != "unit_env_prompt"]
        lowlevel.PROMPT_TEMPLATES.pop("unit_env_prompt", None)


def test_lowlevel_skips_prompt_when_disabled(monkeypatch):
    lowlevel = _import_lowlevel()
    monkeypatch.setenv("ENABLE_PROMPTS", "false")
    raw = json.dumps({"name": "disabled_env_prompt", "messages": [{"assistant": "nope"}]})
    lowlevel.register_env_prompt(raw)
    assert all(p.name != "disabled_env_prompt" for p in lowlevel.prompts)
    assert "disabled_env_prompt" not in lowlevel.PROMPT_TEMPLATES
