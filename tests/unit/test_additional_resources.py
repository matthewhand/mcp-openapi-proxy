"""ADDITIONAL_RESOURCES: user-defined resources served from local files (issue #33).

Runs each scenario in a subprocess so module-level env parsing is exercised
exactly as in production, with zero state leakage into other test files.
"""
import json
import os
import subprocess
import sys

DRIVER = r"""
import asyncio, json, sys
import mcp_openapi_proxy.server_lowlevel as srv
from mcp import types

out = {"names": [r.name for r in srv.resources]}
uri = sys.argv[1] if len(sys.argv) > 1 else None
if uri:
    req = types.ReadResourceRequest(
        method="resources/read",
        params=types.ReadResourceRequestParams(uri=uri),
    )
    result = asyncio.new_event_loop().run_until_complete(srv.read_resource(req))
    out["text"] = result.contents[0].text
    out["mime"] = getattr(result.contents[0], "mimeType", None)
print(json.dumps(out))
"""


def run_driver(env_extra, uri=None):
    env = dict(os.environ)
    env["OPENAPI_SPEC_URL"] = "file:///dev/null"
    env.pop("ADDITIONAL_RESOURCES", None)
    env.update(env_extra)
    cmd = [sys.executable, "-c", DRIVER] + ([uri] if uri else [])
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr[-500:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_additional_resources_listed_and_read(tmp_path):
    policy = tmp_path / "policy.md"
    policy.write_text("# Naming Policy\nUse lowercase hostnames.")
    out = run_driver({"ADDITIONAL_RESOURCES": f"netbox-naming-policy={policy}"},
                     uri="file:///netbox-naming-policy")
    assert "spec_file" in out["names"]
    assert "netbox-naming-policy" in out["names"]
    assert "lowercase hostnames" in out["text"]
    assert out["mime"] == "text/markdown"


def test_additional_resources_missing_file(tmp_path):
    out = run_driver({"ADDITIONAL_RESOURCES": f"ghost={tmp_path}/nope.md"},
                     uri="file:///ghost")
    assert "unavailable" in out["text"]


def test_additional_resources_malformed_entries_ignored():
    out = run_driver({"ADDITIONAL_RESOURCES": "no-equals-sign,=,name="})
    assert out["names"] == ["spec_file"]


def test_no_env_keeps_default_only():
    out = run_driver({"ADDITIONAL_RESOURCES": ""})
    assert out["names"] == ["spec_file"]
