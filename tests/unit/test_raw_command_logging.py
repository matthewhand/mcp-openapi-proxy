# -*- coding: utf-8 -*-
"""Opt-in verbatim shell-command audit logging (MCP_LOG_RAW_COMMANDS).

Off by default: the only MCP log record is the existing
``mcp rpc method=... name=...`` line, and tool arguments never appear.
On, and only for allow-listed shell-execution tools, one extra record is
emitted immediately before execution::

    mcp raw-command tool=post_command_execute_shell
    <verbatim command>

The command is logged byte-for-byte -- no stripping, no newline folding, no
redaction -- so whitespace, quoting and blank lines survive.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
import requests

from mcp_openapi_proxy.protocol import (
    DEFAULT_RAW_COMMAND_TOOLS,
    extract_raw_command,
    format_raw_command_log_line,
    log_raw_command,
    raw_command_logging_enabled,
    raw_command_tools,
)

TOOL = "post_command_execute_shell"
MULTILINE = "set -euo pipefail\ncd /srv/app\n\n  ls -la\t'quoted arg'\necho done"
SECRET_COMMAND = "curl -sS -H 'Authorization: Bearer SUPERSECRET' https://api.example.test/v1"

TERMINAL_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "gpt-terminal-plus API", "version": "1.0.0"},
    "servers": [{"url": "http://terminal.example.test"}],
    "paths": {
        "/command/execute-shell": {
            "post": {
                "summary": "Execute a command using configured shell (generic)",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"command": {"type": "string"}},
                                "required": ["command"],
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Execution complete"}},
            }
        },
        "/file/read": {
            "post": {
                "summary": "Read a file",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"path": {"type": "string"}},
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("MCP_LOG_RAW_COMMANDS", raising=False)
    monkeypatch.delenv("MCP_LOG_RAW_COMMAND_TOOLS", raising=False)


def _raw_records(caplog):
    return [r.message for r in caplog.records if r.message.startswith("mcp raw-command")]


# --- default is off ----------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off"])
def test_default_off_does_not_log_command(caplog, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", value)
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")

    assert raw_command_logging_enabled() is False
    assert log_raw_command(TOOL, {"command": SECRET_COMMAND}) is None

    blob = "\n".join(r.message for r in caplog.records)
    assert _raw_records(caplog) == []
    assert "SUPERSECRET" not in blob
    assert SECRET_COMMAND not in blob


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
def test_opt_in_switch_truthiness(monkeypatch, value):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", value)
    assert raw_command_logging_enabled() is True


def test_opt_in_logs_exact_command_string(caplog, monkeypatch):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", "1")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")

    line = log_raw_command(TOOL, {"command": "ls -la", "shell": "/bin/bash"})

    assert line == f"mcp raw-command tool={TOOL}\nls -la"
    assert _raw_records(caplog) == [f"mcp raw-command tool={TOOL}\nls -la"]


def test_opt_in_logs_multiline_command_verbatim(caplog, monkeypatch):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", "1")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")

    line = log_raw_command(TOOL, {"command": MULTILINE})

    assert line is not None
    header, _, payload = line.partition("\n")
    assert header == f"mcp raw-command tool={TOOL}"
    assert payload == MULTILINE
    # Newlines, tabs, blank lines and quotes all survive untouched (the only
    # added newline is the one separating the marker header from the command).
    assert line.count("\n") == MULTILINE.count("\n") + 1
    assert "\t" in line
    assert "\n\n  ls -la" in line
    assert "'quoted arg'" in line


def test_opt_in_does_not_mutate_or_normalize_command(caplog, monkeypatch):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", "1")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")
    padded = "  \n echo  'a'   \"b\"  \t\n "

    line = log_raw_command(TOOL, {"command": padded})

    assert line == f"mcp raw-command tool={TOOL}\n{padded}"


# --- scoping: shell/command execution tools only -----------------------------


@pytest.mark.parametrize("tool", ["post_file_read", "post_issue_list", "ping", "tools/list"])
def test_unrelated_tools_never_get_raw_dump(caplog, monkeypatch, tool):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", "1")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")

    assert log_raw_command(tool, {"command": SECRET_COMMAND, "path": "/etc/shadow"}) is None
    blob = "\n".join(r.message for r in caplog.records)
    assert _raw_records(caplog) == []
    assert "SUPERSECRET" not in blob
    assert "/etc/shadow" not in blob


def test_default_allowlist_is_narrow():
    assert TOOL in DEFAULT_RAW_COMMAND_TOOLS
    assert "post_file_read" not in DEFAULT_RAW_COMMAND_TOOLS
    assert set(DEFAULT_RAW_COMMAND_TOOLS) == raw_command_tools()


def test_allowlist_override_adds_tool(caplog, monkeypatch):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", "1")
    monkeypatch.setenv("MCP_LOG_RAW_COMMAND_TOOLS", "post_run,my_shell_exec")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")

    assert log_raw_command("post_run", {"args": ["issue", "list"]}) is None
    assert log_raw_command("my_shell_exec", {"cmd": "whoami"}) == (
        "mcp raw-command tool=my_shell_exec\nwhoami"
    )
    assert log_raw_command(TOOL, {"command": "ls"}) is None


def test_allowlist_rejects_log_injection_entries(monkeypatch):
    monkeypatch.setenv("MCP_LOG_RAW_COMMAND_TOOLS", "ok_tool,evil\nmcp raw-command tool=x")
    assert raw_command_tools() == frozenset({"ok_tool"})


# --- malformed / absent arguments must not raise ------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        None,
        {},
        {"shell": "/bin/bash"},
        {"command": None},
        {"command": ["ls", "-la"]},
        {"command": 42},
        {"command": {"nested": "ls"}},
        "ls -la",
        ["ls"],
        object(),
    ],
)
def test_malformed_arguments_do_not_crash(caplog, monkeypatch, arguments):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", "1")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")

    assert log_raw_command(TOOL, arguments) is None
    assert _raw_records(caplog) == []


def test_format_rejects_unsafe_tool_names():
    assert extract_raw_command({"command": "ls"}) == "ls"
    assert format_raw_command_log_line(None, "ls") is None
    assert format_raw_command_log_line("bad\nname", "ls") is None
    assert format_raw_command_log_line(TOOL, None) is None
    assert format_raw_command_log_line(TOOL, 7) is None


# --- dispatcher wiring: record lands before execution ------------------------


@pytest.fixture
def terminal_tools(monkeypatch):
    import mcp_openapi_proxy.server_lowlevel as sl
    from mcp_openapi_proxy.openapi import register_functions

    monkeypatch.setenv("TOOL_WHITELIST", "")
    monkeypatch.setenv("OPENAPI_SPEC_URL", "")
    sl.tools.clear()
    sl.resources.clear()
    sl.prompts.clear()
    sl.openapi_spec_data = None
    sl._spec_load_error = None
    sl._spec_load_lock = None
    register_functions(TERMINAL_SPEC)
    sl.openapi_spec_data = TERMINAL_SPEC
    names = {t.name for t in sl.tools}
    assert TOOL in names, names
    yield sl
    sl.tools.clear()
    sl.openapi_spec_data = None


def _call(lowlevel, name, arguments, captured):
    class DummyResponse:
        text = '{"ok": true}'

        def raise_for_status(self):
            return None

    def dummy_request(method, url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return DummyResponse()

    original = requests.request
    requests.request = dummy_request
    try:
        return asyncio.run(
            lowlevel.dispatcher_handler(
                SimpleNamespace(params=SimpleNamespace(name=name, arguments=arguments))
            )
        )
    finally:
        requests.request = original


def test_dispatcher_logs_command_before_upstream_request(terminal_tools, caplog, monkeypatch):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", "1")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")
    captured: dict = {}

    _call(terminal_tools, TOOL, {"command": MULTILINE}, captured)

    assert captured, "expected the upstream request to have been made"
    records = [r.message for r in caplog.records if r.message.startswith("mcp raw-command")]
    assert records == [f"mcp raw-command tool={TOOL}\n{MULTILINE}"]
    assert captured["json"]["command"] == MULTILINE


def test_dispatcher_default_mode_leaves_no_trace(terminal_tools, caplog):
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")
    captured: dict = {}

    _call(terminal_tools, TOOL, {"command": SECRET_COMMAND}, captured)

    blob = "\n".join(r.message for r in caplog.records)
    assert "mcp raw-command" not in blob
    assert "SUPERSECRET" not in blob
    assert SECRET_COMMAND not in blob


def test_dispatcher_opt_in_ignores_non_shell_tool(terminal_tools, caplog, monkeypatch):
    monkeypatch.setenv("MCP_LOG_RAW_COMMANDS", "1")
    caplog.set_level(logging.INFO, logger="mcp_openapi_proxy")
    captured: dict = {}

    _call(terminal_tools, "post_file_read", {"path": "/etc/shadow"}, captured)

    blob = "\n".join(r.message for r in caplog.records)
    assert "mcp raw-command" not in blob
    assert "/etc/shadow" not in blob
