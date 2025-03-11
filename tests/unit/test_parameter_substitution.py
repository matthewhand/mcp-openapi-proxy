# -*- coding: utf-8 -*-
import unittest
import os
import requests
import asyncio
from types import SimpleNamespace
from mcp_openapi_proxy.server_lowlevel import register_functions, tools, dispatcher_handler
import mcp_openapi_proxy.utils as utils

class TestParameterSubstitution(unittest.TestCase):
    def setUp(self):
        # Ensure we fully reset tools each time so that each test starts fresh.
        tools.clear()

        # Ensure whitelist doesn't filter out our endpoint
        if "TOOL_WHITELIST" in os.environ:
            self.old_tool_whitelist = os.environ["TOOL_WHITELIST"]
        else:
            self.old_tool_whitelist = None
        os.environ["TOOL_WHITELIST"] = ""

        # Patch is_tool_whitelisted in utils to always return True
        self.old_is_tool_whitelisted = utils.is_tool_whitelisted
        utils.is_tool_whitelisted = lambda endpoint: True

        # Dummy Asana OpenAPI spec with workspace_gid in path
        # IMPORTANT: Include commas for valid JSON
        self.dummy_spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base-url.com"}],
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
                                "description": "Owner"
                            },
                            {
                                "name": "repo",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                                "description": "Repo"
                            }
                        ],
                        "responses": {
                            "200": {"description": "OK"}
                        }
                    }
                }
            }
        }
        register_functions(self.dummy_spec)

        # Confirm that exactly one tool was registered
        self.assertEqual(len(tools), 1, "Expected 1 tool to be registered")

    def tearDown(self):
        # Restore the original whitelist patch
        utils.is_tool_whitelisted = self.old_is_tool_whitelisted
        if self.old_tool_whitelist is not None:
            os.environ["TOOL_WHITELIST"] = self.old_tool_whitelist
        else:
            os.environ.pop("TOOL_WHITELIST", None)

    def test_path_parameter_substitution(self):
        # Use the registered tool's name to ensure consistency
        if len(tools) > 0:
            tool_name = tools[0].name
            dummy_request = SimpleNamespace(
                params=SimpleNamespace(
                    name=tool_name,
                    arguments={"owner": "foo", "repo": "bar"}
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

            expected_url = "https://dummy-base-url.com/repos/foo/bar/contents/"
            self.assertEqual(
                captured.get("url"),
                expected_url,
                f"Expected URL {expected_url}, got {captured.get('url')}"
            )
        else:
            self.skipTest("No tools registered")

if __name__ == "__main__":
    unittest.main()
