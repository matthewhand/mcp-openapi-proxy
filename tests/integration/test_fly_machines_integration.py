"""
Integration test for Fly Machines API using get_apps function.
"""

import os
import json
import pytest
from dotenv import load_dotenv
from mcp_openapi_proxy.utils import fetch_openapi_spec
from mcp_openapi_proxy.server_fastmcp import mcp, list_functions, call_function

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))


@pytest.mark.integration
def test_fly_machines_get_apps(reset_env_and_module):
    """Test integration with Fly Machines API using get_apps function."""
    env_key = reset_env_and_module
    fly_api_key = os.getenv("FLY_API_KEY")
    print(f"DEBUG: FLY_API_KEY from env: {fly_api_key if fly_api_key else 'Not set'}")
    if not fly_api_key:
        print("DEBUG: Skipping due to missing FLY_API_KEY")
        pytest.skip(
            "FLY_API_KEY not set in .env - skipping Fly Machines integration test"
        )

    spec_url = "https://raw.githubusercontent.com/abhiaagarwal/peristera/refs/heads/main/fly-machines-gen/fixed_spec.json"
    print(f"DEBUG: Fetching spec from {spec_url}")
    spec = fetch_openapi_spec(spec_url)
    assert spec is not None, f"Failed to fetch OpenAPI spec from {spec_url}"
    assert "paths" in spec, "Spec must contain 'paths' key"
    assert "/apps" in spec["paths"], "Spec must define /apps endpoint"
    assert "get" in spec["paths"]["/apps"], "Spec must define GET /apps"
    assert "servers" in spec, "Spec must define servers"
    print(f"DEBUG: Using server from spec: {spec['servers'][0]['url']}")

    os.environ[env_key] = spec_url
    os.environ["FLY_API_KEY"] = fly_api_key
    os.environ["API_KEY"] = fly_api_key  # Map FLY_API_KEY to API_KEY for the HTTP call
    os.environ["API_AUTH_TYPE"] = "Bearer"
    os.environ["DEBUG"] = "true"

    print("DEBUG: Listing functions")
    tools_json = list_functions(env_key=env_key)
    tools = json.loads(tools_json)
    assert isinstance(tools, list), "list_functions returned invalid data (not a list)"
    assert len(tools) > 0, f"No functions generated from Fly spec: {tools_json}"
    assert any(
        tool["name"] == "get_apps" for tool in tools
    ), "get_apps function not found in functions"

    org_slug = "personal"  # Works in yer client, ya clever sod
    print(f"DEBUG: Calling get_apps with org_slug={org_slug}")
    response_json = call_function(
        function_name="get_apps", parameters={"org_slug": org_slug}, env_key=env_key
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Response contains error: {response['error']}")
            if "404" in response["error"]:
                print("DEBUG: Got 404 from Fly API - check org_slug")
                pytest.skip(
                    f"Fly API returned 404 - org_slug '{org_slug}' may not exist"
                )
            if "401" in response["error"]:
                assert False, "FLY_API_KEY invalid - check .env or Fly API"
            assert False, f"Unexpected error from Fly API: {response_json}"
        assert isinstance(
            response, dict
        ), f"Expected a dict response, got: {response_json}"
        assert "apps" in response, f"No 'apps' key in response: {response_json}"
        assert len(response["apps"]) > 0, f"No apps returned: {response_json}"
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"
