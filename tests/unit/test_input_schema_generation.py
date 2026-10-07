import unittest
from mcp_openapi_proxy.openapi import register_functions
from mcp_openapi_proxy.server_lowlevel import tools
from mcp_openapi_proxy.utils import normalize_tool_name


class TestInputSchemaGeneration(unittest.TestCase):
    def setUp(self):
        # Stash any existing TOOL_WHITELIST and set it to empty to allow all endpoints
        import os
        import mcp_openapi_proxy.utils as utils

        self.old_tool_whitelist = os.environ.pop("TOOL_WHITELIST", None)
        tools.clear()
        # Patch is_tool_whitelisted to always return True to bypass whitelist filtering in tests
        self.old_is_tool_whitelisted = utils.is_tool_whitelisted
        utils.is_tool_whitelisted = lambda endpoint: True
        self.dummy_spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base.com"}],
            "paths": {
                "/repos/{owner}/{repo}/contents/": {
                    "get": {
                        "summary": "Get repo contents",
                        "parameters": [
                            {
                                "name": "owner",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                                "description": "Owner name",
                            },
                            {
                                "name": "repo",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                                "description": "Repository name",
                            },
                            {
                                "name": "filter",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "string"},
                                "description": "Filter value",
                            },
                        ],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        register_functions(self.dummy_spec)

    def tearDown(self):
        import os
        import mcp_openapi_proxy.utils as utils

        # Restore TOOL_WHITELIST
        if self.old_tool_whitelist is not None:
            os.environ["TOOL_WHITELIST"] = self.old_tool_whitelist
        else:
            os.environ.pop("TOOL_WHITELIST", None)
        # Restore is_tool_whitelisted
        utils.is_tool_whitelisted = self.old_is_tool_whitelisted

    def test_input_schema_contents(self):
        # Ensure that one tool is registered for the endpoint using the returned tools list directly
        registered_tools = register_functions(self.dummy_spec)
        self.assertEqual(len(registered_tools), 1)
        tool = registered_tools[0]
        input_schema = tool.inputSchema

        expected_properties = {
            "owner": {"type": "string", "description": "Owner name"},
            "repo": {"type": "string", "description": "Repository name"},
            "filter": {"type": "string", "description": "Filter value"},
        }

        self.assertEqual(input_schema["type"], "object")
        self.assertFalse(input_schema.get("additionalProperties", True))
        self.assertEqual(input_schema["properties"], expected_properties)
        # Only "owner" and "repo" are required
        self.assertCountEqual(input_schema["required"], ["owner", "repo"])


if __name__ == "__main__":
    unittest.main()
