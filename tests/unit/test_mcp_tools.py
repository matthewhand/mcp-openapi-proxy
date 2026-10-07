#!/usr/bin/env python3
import os
import json
import unittest
import asyncio
import pytest
from types import SimpleNamespace
from mcp_openapi_proxy import server_fastmcp, server_lowlevel, utils
from mcp import types

DUMMY_SPEC = {
    "paths": {"/dummy": {"get": {"summary": "Dummy function", "parameters": []}}}
}


class TestMcpTools(unittest.TestCase):
    def setUp(self):
        self.original_fetch_spec = utils.fetch_openapi_spec
        utils.fetch_openapi_spec = lambda url: DUMMY_SPEC
        self.original_fastmcp_fetch = getattr(
            server_fastmcp, "fetch_openapi_spec", None
        )
        server_fastmcp.fetch_openapi_spec = lambda url: DUMMY_SPEC
        self.original_lowlevel_fetch = getattr(
            server_lowlevel, "fetch_openapi_spec", None
        )
        server_lowlevel.fetch_openapi_spec = lambda url: DUMMY_SPEC
        # Patch both server_lowlevel and handlers prompts
        import mcp_openapi_proxy.handlers as handlers

        handlers.prompts = server_lowlevel.prompts = [
            types.Prompt(
                name="summarize_spec",
                description="Dummy prompt",
                arguments=[],
                messages=lambda args: [
                    types.PromptMessage(
                        role="assistant",
                        content=types.TextContent(
                            type="text",
                            text="This OpenAPI spec defines an API’s endpoints, parameters, and responses, making it a blueprint for devs.",
                        ),
                    )
                ],
            )
        ]
        os.environ["OPENAPI_SPEC_URL"] = "http://dummy_url"
        # Ensure resources are enabled for relevant tests
        os.environ["ENABLE_RESOURCES"] = "true"
        if "EXTRA_HEADERS" in os.environ:
            del os.environ["EXTRA_HEADERS"]

    def tearDown(self):
        utils.fetch_openapi_spec = self.original_fetch_spec
        if self.original_fastmcp_fetch is not None:
            server_fastmcp.fetch_openapi_spec = self.original_fastmcp_fetch
        if self.original_lowlevel_fetch is not None:
            server_lowlevel.fetch_openapi_spec = self.original_lowlevel_fetch
        if "EXTRA_HEADERS" in os.environ:
            del os.environ["EXTRA_HEADERS"]
        # Clean up env var
        if "ENABLE_RESOURCES" in os.environ:
            del os.environ["ENABLE_RESOURCES"]

    def test_list_tools_server_fastmcp(self):
        result_json = server_fastmcp.list_functions(env_key="OPENAPI_SPEC_URL")
        result = json.loads(result_json)
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(
            len(result),
            1,
            f"Expected at least 1 tool, got {len(result)}. Result: {result}",
        )
        tool_names = [tool.get("name") for tool in result]
        self.assertIn("list_resources", tool_names)

    def test_list_resources_server_lowlevel(self):
        request = SimpleNamespace(params=SimpleNamespace())  # type: ignore
        result = asyncio.run(server_lowlevel.list_resources(request))  # type: ignore
        self.assertTrue(
            hasattr(result, "resources"), "Result has no attribute 'resources'"
        )
        self.assertGreaterEqual(len(result.resources), 1)
        self.assertEqual(result.resources[0].name, "spec_file")

    def test_list_prompts_server_lowlevel(self):
        request = SimpleNamespace(params=SimpleNamespace())  # type: ignore
        result = asyncio.run(server_lowlevel.list_prompts(request))  # type: ignore
        self.assertTrue(hasattr(result, "prompts"), "Result has no attribute 'prompts'")
        self.assertGreaterEqual(len(result.prompts), 1)
        prompt_names = [prompt.name for prompt in result.prompts]
        self.assertIn("summarize_spec", prompt_names)

    def test_get_prompt_server_lowlevel(self):
        from mcp_openapi_proxy import handlers

        params = SimpleNamespace(name="summarize_spec", arguments={})  # type: ignore
        request = SimpleNamespace(params=params)  # type: ignore
        # Call the handlers.get_prompt directly to ensure the patched prompts are used
        result = asyncio.run(handlers.get_prompt(request))  # type: ignore
        self.assertTrue(
            hasattr(result, "messages"), "Result has no attribute 'messages'"
        )
        self.assertIsInstance(result.messages, list)
        msg = result.messages[0]
        # handlers.get_prompt returns a types.TextContent, not dict
        content_text = msg.content.text if hasattr(msg.content, "text") else ""
        self.assertIn(
            "blueprint",
            content_text,
            f"Expected 'blueprint' in message text, got: {content_text}",
        )

    def test_get_additional_headers(self):
        os.environ["EXTRA_HEADERS"] = "X-Test: Value\nX-Another: More"
        headers = utils.get_additional_headers()
        self.assertEqual(headers.get("X-Test"), "Value")
        self.assertEqual(headers.get("X-Another"), "More")


if __name__ == "__main__":
    unittest.main()
