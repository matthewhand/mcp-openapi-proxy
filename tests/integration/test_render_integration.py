"""
Integration tests for Render.com API via mcp-openapi-proxy, FastMCP mode.
Needs RENDER_API_KEY in .env to run.
"""

import os
import json
import pytest
from dotenv import load_dotenv
from mcp_openapi_proxy.utils import fetch_openapi_spec
from mcp_openapi_proxy.server_fastmcp import mcp, list_functions, call_function

# Load .env file from project root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))


@pytest.mark.integration
def test_render_services_list(reset_env_and_module):
    """Test Render /services endpoint with RENDER_API_KEY."""
    env_key = reset_env_and_module
    render_api_key = os.getenv("RENDER_API_KEY")
    # Prefer RENDER_SPEC_URL if set, else use Render's public OpenAPI spec
    spec_url = os.getenv(
        "RENDER_SPEC_URL",
        "https://api-docs.render.com/openapi/6140fb3daeae351056086186",
    )
    # Always set SERVER_URL_OVERRIDE to the correct Render API base for this test
    os.environ["SERVER_URL_OVERRIDE"] = "https://api.render.com/v1"
    tool_prefix = os.getenv("TOOL_NAME_PREFIX", "render_")
    print(f"DEBUG: RENDER_API_KEY: {render_api_key if render_api_key else 'Not set'}")
    if not render_api_key or "your-" in render_api_key:
        print("DEBUG: Skipping due to missing or placeholder RENDER_API_KEY")
        pytest.skip("RENDER_API_KEY missing or placeholder—please set it in .env!")

    # Fetch the spec
    print(f"DEBUG: Fetching spec from {spec_url}")
    openapi_spec_data = fetch_openapi_spec(spec_url)
    assert openapi_spec_data, f"Failed to fetch spec from {spec_url}"
    assert "paths" in openapi_spec_data, "No 'paths' key in spec"
    assert "/services" in openapi_spec_data["paths"], "No /services endpoint in spec"
    assert (
        "servers" in openapi_spec_data or "host" in openapi_spec_data
    ), "No servers or host defined in spec"

    # Set env vars
    os.environ[env_key] = spec_url
    os.environ["API_KEY"] = render_api_key
    os.environ["API_KEY_JMESPATH"] = ""  # Render uses header auth, no JMESPath
    os.environ["API_AUTH_TYPE"] = "Bearer"  # Render expects Bearer token
    os.environ["TOOL_NAME_PREFIX"] = tool_prefix
    os.environ["TOOL_WHITELIST"] = "/services,/deployments"
    os.environ["DEBUG"] = "true"
    print(f"DEBUG: API_KEY set to: {os.environ['API_KEY'][:5]}...")

    # Verify tools
    registered_tools = list_functions(env_key=env_key)
    assert registered_tools, "No tools registered from spec!"
    tools = json.loads(registered_tools)
    assert any(
        tool["name"] == f"{tool_prefix}get_services" for tool in tools
    ), "get_services tool not found!"

    # Call the tool to list services
    response_json = call_function(
        function_name=f"{tool_prefix}get_services", parameters={}, env_key=env_key
    )
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error hit: {response['error']}")
            if "401" in response["error"]:
                assert False, "RENDER_API_KEY is invalid—please check your token."
            assert False, f"Render API returned an error: {response_json}"
        assert isinstance(response, list), f"Response is not a list: {response_json}"
        assert (
            len(response) > 0
        ), "No services found—please ensure you have deployed services."
        print(f"DEBUG: Found {len(response)} services.")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"
