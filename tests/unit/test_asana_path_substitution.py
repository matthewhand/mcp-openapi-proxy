# -*- coding: utf-8 -*-
import unittest
import os
import json
import requests
import asyncio
from types import SimpleNamespace
import mcp_openapi_proxy.server_lowlevel as lowlevel
import mcp_openapi_proxy.utils as utils
from mcp_openapi_proxy.server_lowlevel import dispatcher_handler

class TestAsanaPathSubstitution(unittest.TestCase):
    def setUp(self):
        lowlevel.tools.clear()
        if "TOOL_WHITELIST" in os.environ:
            self.old_tool_whitelisted = os.environ["TOOL_WHITELIST"]
        else:
            self.old_tool_whitelisted = None
        os.environ["TOOL_WHITELIST"] = ""
        self.old_is_tool_whitelisted = utils.is_tool_whitelisted
        utils.is_tool_whitelisted = lambda endpoint: True
        self.dummy_spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://app.asana.com/api/1.0"}],
            "paths": {
                "/workspaces/{workspace_gid}/custom_fields": {
                    "get": {
                        "operationId": "get_workspaces_custom_fields",
                        "summary": "Get workspaces custom fields",
                        "parameters": [
                            {
                                "name": "workspace_gid",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                                "description": "Workspace GID"
                            },
                            {
                                "name": "opt_fields",
                                "in": "query",
                                "required": False,
                                "schema": {"type": "string"},
                                "description": "Optional fields"
                            }
                        ],
                        "responses": {
                            "200": {"description": "OK"}
                        }
                    }
                }
            }
        }
        lowlevel.register_functions(self.dummy_spec)
        self.assertEqual(len(lowlevel.tools), 1, "Expected 1 tool to be registered")

    def tearDown(self):
        utils.is_tool_whitelisted = self.old_is_tool_whitelisted
        if self.old_tool_whitelisted is not None:
            os.environ["TOOL_WHITELIST"] = self.old_tool_whitelisted
        else:
            os.environ.pop("TOOL_WHITELIST", None)
        lowlevel.tools.clear()

    def test_workspace_gid_in_input_schema(self):
        asana_tool = next(
            (t for t in lowlevel.tools if t.name == "get_workspaces_custom_fields"),
            None
        )
        self.assertIsNotNone(asana_tool, "Asana function not registered (didn't find 'get_workspaces_custom_fields')")
        input_schema = asana_tool.inputSchema
        self.assertIn(
            "workspace_gid",
            input_schema["properties"],
            "Input schema should contain 'workspace_gid' parameter"
        )
        self.assertIn(
            "workspace_gid",
            input_schema["required"],
            "'workspace_gid' should be a required parameter"
        )

    def test_workspace_gid_substitution(self):
        asana_tool = next(
            (t for t in lowlevel.tools if "workspaces" in t.name),
            None
        )
        self.assertIsNotNone(asana_tool, "Asana function not registered")
        dummy_request = SimpleNamespace(
            params=SimpleNamespace(
                name=asana_tool.name,
                arguments={"workspace_gid": "12345", "opt_fields": "id,name"}
            )
        )
        original_request = requests.request
        captured = {}
        def dummy_request_fn(method, url, **kwargs):
            captured["url"] = url
            class DummyResponse:
                def __init__(self, url):
                    self.url = url
                    self.text = "Success"
                def raise_for_status(self):
                    pass
            return DummyResponse(url)
        requests.request = dummy_request_fn
        try:
            asyncio.run(dispatcher_handler(dummy_request))
        finally:
            requests.request = original_request
        expected_url = "https://app.asana.com/api/1.0/workspaces/12345/custom_fields"
        self.assertEqual(
            captured.get("url"),
            expected_url,
            f"Expected URL {expected_url}, got {captured.get('url')}"
        )

    @unittest.skip("Skipping due to types namespace issue")
    def test_missing_workspace_gid(self):
        asana_tool = next(
            (t for t in lowlevel.tools if "workspaces" in t.name),
            None
        )
        self.assertIsNotNone(asana_tool, "Asana function not registered")
        dummy_request = SimpleNamespace(
            params=SimpleNamespace(
                name=asana_tool.name,
                arguments={"opt_fields": "id,name"}
            )
        )
        original_request = requests.request
        def dummy_request_fn(method, url, **kwargs):
            class DummyResponse:
                def __init__(self):
                    self.text = "Missing required path parameters: ['workspace_gid']"
                def raise_for_status(self):
                    pass
            return DummyResponse()
        requests.request = dummy_request_fn
        try:
            result = asyncio.run(dispatcher_handler(dummy_request))
        finally:
            requests.request = original_request
        self.assertIn(
            "Missing required path parameters",
            result.root.content[0].text
        )

if __name__ == "__main__":
    unittest.main()
