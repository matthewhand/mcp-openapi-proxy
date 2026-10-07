"""
Integration tests for Asana API via mcp-openapi-proxy, FastMCP mode.
Requires ASANA_API_KEY in .env to run.
"""

import os
import json
import pytest
from dotenv import load_dotenv
from mcp_openapi_proxy.utils import fetch_openapi_spec
from mcp_openapi_proxy.server_fastmcp import list_functions, call_function

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

SPEC_URL = "https://raw.githubusercontent.com/Asana/openapi/refs/heads/master/defs/asana_oas.yaml"
SERVER_URL = "https://app.asana.com/api/1.0"
TOOL_WHITELIST = "/workspaces,/tasks,/projects,/users"
TOOL_PREFIX = "asana_"


def setup_asana_env(env_key, asana_api_key):
    """Set up environment variables for Asana tests."""
    os.environ[env_key] = SPEC_URL
    os.environ["API_KEY"] = asana_api_key
    os.environ["SERVER_URL_OVERRIDE"] = SERVER_URL
    os.environ["TOOL_WHITELIST"] = TOOL_WHITELIST
    os.environ["TOOL_NAME_PREFIX"] = TOOL_PREFIX
    os.environ["DEBUG"] = "true"
    print(f"DEBUG: API_KEY set to: {os.environ['API_KEY'][:5]}...")


def get_tool_name(tools, original_name):
    """Find tool name by original endpoint name."""
    tool = next((t for t in tools if t["original_name"] == original_name), None)
    if not tool:
        print(
            f"DEBUG: Tool not found for {original_name}. Available tools: {[t['original_name'] for t in tools]}"
        )
    return tool["name"] if tool else None


@pytest.fixture
def asana_setup(reset_env_and_module):
    """Fixture to set up Asana env and fetch a workspace ID."""
    env_key = reset_env_and_module
    asana_api_key = os.getenv("ASANA_API_KEY")
    print(f"DEBUG: ASANA_API_KEY: {asana_api_key if asana_api_key else 'Not set'}")
    if not asana_api_key or "your_key" in asana_api_key.lower():
        print("DEBUG: Skipping due to missing or placeholder ASANA_API_KEY")
        pytest.skip("ASANA_API_KEY missing or placeholder—please set it in .env!")

    setup_asana_env(env_key, asana_api_key)

    print(f"DEBUG: Fetching spec from {SPEC_URL}")
    spec = fetch_openapi_spec(SPEC_URL)
    assert spec, f"Failed to fetch spec from {SPEC_URL}"

    print("DEBUG: Listing available functions")
    tools_json = list_functions(env_key=env_key)
    tools = json.loads(tools_json)
    print(f"DEBUG: Tools: {tools_json}")
    assert tools, "No functions generated"

    workspaces_tool = get_tool_name(tools, "GET /workspaces")
    assert workspaces_tool, "Workspaces tool not found!"

    print(f"DEBUG: Calling {workspaces_tool} to find workspace ID")
    response_json = call_function(
        function_name=workspaces_tool, parameters={}, env_key=env_key
    )
    print(f"DEBUG: Workspaces response: {response_json}")
    response = json.loads(response_json)
    assert "data" in response and response["data"], "No workspaces found!"

    workspace_gid = response["data"][0]["gid"]
    return env_key, tools, workspace_gid


@pytest.mark.integration
def test_asana_workspaces_list(asana_setup):
    """Test Asana /workspaces endpoint with ASANA_API_KEY."""
    env_key, tools, _ = asana_setup
    tool_name = get_tool_name(tools, "GET /workspaces")
    assert tool_name, "Function for GET /workspaces not found!"

    print(f"DEBUG: Calling {tool_name} for workspaces list")
    response_json = call_function(
        function_name=tool_name, parameters={}, env_key=env_key
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error occurred: {response['error']}")
            if (
                "401" in response["error"]
                or "authentication" in response["error"].lower()
            ):
                assert False, "ASANA_API_KEY is invalid—please check your token!"
            assert False, f"Asana API returned an error: {response_json}"
        assert isinstance(
            response, dict
        ), f"Response is not a dictionary: {response_json}"
        assert "data" in response, f"No 'data' key in response: {response_json}"
        assert isinstance(response["data"], list), "Data is not a list"
        assert (
            len(response["data"]) > 0
        ), "No workspaces found—please ensure your Asana account has workspaces!"
        print(f"DEBUG: Found {len(response['data'])} workspaces—excellent!")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"


@pytest.mark.integration
def test_asana_tasks_list(asana_setup):
    """Test Asana /tasks endpoint with ASANA_API_KEY."""
    env_key, tools, workspace_gid = asana_setup
    tool_name = get_tool_name(tools, "GET /tasks")
    assert tool_name, "Function for GET /tasks not found!"

    print(f"DEBUG: Calling {tool_name} for tasks in workspace {workspace_gid}")
    response_json = call_function(
        function_name=tool_name,
        parameters={"workspace": workspace_gid, "assignee": "me"},
        env_key=env_key,
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error occurred: {response['error']}")
            if (
                "401" in response["error"]
                or "authentication" in response["error"].lower()
            ):
                assert False, "ASANA_API_KEY is invalid—please check your token!"
            assert False, f"Asana API returned an error: {response_json}"
        assert isinstance(
            response, dict
        ), f"Response is not a dictionary: {response_json}"
        assert "data" in response, f"No 'data' key in response: {response_json}"
        assert isinstance(response["data"], list), "Data is not a list"
        print(f"DEBUG: Found {len(response['data'])} tasks—excellent!")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"


@pytest.mark.integration
def test_asana_projects_list(asana_setup):
    """Test Asana /projects endpoint with ASANA_API_KEY."""
    env_key, tools, workspace_gid = asana_setup
    tool_name = get_tool_name(tools, "GET /projects")
    assert tool_name, "Function for GET /projects not found!"

    print(f"DEBUG: Calling {tool_name} for projects in workspace {workspace_gid}")
    response_json = call_function(
        function_name=tool_name,
        parameters={"workspace": workspace_gid},
        env_key=env_key,
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error occurred: {response['error']}")
            if (
                "401" in response["error"]
                or "authentication" in response["error"].lower()
            ):
                assert False, "ASANA_API_KEY is invalid—please check your token!"
            assert False, f"Asana API returned an error: {response_json}"
        assert isinstance(
            response, dict
        ), f"Response is not a dictionary: {response_json}"
        assert "data" in response, f"No 'data' key in response: {response_json}"
        assert isinstance(response["data"], list), "Data is not a list"
        print(f"DEBUG: Found {len(response['data'])} projects—excellent!")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"
