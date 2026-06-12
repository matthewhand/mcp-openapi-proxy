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
                            {"name": "owner", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Owner name"},
                            {"name": "repo", "in": "path", "required": True, "schema": {"type": "string"}, "description": "Repository name"},
                            {"name": "filter", "in": "query", "required": False, "schema": {"type": "string"}, "description": "Filter value"}
                        ],
                        "responses": {
                            "200": {
                                "description": "OK"
                            }
                        }
                    }
                }
            }
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

    def test_array_param_with_items_includes_items(self):
        # Issue #16: array parameters must include their `items` schema so
        # OpenAI tool_use does not reject the generated JSON Schema.
        spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base.com"}],
            "paths": {
                "/pet/findByTags": {
                    "get": {
                        "summary": "Finds Pets by tags.",
                        "operationId": "findPetsByTags",
                        "parameters": [
                            {
                                "name": "tags",
                                "in": "query",
                                "description": "Tags to filter by",
                                "required": True,
                                "explode": True,
                                "schema": {"type": "array", "items": {"type": "string"}}
                            }
                        ],
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        registered_tools = register_functions(spec)
        self.assertEqual(len(registered_tools), 1)
        prop = registered_tools[0].inputSchema["properties"]["tags"]
        self.assertEqual(prop["type"], "array")
        self.assertEqual(prop.get("items"), {"type": "string"})

    def test_array_param_without_items_gets_default_items(self):
        # OpenAI requires `items` for arrays; fall back to string items
        # when the spec omits them.
        spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base.com"}],
            "paths": {
                "/things": {
                    "get": {
                        "summary": "List things",
                        "parameters": [
                            {
                                "name": "ids",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "array"}
                            }
                        ],
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        registered_tools = register_functions(spec)
        self.assertEqual(len(registered_tools), 1)
        prop = registered_tools[0].inputSchema["properties"]["ids"]
        self.assertEqual(prop["type"], "array")
        self.assertEqual(prop.get("items"), {"type": "string"})

    def test_request_body_array_property_includes_items(self):
        # Array properties merged from a requestBody must also carry `items`,
        # including a fallback when the spec omits them.
        spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base.com"}],
            "paths": {
                "/pets": {
                    "post": {
                        "summary": "Create a pet",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "tags": {
                                                "type": "array",
                                                "items": {"type": "string"}
                                            },
                                            "photoUrls": {
                                                "type": "array"
                                            }
                                        },
                                        "required": ["tags"]
                                    }
                                }
                            }
                        },
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        registered_tools = register_functions(spec)
        self.assertEqual(len(registered_tools), 1)
        props = registered_tools[0].inputSchema["properties"]
        self.assertEqual(props["tags"]["type"], "array")
        self.assertEqual(props["tags"].get("items"), {"type": "string"})
        self.assertEqual(props["photoUrls"]["type"], "array")
        self.assertEqual(props["photoUrls"].get("items"), {"type": "string"})

    def test_fastmcp_array_param_includes_items(self):
        # The FastMCP path builds its own inputSchema and must also emit
        # array types with `items` (falling back to string items).
        import json
        import os
        from mcp_openapi_proxy import server_fastmcp
        spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base.com"}],
            "paths": {
                "/pet/findByTags": {
                    "get": {
                        "summary": "Finds Pets by tags.",
                        "operationId": "findPetsByTags",
                        "parameters": [
                            {
                                "name": "tags",
                                "in": "query",
                                "description": "Tags to filter by",
                                "required": True,
                                "schema": {"type": "array", "items": {"type": "string"}}
                            },
                            {
                                "name": "ids",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "array"}
                            }
                        ],
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        original_fetch = server_fastmcp.fetch_openapi_spec
        server_fastmcp.fetch_openapi_spec = lambda url: spec
        os.environ["OPENAPI_SPEC_URL"] = "http://dummy_url_issue16"
        try:
            result = json.loads(server_fastmcp.list_functions(env_key="OPENAPI_SPEC_URL"))
        finally:
            server_fastmcp.fetch_openapi_spec = original_fetch
            os.environ.pop("OPENAPI_SPEC_URL", None)
        tool = next(f for f in result if f.get("path") == "/pet/findByTags")
        tags_prop = tool["inputSchema"]["properties"]["tags"]
        self.assertEqual(tags_prop["type"], "array")
        self.assertEqual(tags_prop.get("items"), {"type": "string"})
        ids_prop = tool["inputSchema"]["properties"]["ids"]
        self.assertEqual(ids_prop["type"], "array")
        self.assertEqual(ids_prop.get("items"), {"type": "string"})

    def test_input_schema_contents(self):
        # Ensure that one tool is registered for the endpoint using the returned tools list directly
        registered_tools = register_functions(self.dummy_spec)
        self.assertEqual(len(registered_tools), 1)
        tool = registered_tools[0]
        input_schema = tool.inputSchema

        expected_properties = {
            "owner": {"type": "string", "description": "Owner name"},
            "repo": {"type": "string", "description": "Repository name"},
            "filter": {"type": "string", "description": "Filter value"}
        }

        self.assertEqual(input_schema["type"], "object")
        self.assertFalse(input_schema.get("additionalProperties", True))
        self.assertEqual(input_schema["properties"], expected_properties)
        # Only "owner" and "repo" are required
        self.assertCountEqual(input_schema["required"], ["owner", "repo"])

if __name__ == "__main__":
    unittest.main()