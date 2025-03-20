import os
import json
import jmespath
import subprocess
import time
import unittest
import signal
import select

print("Loading test module...")

class TestJSONRPCExamples(unittest.TestCase):
    print("Initializing TestJSONRPCExamples class...")

    def run_server_jsonrpc(self, env):
        print(f"Starting server with OPENAPI_SPEC_URL={env.get('OPENAPI_SPEC_URL')}")
        process = subprocess.Popen(
            ["uv", "run", "mcp_openapi_proxy/server_lowlevel.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        print(f"Waiting 2 seconds for server to initialize, PID={process.pid}")
        time.sleep(2)
        if process.poll() is not None:
            stderr_out = process.stderr.read()
            print(f"Server terminated early, return code={process.returncode}, stderr={stderr_out}")
            raise RuntimeError(f"Server failed to start, return code {process.returncode}: {stderr_out}")
        print("Server is running, waiting for READY signal...")
        start_time = time.time()
        timeout = 10
        while time.time() - start_time < timeout:
            print(f"Elapsed time: {time.time() - start_time:.2f} seconds")
            rlist, _, _ = select.select([process.stdout], [], [], 0.1)
            if rlist:
                line = process.stdout.readline().strip()
                print(f"Received output: '{line}'")
                if "READY" in line:
                    print("Server signaled READY, proceeding.")
                    return process
            else:
                print("No output received yet, continuing to wait...")
            time.sleep(0.1)
        stderr_out = process.stderr.read()
        print(f"Timeout after {timeout} seconds, stderr={stderr_out}")
        process.kill()
        raise RuntimeError(f"Server failed to signal READY after {timeout} seconds, stderr: {stderr_out}")

    def send_jsonrpc_request(self, process, request, timeout=10):
        print(f"Sending JSONRPC request: {json.dumps(request)}")
        request_str = json.dumps(request) + "\n"
        process.stdin.write(request_str)
        process.stdin.flush()
        start_time = time.time()
        while time.time() - start_time < timeout:
            if process.stdout.closed:
                print("Stdout closed, aborting wait.")
                break
            rlist, _, _ = select.select([process.stdout], [], [], timeout)
            if not rlist:
                print("No response within timeout, giving up.")
                break
            line = process.stdout.readline().strip()
            print(f"Received response: '{line}'")
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                print("Response not valid JSON, skipping...")
                continue
        raise TimeoutError("No valid JSON response from server within timeout period.")

    def test_jsonrpc_for_examples(self):
        print("Starting test_jsonrpc_for_examples...")
        def timeout_handler(signum, frame):
            raise TimeoutError("Test timed out")
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(60)

        examples = [
            ("glama", "examples/glama-claude_desktop_config.json"),
            ("flyio", "examples/flyio-claude_desktop_config.json"),
            ("getzep", "examples/getzep-claude_desktop_config.json"),
            ("render", "examples/render-claude_desktop_config.json"),
            ("slack", "examples/slack-claude_desktop_config.json")
        ]
        for name, config_path in examples:
            print(f"Running subtest for {name}...")
            with self.subTest(example=name):
                if not os.path.exists(config_path):
                    self.skipTest(f"Configuration file {config_path} does not exist")
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                spec_url = jmespath.search(f"mcpServers.{name}.env.OPENAPI_SPEC_URL", config)
                if not spec_url:
                    spec_url = "https://raw.githubusercontent.com/OAI/OpenAPI-Specification/main/examples/v3.0/petstore.json"
                env = os.environ.copy()
                env["OPENAPI_SPEC_URL"] = spec_url
                process = self.run_server_jsonrpc(env)
                try:
                    time.sleep(1)
                    init_cmd = {"method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "claude-ai", "version": "0.1.0"}}, "jsonrpc": "2.0", "id": 0}
                    init_response = self.send_jsonrpc_request(process, init_cmd)
                    self.assertIsInstance(init_response, dict, f"Example {name}: Initialization response is not valid JSON")
                    # Rest of yer tests...
                finally:
                    process.kill()
        signal.alarm(0)

if __name__ == "__main__":
    print("Running unittest.main()...")
    unittest.main()
