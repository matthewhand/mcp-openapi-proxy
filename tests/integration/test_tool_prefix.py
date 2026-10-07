"""
Integration test for function name generation from OpenAPI spec.
"""

import os
import json
import pytest
from mcp_openapi_proxy.server_fastmcp import list_functions


@pytest.mark.integration
def test_function_name_mapping(reset_env_and_module):
    """Test that function names are correctly generated from OpenAPI spec."""
    env_key = reset_env_and_module
    spec_url = "https://petstore.swagger.io/v2/swagger.json"
    os.environ[env_key] = spec_url
    os.environ["DEBUG"] = "true"

    tools_json = list_functions(env_key=env_key)
    tools = json.loads(tools_json)
    assert isinstance(tools, list), "Functions should be a list"
    assert len(tools) > 0, "No functions generated from spec"
    for tool in tools:
        name = tool["name"]
        # Only check HTTP method prefix for tools with a method (skip built-ins like list_resources)
        if tool.get("method"):
            assert name.startswith(
                ("get_", "post_", "put_", "delete_")
            ), f"Function name {name} should start with HTTP method prefix"
        assert " " not in name, f"Function name {name} should have no spaces"
