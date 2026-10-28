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



def test_custom_prompt_names_not_exposed_in_debug_logs(monkeypatch, caplog):
    """Both registration paths must not echo configured names into log sinks."""
    import logging
    from mcp_openapi_proxy import server_fastmcp as fast
    from mcp_openapi_proxy import server_lowlevel as low

    sentinel = "SYNTHETIC_PRIVATE_PROMPT_NAME_NOT_REAL"
    raw = json.dumps({
        "name": sentinel + "\nFORGED_LOG_ENTRY",
        "description": "Fictional example",
        "messages": [{"user": "Fictional question"}],
    })
    monkeypatch.setenv("ENABLE_PROMPTS", "true")
    recorded = []
    def fake_decorator(*, name, description):
        recorded.append((name, description))
        return lambda callback: callback
    monkeypatch.setattr(fast.mcp, "prompt", fake_decorator)
    previous_prompts = list(low.prompts)
    previous_templates = dict(low.PROMPT_TEMPLATES)
    try:
        with caplog.at_level(logging.DEBUG, logger="mcp_openapi_proxy"):
            low.register_env_prompt(raw)
            fast.register_fastmcp_env_prompt(raw)
        assert recorded[0][0].startswith(sentinel)
        assert sentinel in [item.name for item in low.prompts if item.name.startswith(sentinel)][0]
        assert sentinel not in caplog.text
        assert "FORGED_LOG_ENTRY" not in caplog.text
    finally:
        low.prompts[:] = previous_prompts
        low.PROMPT_TEMPLATES.clear()
        low.PROMPT_TEMPLATES.update(previous_templates)


def test_invalid_json_and_reserved_names_never_echo_raw_prompt_values(
        monkeypatch, caplog):
    import logging
    from mcp_openapi_proxy import server_fastmcp as fast
    from mcp_openapi_proxy import server_lowlevel as low
    marker = "SYNTHETIC_CONFIG_MARKER_NOT_REAL"
    monkeypatch.setenv("ENABLE_PROMPTS", "true")
    with caplog.at_level(logging.DEBUG, logger="mcp_openapi_proxy"):
        assert parse_prompt_env("{" + marker) is None
        low.register_env_prompt(json.dumps({"name": "summarize_spec", "messages": []}))
        fast.register_fastmcp_env_prompt(json.dumps({"name": "whimsical_blog", "messages": []}))
    assert marker not in caplog.text
    assert "Failed to parse PROMPT as JSON:" not in caplog.text



def test_prompt_lookup_does_not_log_custom_name(monkeypatch, caplog):
    """Prompt discovery must not echo user-configured names into DEBUG/errors."""
    import logging
    from mcp_openapi_proxy import server_lowlevel as low
    sentinel = "SYNTHETIC_CUSTOM_PROMPT_LOOKUP_SECRET_NOT_REAL"
    monkeypatch.setenv("ENABLE_PROMPTS", "true")
    before_prompts = list(low.prompts)
    before_templates = dict(low.PROMPT_TEMPLATES)
    try:
        low.register_env_prompt(json.dumps({
            "name": sentinel, "messages": [{"user": "SYNTHETIC_PROMPT_BODY_SENTINEL_NOT_REAL"}]
        }))
        with caplog.at_level(logging.DEBUG, logger="mcp_openapi_proxy"):
            result = asyncio.run(low.get_prompt(
                SimpleNamespace(params=SimpleNamespace(name=sentinel, arguments={}))
            ))
            assert result.messages
            missing = asyncio.run(low.get_prompt(
                SimpleNamespace(params=SimpleNamespace(
                    name=sentinel + "_missing", arguments={}
                ))
            ))
        assert missing.description == "Prompt not found"
        assert sentinel not in caplog.text
        assert "SYNTHETIC_PROMPT_BODY_SENTINEL_NOT_REAL" not in caplog.text
    finally:
        low.prompts[:] = before_prompts
        low.PROMPT_TEMPLATES.clear()
        low.PROMPT_TEMPLATES.update(before_templates)
