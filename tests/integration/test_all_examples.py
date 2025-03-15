import os
import json
import jmespath
import requests
import unittest
from mcp_openapi_proxy.server_lowlevel import register_functions, tools

class TestAllExamples(unittest.TestCase):
    def test_example_specs(self):
        examples = [
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
        for name, path in examples:
            with self.subTest(example=name):
                if not os.path.exists(path):
                    self.skipTest(f"Configuration file {path} does not exist")
                with open(path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                # Extract the OPENAPI spec URL using jmespath:
                spec_url = jmespath.search(f"mcpServers.{name}.env.OPENAPI_SPEC_URL", config)
                if not spec_url:
                    self.skipTest(f"spec_url not defined for example {name} in configuration file {path}")
                try:
                    response = requests.get(spec_url, timeout=10)
                    response.raise_for_status()
                except Exception as e:
                    self.skipTest(f"Could not fetch spec from URL {spec_url} for example {name}: {e}")
                try:
                    spec = response.json()
                except ValueError as e:
                    self.skipTest(f"Response from URL {spec_url} is not valid JSON for example {name}: {e}")
                # Clear any previously registered tools
                tools.clear()
                registered = register_functions(spec)
                self.assertGreater(len(registered), 0, f"No functions registered from spec for example {name}")

if __name__ == "__main__":
    unittest.main()