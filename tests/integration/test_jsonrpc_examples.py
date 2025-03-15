import os
import json
import jmespath
import subprocess
import time
import unittest
import signal
import select

class TestJSONRPCExamples(unittest.TestCase):
    def run_server_jsonrpc(self, env):
        # Spawn the mcp-openapi-proxy server using uvx with the provided environment variables.
        # The server communicates via stdio (stdin/stdout) using JSONRPC.
        process = subprocess.Popen(
            ["uvx", "mcp-openapi-proxy"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        # Wait for the server to signal readiness.
        ready_line = process.stdout.readline().strip()
        if ready_line != "READY":
            self.fail(f"Server did not output READY message, got: '{ready_line}'")
        return process

    def send_jsonrpc_request(self, process, request, timeout=10):
        # Send a JSONRPC request to the server via its stdin and return the parsed JSON response.
        import select
        request_str = json.dumps(request) + "\n"
        process.stdin.write(request_str)
        process.stdin.flush()
        rlist, _, _ = select.select([process.stdout], [], [], timeout)
        if not rlist:
            raise TimeoutError("No response from server within timeout period.")
        response_line = process.stdout.readline().strip()
        try:
            return json.loads(response_line)
        except json.JSONDecodeError as e:
            self.fail(f"Failed to decode JSON response: {e}\nResponse was: {response_line}")

    def test_jsonrpc_for_examples(self):
        # Set a global timeout of 60 seconds for the test.
        def timeout_handler(signum, frame):
            raise TimeoutError("Test timed out")
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(60)

        examples = [
            ("glama", "examples/glama-claude_desktop_config.json"),
            ("asana", "examples/claude_desktop_config.json-asana"),
            ("atlassian", "examples/claude_desktop_config.json-atlassian"),
            ("azure", "examples/claude_desktop_config.json-azure"),
            ("brevo", "examples/claude_desktop_config.json-brevo"),
            ("ghost", "examples/claude_desktop_config.json-ghost"),
            ("github", "examples/claude_desktop_config.json-github"),
            ("gitlab", "examples/claude_desktop_config.json-gitlab"),
            ("openai", "examples/claude_desktop_config.json-openai"),
            ("openwebui", "examples/claude_desktop_config.json-openwebui"),
            ("perplexity", "examples/claude_desktop_config.json-perplexity"),
            ("qdrant", "examples/claude_desktop_config.json-qdrant"),
            ("quivr", "examples/claude_desktop_config.json-quivr"),
            ("vectara", "examples/claude_desktop_config.json-vectara"),
            ("flyio", "examples/flyio-claude_desktop_config.json"),
            ("getzep", "examples/getzep-claude_desktop_config.json"),
            ("render", "examples/render-claude_desktop_config.json"),
            ("slack", "examples/slack-claude_desktop_config.json")
        ]
        for name, config_path in examples:
            with self.subTest(example=name):
                if not os.path.exists(config_path):
                    self.skipTest(f"Configuration file {config_path} does not exist")
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                # Use jmespath to extract the spec URL for the given example.
                spec_url = jmespath.search(f"mcpServers.{name}.env.OPENAPI_SPEC_URL", config)
                if not spec_url:
                    spec_url = "https://raw.githubusercontent.com/OAI/OpenAPI-Specification/main/examples/v3.0/petstore.json"
                env = os.environ.copy()
                env["OPENAPI_SPEC_URL"] = spec_url
                # Spawn the mcp-openapi-proxy process.
                process = self.run_server_jsonrpc(env)
                try:
                    # Allow some time for the server to initialize.
                    time.sleep(1)
                    # Prepare a JSONRPC request. For example, a ListToolsRequest.
                    request = {"jsonrpc": "2.0", "method": "list_tools", "params": {}, "id": 1}
                    response = self.send_jsonrpc_request(process, request)
                    self.assertEqual(response.get("jsonrpc"), "2.0", f"Example {name}: Invalid jsonrpc version")
                    self.assertIn("result", response, f"Example {name}: Missing result in response")
                    self.assertIn("tools", response["result"], f"Example {name}: Response does not contain tools")
                    self.assertGreater(len(response["result"]["tools"]), 0, f"Example {name}: No tools returned")
                finally:
                    process.kill()
        # Cancel the alarm after test completes.
        signal.alarm(0)

if __name__ == "__main__":
    unittest.main()