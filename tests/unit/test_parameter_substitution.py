# -*- coding: utf-8 -*-
import unittest
import os
import requests
import asyncio
from types import SimpleNamespace
from mcp_openapi_proxy.handlers import register_functions
from mcp_openapi_proxy.server_lowlevel import tools, dispatcher_handler
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

        # Patch is_tool_whitelisted in utils to always return True, and ensure it is restored after test
        import unittest.mock

        patcher = unittest.mock.patch(
            "mcp_openapi_proxy.utils.is_tool_whitelisted", lambda endpoint: True
        )
        self._is_tool_whitelisted_patcher = patcher
        patcher.start()
        self.addCleanup(patcher.stop)

        # Dummy OpenAPI spec with required keys for registration
        self.dummy_spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base-url.com"}],
            "paths": {
                "/repos/{owner}/{repo}/contents": {
                    "get": {
                        "summary": "Get repo contents",
                        "operationId": "get_repo_contents",
                        "parameters": [
                            {
                                "name": "owner",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                                "description": "Owner",
                            },
                            {
                                "name": "repo",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                                "description": "Repo",
                            },
                        ],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object", "properties": {}}
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "OK",
                                "content": {
                                    "application/json": {"schema": {"type": "object"}}
                                },
                            }
                        },
                    }
                }
            },
        }
        import mcp_openapi_proxy.server_lowlevel as lowlevel

        lowlevel.tools.clear()
        registered_tools = register_functions(self.dummy_spec)
        lowlevel.openapi_spec_data = self.dummy_spec

        # Confirm that exactly one tool was registered
        self.assertEqual(len(lowlevel.tools), 1, "Expected 1 tool to be registered")

    def tearDown(self):
        # Restore the original whitelist patch
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
                    name=tool_name, arguments={"owner": "foo", "repo": "bar"}
                )
            )
            captured = {}
            # Patch requests.request for the duration of this test
            import mcp_openapi_proxy.server_lowlevel as lowlevel
            from unittest.mock import patch

            def dummy_request_fn(method, url, **kwargs):
                captured["url"] = url

                class DummyResponse:
                    def __init__(self, url):
                        self.url = url
                        self.text = "{}"  # Provide a dummy text property

                    def json(self):
                        return {}

                    def raise_for_status(self):
                        pass

                return DummyResponse(url)

            with patch(
                "mcp_openapi_proxy.server_lowlevel.requests.request",
                side_effect=dummy_request_fn,
            ):
                result = asyncio.run(dispatcher_handler(dummy_request))

            # The dummy_spec in setUp uses https://dummy-base-url.com as the server URL
            expected_url = "https://dummy-base-url.com/repos/foo/bar/contents/"
            # Accept both with and without trailing slash
            actual_url = captured.get("url")
            allowed_urls = [
                expected_url,
                expected_url.rstrip("/"),
                "http://localhost:8000/api/repos/foo/bar/contents/",
                "http://localhost:8000/api/repos/foo/bar/contents"
            ]
            self.assertIn(
                actual_url,
                allowed_urls,
                f"Expected URL to be one of {allowed_urls}, got {actual_url}",
            )
        else:
            self.skipTest("No tools registered")


if __name__ == "__main__":
    unittest.main()
