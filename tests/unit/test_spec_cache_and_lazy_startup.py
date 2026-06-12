"""Issue #28: handshake-first startup, clean exit on closed stream, and
live-first spec cache fallback."""
import json
import os
import subprocess
import sys
import time


def test_handshake_answered_before_slow_spec_fetch(tmp_path):
    """initialize must respond while the spec is still downloading."""
    server = subprocess.Popen(
        [sys.executable, "-c", (
            "import http.server, time\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            "        time.sleep(8)\n"
            "        self.send_response(200); self.end_headers()\n"
            "        self.wfile.write(b'{\"openapi\":\"3.0.0\",\"paths\":{}}')\n"
            "    def log_message(self, *a): pass\n"
            "http.server.HTTPServer(('127.0.0.1', 18931), H).serve_forever()\n")],
    )
    try:
        time.sleep(0.5)
        env = dict(os.environ)
        env["OPENAPI_SPEC_URL"] = "http://127.0.0.1:18931/slow.json"
        env["OPENAPI_SPEC_CACHE_TTL_SECONDS"] = "0"
        proc = subprocess.Popen(
            [sys.executable, "-c", "from mcp_openapi_proxy import main; main()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, text=True,
        )
        start = time.time()
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "1"}}}) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        elapsed = time.time() - start
        proc.terminate()
        resp = json.loads(line)
        assert resp["id"] == 1 and "result" in resp
        assert elapsed < 5, f"initialize took {elapsed:.1f}s — blocked on spec fetch"
    finally:
        server.terminate()


def test_clean_exit_when_client_closes_stream():
    """No crash-loop: closing stdin must end the process promptly."""
    env = dict(os.environ)
    env["OPENAPI_SPEC_URL"] = "file:///dev/null"
    proc = subprocess.Popen(
        [sys.executable, "-c", "from mcp_openapi_proxy import main; main()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env, text=True,
    )
    proc.stdin.write(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"}}}) + "\n")
    proc.stdin.flush()
    proc.stdout.readline()
    proc.stdin.close()
    try:
        rc = proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("server kept running after client closed the stream (crash-loop)")
    assert rc is not None


def test_spec_cache_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAPI_SPEC_CACHE_TTL_SECONDS", "3600")
    from mcp_openapi_proxy import utils
    url = "http://unreachable.invalid/spec.json"
    spec = {"openapi": "3.0.0", "paths": {"/x": {}}}
    utils._spec_cache_store(url, spec)
    out = utils.fetch_openapi_spec(url, retries=1)
    assert out == spec, "cached copy should be served when live fetch fails"


def test_spec_cache_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAPI_SPEC_CACHE_TTL_SECONDS", "0")
    from mcp_openapi_proxy import utils
    url = "http://unreachable.invalid/spec.json"
    utils._spec_cache_store(url, {"x": 1})
    assert utils.fetch_openapi_spec(url, retries=1) is None
