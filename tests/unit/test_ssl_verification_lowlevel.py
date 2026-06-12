# -*- coding: utf-8 -*-
"""Tests that IGNORE_SSL_TOOLS controls SSL verification in low-level mode tool calls."""
import unittest
import os
import requests
import asyncio
from types import SimpleNamespace
from mcp_openapi_proxy.handlers import register_functions
from mcp_openapi_proxy.server_lowlevel import tools, dispatcher_handler
import mcp_openapi_proxy.utils as utils


class TestSslVerificationLowLevel(unittest.TestCase):
    def setUp(self):
        tools.clear()

        self.old_tool_whitelist = os.environ.pop("TOOL_WHITELIST", None)
        os.environ["TOOL_WHITELIST"] = ""
        self.old_ignore_ssl_tools = os.environ.pop("IGNORE_SSL_TOOLS", None)

        self.old_is_tool_whitelisted = utils.is_tool_whitelisted
        utils.is_tool_whitelisted = lambda endpoint: True

        self.dummy_spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base-url.com"}],
            "paths": {
                "/widgets": {
                    "get": {
                        "summary": "List widgets",
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        register_functions(self.dummy_spec)
        import mcp_openapi_proxy.server_lowlevel as lowlevel
        lowlevel.openapi_spec_data = self.dummy_spec

        self.assertEqual(len(tools), 1, "Expected 1 tool to be registered")

    def tearDown(self):
        utils.is_tool_whitelisted = self.old_is_tool_whitelisted
        if self.old_tool_whitelist is not None:
            os.environ["TOOL_WHITELIST"] = self.old_tool_whitelist
        else:
            os.environ.pop("TOOL_WHITELIST", None)
        if self.old_ignore_ssl_tools is not None:
            os.environ["IGNORE_SSL_TOOLS"] = self.old_ignore_ssl_tools
        else:
            os.environ.pop("IGNORE_SSL_TOOLS", None)

    def _call_tool_and_capture_kwargs(self):
        tool_name = tools[0].name
        dummy_request = SimpleNamespace(
            params=SimpleNamespace(name=tool_name, arguments={})
        )
        original_request = requests.request
        captured = {}

        def dummy_request_fn(method=None, url=None, **kwargs):
            captured.update(kwargs)
            captured["method"] = method
            captured["url"] = url

            class DummyResponse:
                text = "{}"

                def raise_for_status(self):
                    pass

            return DummyResponse()

        requests.request = dummy_request_fn
        try:
            asyncio.run(dispatcher_handler(dummy_request))  # type: ignore
        finally:
            requests.request = original_request
        return captured

    def test_ssl_verification_enabled_by_default(self):
        os.environ.pop("IGNORE_SSL_TOOLS", None)
        captured = self._call_tool_and_capture_kwargs()
        self.assertIn("verify", captured, "Expected verify kwarg to be passed to requests.request")
        self.assertTrue(captured["verify"], "SSL verification should be enabled by default")

    def test_ignore_ssl_tools_disables_verification(self):
        for truthy in ("true", "1", "yes"):
            os.environ["IGNORE_SSL_TOOLS"] = truthy
            captured = self._call_tool_and_capture_kwargs()
            self.assertIn("verify", captured)
            self.assertFalse(
                captured["verify"],
                f"IGNORE_SSL_TOOLS={truthy} should disable SSL verification"
            )

    def test_ignore_ssl_tools_false_keeps_verification(self):
        os.environ["IGNORE_SSL_TOOLS"] = "false"
        captured = self._call_tool_and_capture_kwargs()
        self.assertTrue(captured["verify"], "IGNORE_SSL_TOOLS=false should keep SSL verification on")


if __name__ == "__main__":
    unittest.main()
