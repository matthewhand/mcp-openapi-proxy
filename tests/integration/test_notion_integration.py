"""
Integration tests for Notion API via mcp-openapi-proxy, FastMCP mode.
Requires NOTION_API_KEY in .env to run.
"""

import os
import json
import pytest
from dotenv import load_dotenv
from mcp_openapi_proxy.utils import fetch_openapi_spec
from mcp_openapi_proxy.server_fastmcp import list_functions, call_function

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

SPEC_URL = (
    "https://storage.googleapis.com/versori-assets/public-specs/20240214/NotionAPI.yml"
)
SERVER_URL = "https://api.notion.com"
EXTRA_HEADERS = "Notion-Version: 2022-06-28"
TOOL_PREFIX = "notion_"


def setup_notion_env(env_key, notion_api_key):
    """Set up environment variables for Notion tests."""
    os.environ[env_key] = SPEC_URL
    os.environ["API_KEY"] = notion_api_key
    os.environ["SERVER_URL_OVERRIDE"] = SERVER_URL
    os.environ["EXTRA_HEADERS"] = EXTRA_HEADERS
    os.environ["TOOL_NAME_PREFIX"] = TOOL_PREFIX
    os.environ["DEBUG"] = "true"
    print(f"DEBUG: API_KEY set to: {os.environ['API_KEY'][:5]}...")


def get_tool_name(tools, original_name):
    """Find tool name by original endpoint name."""
    return next(
        (tool["name"] for tool in tools if tool["original_name"] == original_name), None
    )


@pytest.fixture
def notion_ids(reset_env_and_module):
    """Fixture to fetch a page ID and database ID from Notion."""
    env_key = reset_env_and_module
    notion_api_key = os.getenv("NOTION_API_KEY")
    print(f"DEBUG: NOTION_API_KEY: {notion_api_key if notion_api_key else 'Not set'}")
    if not notion_api_key or "your_key" in notion_api_key:
        print("DEBUG: Skipping due to missing or placeholder NOTION_API_KEY")
        pytest.skip("NOTION_API_KEY missing or placeholder—set it in .env, please!")

    setup_notion_env(env_key, notion_api_key)

    print(f"DEBUG: Fetching spec from {SPEC_URL}")
    spec = fetch_openapi_spec(SPEC_URL)
    assert spec, f"Failed to fetch spec from {SPEC_URL}"

    print("DEBUG: Listing available functions")
    tools_json = list_functions(env_key=env_key)
    tools = json.loads(tools_json)
    print(f"DEBUG: Tools: {tools_json}")
    assert tools, "No functions generated"

    search_tool = get_tool_name(tools, "POST /v1/search")
    assert search_tool, "Search tool not found!"

    print(f"DEBUG: Calling {search_tool} to find IDs")
    response_json = call_function(
        function_name=search_tool, parameters={"query": ""}, env_key=env_key
    )
    print(f"DEBUG: Search response: {response_json}")
    response = json.loads(response_json)
    assert "results" in response, "No results in search response"

    page_id = None
    db_id = None
    for item in response["results"]:
        if item["object"] == "page" and not page_id:
            page_id = item["id"]
        elif item["object"] == "database" and not db_id:
            db_id = item["id"]
        if page_id and db_id:
            break

    if not page_id or not db_id:
        print(f"DEBUG: Page ID: {page_id}, DB ID: {db_id}")
        pytest.skip("No page or database found in search—please add some to Notion!")

    return env_key, tools, page_id, db_id


@pytest.mark.integration
def test_notion_users_list(notion_ids):
    """Test Notion /v1/users endpoint with NOTION_API_KEY."""
    env_key, tools, _, _ = notion_ids
    tool_name = get_tool_name(tools, "GET /v1/users")
    assert tool_name, "Function for GET /v1/users not found!"

    print(f"DEBUG: Calling {tool_name} for user list")
    response_json = call_function(
        function_name=tool_name, parameters={}, env_key=env_key
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error occurred: {response['error']}")
            if "401" in response["error"] or "invalid_token" in response["error"]:
                assert False, "NOTION_API_KEY is invalid—please check your token!"
            assert False, f"Notion API returned an error: {response_json}"
        assert isinstance(
            response, dict
        ), f"Response is not a dictionary: {response_json}"
        assert "results" in response, f"No 'results' key in response: {response_json}"
        assert isinstance(response["results"], list), "Results is not a list"
        print(f"DEBUG: Found {len(response['results'])} users—excellent!")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"


@pytest.mark.integration
def test_notion_users_me(notion_ids):
    """Test Notion /v1/users/me endpoint with NOTION_API_KEY."""
    env_key, tools, _, _ = notion_ids
    tool_name = get_tool_name(tools, "GET /v1/users/me")
    assert tool_name, "Function for GET /v1/users/me not found!"

    print(f"DEBUG: Calling {tool_name} for bot user")
    response_json = call_function(
        function_name=tool_name, parameters={}, env_key=env_key
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error occurred: {response['error']}")
            if "401" in response["error"] or "invalid_token" in response["error"]:
                assert False, "NOTION_API_KEY is invalid—please check your token!"
            assert False, f"Notion API returned an error: {response_json}"
        assert isinstance(
            response, dict
        ), f"Response is not a dictionary: {response_json}"
        assert (
            "object" in response and response["object"] == "user"
        ), "Response is not a user object"
        assert "type" in response and response["type"] == "bot", "Expected bot user"
        print(f"DEBUG: Got bot user: {response.get('name', 'Unnamed')}—excellent!")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"


@pytest.mark.integration
def test_notion_search(notion_ids):
    """Test Notion /v1/search endpoint with NOTION_API_KEY."""
    env_key, tools, _, _ = notion_ids
    tool_name = get_tool_name(tools, "POST /v1/search")
    assert tool_name, "Function for POST /v1/search not found!"

    print(f"DEBUG: Calling {tool_name} for search")
    response_json = call_function(
        function_name=tool_name, parameters={"query": "test"}, env_key=env_key
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error occurred: {response['error']}")
            if "401" in response["error"] or "invalid_token" in response["error"]:
                assert False, "NOTION_API_KEY is invalid—please check your token!"
            assert False, f"Notion API returned an error: {response_json}"
        assert isinstance(
            response, dict
        ), f"Response is not a dictionary: {response_json}"
        assert "results" in response, f"No 'results' key in response: {response_json}"
        assert isinstance(response["results"], list), "Results is not a list"
        print(f"DEBUG: Found {len(response['results'])} search results—excellent!")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"


@pytest.mark.integration
def test_notion_get_page(notion_ids):
    """Test Notion /v1/pages/{id} endpoint with NOTION_API_KEY."""
    env_key, tools, page_id, _ = notion_ids
    tool_name = get_tool_name(tools, "GET /v1/pages/{id}")
    assert tool_name, "Function for GET /v1/pages/{id} not found!"

    print(f"DEBUG: Calling {tool_name} for page {page_id}")
    response_json = call_function(
        function_name=tool_name, parameters={"id": page_id}, env_key=env_key
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error occurred: {response['error']}")
            if "401" in response["error"] or "invalid_token" in response["error"]:
                assert False, "NOTION_API_KEY is invalid—please check your token!"
            assert False, f"Notion API returned an error: {response_json}"
        assert isinstance(
            response, dict
        ), f"Response is not a dictionary: {response_json}"
        assert (
            "object" in response and response["object"] == "page"
        ), "Response is not a page object"
        assert (
            response["id"] == page_id
        ), f"Expected page ID {page_id}, got {response['id']}"
        print(f"DEBUG: Got page: {response.get('url', 'No URL')}—excellent!")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"


@pytest.mark.integration
def test_notion_query_database(notion_ids):
    """Test Notion /v1/databases/{id}/query endpoint with NOTION_API_KEY."""
    env_key, tools, _, db_id = notion_ids
    tool_name = get_tool_name(tools, "POST /v1/databases/{id}/query")
    assert tool_name, "Function for POST /v1/databases/{id}/query not found!"

    print(f"DEBUG: Calling {tool_name} for database {db_id}")
    response_json = call_function(
        function_name=tool_name, parameters={"id": db_id}, env_key=env_key
    )
    print(f"DEBUG: Raw response: {response_json}")
    try:
        response = json.loads(response_json)
        if isinstance(response, dict) and "error" in response:
            print(f"DEBUG: Error occurred: {response['error']}")
            if "401" in response["error"] or "invalid_token" in response["error"]:
                assert False, "NOTION_API_KEY is invalid—please check your token!"
            assert False, f"Notion API returned an error: {response_json}"
        assert isinstance(
            response, dict
        ), f"Response is not a dictionary: {response_json}"
        assert "results" in response, f"No 'results' key in response: {response_json}"
        assert isinstance(response["results"], list), "Results is not a list"
        print(f"DEBUG: Found {len(response['results'])} database entries—excellent!")
    except json.JSONDecodeError:
        assert False, f"Response is not valid JSON: {response_json}"
