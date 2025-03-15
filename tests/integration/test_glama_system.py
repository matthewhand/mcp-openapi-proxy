import os
import json
import jmespath
import requests
import unittest
from mcp_openapi_proxy.server_lowlevel import register_functions, tools

class TestGlamaSystem(unittest.TestCase):
    def setUp(self):
        # Clear any existing tool registrations
        tools.clear()
        # Load glama example configuration
        config_path = "examples/glama-claude_desktop_config.json"
        if not os.path.exists(config_path):
            self.fail(f"Configuration file {config_path} does not exist")
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        self.spec_url = jmespath.search("mcpServers.glama.env.OPENAPI_SPEC_URL", self.config)
        if not self.spec_url:
            self.fail("spec_url is not defined in the configuration file.")
            
    def test_glama_spec_loading(self):
        # Fetch the OpenAPI spec from the URL. Fail test if it cannot be fetched.
        response = requests.get(self.spec_url, timeout=10)
        response.raise_for_status()
        spec = response.json()
        # Register functions using the spec
        registered = register_functions(spec)
        # Assert that at least one function is registered
        self.assertGreater(len(registered), 0, "No functions registered from glama spec")

if __name__ == "__main__":
    unittest.main()