import os
import json
import pytest
import logging

logger = logging.getLogger(__name__)

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
VIRUSTOTAL_OPENAPI_URL = f"file://{os.path.join(os.path.dirname(TEST_DIR), '..', 'examples', 'virustotal.openapi.yml')}"


# Helper function to load spec, used by multiple tests
def load_spec(spec_path):
    with open(spec_path, "r") as f:
        spec_format = os.getenv("OPENAPI_SPEC_FORMAT", "json").lower()
        if spec_format == "yaml":
            import yaml

            try:
                spec = yaml.safe_load(f)
            except yaml.YAMLError:
                logger.error(f"Failed to parse YAML from {spec_path}")
                spec = None
        else:
            try:
                spec = json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON from {spec_path}")
                spec = None
    return spec


def setup_virustotal_env(env_key, api_key, spec_url):
    """Sets up environment variables for VirusTotal tests."""
    spec_path = spec_url.replace("file://", "")

    # Ensure spec format is set correctly BEFORE loading
    if spec_url.endswith(".yml") or spec_url.endswith(".yaml"):
        os.environ["OPENAPI_SPEC_FORMAT"] = "yaml"
        logger.debug("Setting OPENAPI_SPEC_FORMAT=yaml for spec loading")
    else:
        os.environ.pop("OPENAPI_SPEC_FORMAT", None)  # Default to JSON if not YAML
        logger.debug("Using default JSON spec format for loading")

    spec = load_spec(spec_path)
    if spec is None:
        pytest.skip(
            "VirusTotal OpenAPI spec is empty or invalid after loading attempt."
        )

    os.environ[env_key] = spec_url
    whitelist = ",".join(spec["paths"].keys())
    os.environ["TOOL_WHITELIST"] = whitelist
    os.environ["API_KEY"] = api_key  # Use API_KEY as per utils.handle_auth default
    os.environ["API_AUTH_TYPE"] = (
        "api-key"  # Use API_AUTH_TYPE instead of deprecated override
    )
    os.environ["API_AUTH_HEADER"] = "x-apikey"  # VirusTotal uses x-apikey header

    logger.debug(f"Using env key: {env_key}")
    logger.debug(f"TOOL_WHITELIST set to: {whitelist}")
    logger.debug(f"API_AUTH_TYPE set to: {os.environ['API_AUTH_TYPE']}")
    logger.debug(f"API_AUTH_HEADER set to: {os.environ['API_AUTH_HEADER']}")
    logger.debug(
        f"OPENAPI_SPEC_FORMAT: {os.getenv('OPENAPI_SPEC_FORMAT', 'default json')}"
    )
    return spec


@pytest.fixture(scope="function", autouse=True)
def virustotal_api_key_check():
    if not os.getenv("VIRUSTOTAL_API_KEY"):
        pytest.skip("VIRUSTOTAL_API_KEY not set in .env, skipping VirusTotal tests.")


def test_virustotal_openapi_and_tools(reset_env_and_module):
    env_key = reset_env_and_module
    api_key = os.getenv("VIRUSTOTAL_API_KEY")  # Already checked by fixture

    spec = setup_virustotal_env(env_key, api_key, VIRUSTOTAL_OPENAPI_URL)

    # Validate the OpenAPI structure
    assert (
        "swagger" in spec or "openapi" in spec
    ), "Invalid OpenAPI document: missing version key."
    assert "paths" in spec and spec["paths"], "No API paths found in the specification."
    print(
        f"DEBUG: Virustotal spec version: {spec.get('swagger') or spec.get('openapi')}"
    )
    print(f"DEBUG: First endpoint found: {next(iter(spec['paths'] or {}), 'none')}")
    print(f"DEBUG: Total paths in spec: {len(spec.get('paths', {}))}")

    # Import after environment setup
    from mcp_openapi_proxy.server_fastmcp import list_functions

    logger.debug(
        f"Env before list_functions: {env_key}={os.environ.get(env_key)}, TOOL_WHITELIST={os.environ.get('TOOL_WHITELIST')}"
    )
    logger.debug("Calling list_functions for Virustotal integration")
    tools_json = list_functions(env_key=env_key)
    logger.debug(f"list_functions returned: {tools_json}")
    tools = json.loads(tools_json)
    print(f"DEBUG: Raw tools_json output: {tools_json}")
    print(f"DEBUG: Parsed tools list: {tools}")
    print(f"DEBUG: Number of tools generated: {len(tools)}")

    # Verify tool creation with enhanced debug info on failure
    assert isinstance(tools, list), "list_functions returned invalid data (not a list)."
    assert len(tools) > 0, (
        f"No tools were generated from the VirusTotal specification. "
        f"VIRUSTOTAL_OPENAPI_URL: {VIRUSTOTAL_OPENAPI_URL}, "
        f"Spec keys: {list(spec.keys())}, "
        f"Paths: {list(spec.get('paths', {}).keys())}"
    )


def test_virustotal_ip_report(reset_env_and_module):
    """Tests the get_/ip_addresses/{ip_address} tool for VirusTotal v3."""
    env_key = reset_env_and_module
    api_key = os.getenv("VIRUSTOTAL_API_KEY")
    if not api_key:
        pytest.skip("VIRUSTOTAL_API_KEY not set in .env, skipping test.")
    setup_virustotal_env(env_key, api_key, VIRUSTOTAL_OPENAPI_URL)

    from mcp_openapi_proxy.server_fastmcp import call_function, list_functions
    from mcp_openapi_proxy.utils import normalize_tool_name

    tools_json = list_functions(env_key=env_key)
    tools = json.loads(tools_json)
    # Find the tool that matches the /ip_addresses/{ip_address} endpoint
    tool_name = None
    for tool in tools:
        operation_id = tool.get("operationId")
        path = tool.get("path")
        if (operation_id and operation_id.endswith("get_ip_report")) or (
            path and "/ip_addresses/{ip_address}" in path
        ):
            tool_name = tool["name"]
            break
    assert tool_name, "Could not find the correct tool for IP address report."
    parameters = {"ip_address": "8.8.8.8"}
    result_json = call_function(
        function_name=tool_name, parameters=parameters, env_key=env_key
    )
    logger.info(f"Result from {tool_name}: {result_json}")
    result = json.loads(result_json)
    assert isinstance(result, dict), f"Expected dict response, got {type(result)}"
    # In v3, we expect a 'data' property instead of 'response_code'
    if "data" not in result:
        print(
            f"DEBUG: VirusTotal response for {parameters['ip_address']}: {result_json}"
        )
    assert "data" in result, "Response missing 'data' key"
    # Optionally check that data contains attributes field
    assert "attributes" in result["data"], "Report data missing 'attributes'"


def test_virustotal_file_report(reset_env_and_module):
    """Tests the get_/file/report tool with a known hash."""
    env_key = reset_env_and_module
    api_key = os.getenv("VIRUSTOTAL_API_KEY")
    if not api_key:
        pytest.skip("VIRUSTOTAL_API_KEY not set in .env, skipping test.")
    setup_virustotal_env(env_key, api_key, VIRUSTOTAL_OPENAPI_URL)

    from mcp_openapi_proxy.server_fastmcp import call_function
    from mcp_openapi_proxy.utils import normalize_tool_name

    tool_name = normalize_tool_name("GET /file/report")
    # MD5 hash of an empty file - should exist and be benign
    file_hash = "d41d8cd98f00b204e9800998ecf8427e"
    parameters = {"resource": file_hash}

    logger.info(f"Calling tool '{tool_name}' with parameters: {parameters}")
    result_json = call_function(
        function_name=tool_name, parameters=parameters, env_key=env_key
    )
    logger.info(f"Result from {tool_name}: {result_json}")

    result = json.loads(result_json)
    assert isinstance(result, dict), f"Expected dict response, got {type(result)}"
    assert "response_code" in result, "Response missing 'response_code'"
    # Response code 1 means found, 0 means not found (or error)
    assert result["response_code"] in [
        0,
        1,
    ], f"Unexpected response_code: {result.get('response_code')}"
    if result["response_code"] == 1:
        assert (
            "scans" in result or "positives" in result
        ), "Missing expected report data (scans or positives)"
    else:
        logger.warning(
            f"File hash {file_hash} not found in VirusTotal (response_code 0). Test passes but indicates hash not present."
        )
