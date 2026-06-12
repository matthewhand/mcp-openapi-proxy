# -*- coding: utf-8 -*-
"""End-to-end MCP discovery handshake over stdio.

Simulates what a strict MCP client (Gemini, Codex, Qwen, etc.) does on connect:
  initialize -> notifications/initialized -> tools/list -> resources/list -> prompts/list

This is the harness that catches client-compatibility regressions: empty
capability advertisement, non-serializable list_resources results, and broken
prompt shapes all surface here as a failed handshake rather than a silent
"no tools found" in the client.
"""
import json
import os
import select
import subprocess
import sys

import pytest

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "discovery-test", "version": "1.0.0"},
    "servers": [{"url": "http://localhost"}],
    "paths": {
        "/ping": {
            "get": {
                "summary": "Ping",
                "operationId": "ping",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


class StdioClient:
    def __init__(self, proc):
        self.proc = proc
        self._buf = ""
        self._id = 0

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method, params=None, timeout=20.0):
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        return self._read_response(rid, timeout)

    def _read_response(self, rid, timeout):
        import time
        deadline = time.monotonic() + timeout
        while True:
            nl = self._buf.find("\n")
            if nl >= 0:
                line = self._buf[:nl]
                self._buf = self._buf[nl + 1:]
                line = line.strip()
                if line.startswith("{"):
                    msg = json.loads(line)
                    if msg.get("id") == rid:
                        return msg
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no response to id={rid} within {timeout}s")
            r, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not r:
                continue
            chunk = os.read(self.proc.stdout.fileno(), 4096).decode("utf-8", "replace")
            if not chunk:
                raise RuntimeError("server closed stdout before responding")
            self._buf += chunk


@pytest.fixture
def server(tmp_path):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SPEC))
    env = dict(os.environ)
    env.update({
        "OPENAPI_SPEC_URL": spec_path.as_uri(),
        "ENABLE_RESOURCES": "true",
        "ENABLE_PROMPTS": "true",
        "DEBUG": "false",
    })
    proc = subprocess.Popen(
        [sys.executable, "-c", "from mcp_openapi_proxy import main; main()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, text=True,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


@pytest.fixture
def simple_server(tmp_path):
    """FastMCP (simple) mode permutation."""
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SPEC))
    env = dict(os.environ)
    env.update({
        "OPENAPI_SPEC_URL": spec_path.as_uri(),
        "OPENAPI_SIMPLE_MODE": "true",
        "DEBUG": "false",
    })
    proc = subprocess.Popen(
        [sys.executable, "-c", "from mcp_openapi_proxy import main; main()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, text=True,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def _initialize(client):
    resp = client.request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "discovery-test", "version": "0"},
    })
    assert "result" in resp, f"initialize failed: {resp}"
    client.notify("notifications/initialized")
    return resp["result"]


def test_initialize_advertises_all_capabilities(server):
    client = StdioClient(server)
    result = _initialize(client)
    caps = result.get("capabilities", {})
    assert caps.get("tools") is not None, f"tools capability not advertised: {caps}"
    assert caps.get("resources") is not None, f"resources capability not advertised: {caps}"
    assert caps.get("prompts") is not None, f"prompts capability not advertised: {caps}"


def test_full_discovery_handshake(server):
    client = StdioClient(server)
    _initialize(client)

    tools = client.request("tools/list")
    assert "result" in tools, f"tools/list errored: {tools}"
    names = [t["name"] for t in tools["result"]["tools"]]
    assert names, "no tools returned"

    # The bug that broke Gemini: list_resources returned a non-serializable object.
    resources = client.request("resources/list")
    assert "result" in resources, f"resources/list errored: {resources}"
    assert isinstance(resources["result"]["resources"], list)

    prompts = client.request("prompts/list")
    assert "result" in prompts, f"prompts/list errored: {prompts}"
    prompt_names = [p["name"] for p in prompts["result"]["prompts"]]
    assert "summarize_spec" in prompt_names, f"expected summarize_spec, got {prompt_names}"


def test_get_prompt_returns_valid_messages(server):
    client = StdioClient(server)
    _initialize(client)
    resp = client.request("prompts/get", {"name": "summarize_spec", "arguments": {}})
    assert "result" in resp, f"prompts/get errored: {resp}"
    messages = resp["result"]["messages"]
    assert messages and messages[0]["role"] in ("assistant", "user")
    assert messages[0]["content"]["type"] == "text"


def test_simple_mode_tools_discoverable(simple_server):
    """FastMCP (simple) mode permutation: a strict client can still initialize
    and discover the static tools."""
    client = StdioClient(simple_server)
    result = _initialize(client)
    assert result.get("capabilities", {}).get("tools") is not None
    tools = client.request("tools/list")
    assert "result" in tools, f"tools/list errored: {tools}"
    names = [t["name"] for t in tools["result"]["tools"]]
    assert "list_functions" in names and "call_function" in names, names
