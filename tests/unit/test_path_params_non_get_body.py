# -*- coding: utf-8 -*-
"""Regression: path parameters must be stripped from non-GET request bodies.

The placeholder strip previously ran only for GET, so on POST/PUT/PATCH/DELETE
the substituted path params leaked into the JSON body and strict APIs rejected
the unexpected fields -- e.g. Home Assistant POST /api/services/{domain}/{service}
returned HTTP 400 because the body carried domain/service.
"""
import unittest
import os
import asyncio
from types import SimpleNamespace

import requests

from mcp_openapi_proxy.handlers import register_functions
from mcp_openapi_proxy.server_lowlevel import tools, dispatcher_handler
import mcp_openapi_proxy.utils as utils


class TestPathParamsNonGetBody(unittest.TestCase):
    def setUp(self):
        tools.clear()
        self.old_wl = os.environ.get("TOOL_WHITELIST")
        os.environ["TOOL_WHITELIST"] = ""
        self.old_is_wl = utils.is_tool_whitelisted
        utils.is_tool_whitelisted = lambda endpoint: True
        self.spec = {
            "openapi": "3.0.0",
            "servers": [{"url": "https://dummy-base-url.com"}],
            "paths": {
                "/widgets/{a}/{b}": {
                    "post": {
                        "summary": "Create widget",
                        "parameters": [
                            {"name": "a", "in": "path", "required": True, "schema": {"type": "string"}},
                            {"name": "b", "in": "path", "required": True, "schema": {"type": "string"}},
                        ],
                        "requestBody": {
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {"x": {"type": "string"}},
                            }}}
                        },
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        register_functions(self.spec)
        import mcp_openapi_proxy.server_lowlevel as lowlevel
        lowlevel.openapi_spec_data = self.spec
        self.assertEqual(len(tools), 1, "expected 1 tool registered")

    def tearDown(self):
        utils.is_tool_whitelisted = self.old_is_wl
        if self.old_wl is not None:
            os.environ["TOOL_WHITELIST"] = self.old_wl
        else:
            os.environ.pop("TOOL_WHITELIST", None)

    def test_path_params_not_in_post_body(self):
        """URL gets a/b substituted; JSON body carries only the requestBody prop x."""
        req = SimpleNamespace(params=SimpleNamespace(
            name=tools[0].name, arguments={"a": "foo", "b": "bar", "x": "hello"}))
        captured = {}
        orig = requests.request

        def fake(method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = kwargs.get("json")

            class R:
                status_code = 200
                text = "{}"
                headers = {"Content-Type": "application/json"}
                def json(self_inner):
                    return {}
                def raise_for_status(self_inner):
                    pass
            return R()

        requests.request = fake
        try:
            asyncio.run(dispatcher_handler(req))  # type: ignore
        finally:
            requests.request = orig

        self.assertEqual(captured.get("method"), "POST")
        self.assertIn("/widgets/foo/bar", captured.get("url", ""),
                      f"path not substituted into URL: {captured.get('url')}")
        self.assertEqual(captured.get("json"), {"x": "hello"},
                         f"body must contain ONLY requestBody props, got {captured.get('json')}")
        self.assertNotIn("a", captured.get("json") or {})
        self.assertNotIn("b", captured.get("json") or {})


if __name__ == "__main__":
    unittest.main()
