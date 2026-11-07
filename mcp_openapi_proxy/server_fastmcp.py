"""
Provides the FastMCP server logic for mcp-openapi-proxy.

This server exposes a pre-defined set of functions based on an OpenAPI specification.
Configuration is controlled via environment variables:
- OPENAPI_SPEC_URL_<hash>: Unique URL per test, falls back to OPENAPI_SPEC_URL.
- TOOL_WHITELIST: Comma-separated list of allowed endpoint paths.
- SERVER_URL_OVERRIDE: Optional override for the base URL from the OpenAPI spec.
- API_KEY: Generic token for Bearer header.
- STRIP_PARAM: Param name (e.g., "auth") to remove from parameters.
- EXTRA_HEADERS: Additional headers in 'Header: Value' format, one per line.
"""

import os
import json
import requests
import time
from mcp.server.mcpserver.exceptions import ToolError
from mcp_openapi_proxy.bounded_http import bounded_request, run_cancellable
from mcp_openapi_proxy.request_security import RedirectRefused
from mcp_openapi_proxy.privacy_diagnostics import log_http_event
from mcp_openapi_proxy.path_safety import (
    safe_url, validate_path_arguments, resolve_parameter_reference, resolve_parameter_schema)
from mcp_openapi_proxy.openapi import _spec_identity
from typing import Dict, Any, Optional
from mcp.server.mcpserver import MCPServer
from mcp_openapi_proxy.logging_setup import logger
from mcp import types as mcp_types
from mcp_openapi_proxy.openapi import (
    annotations_wire_dict,
    fetch_openapi_spec,
    build_base_url,
    handle_auth,
)
from mcp_openapi_proxy.utils import is_tool_whitelisted, normalize_tool_name, strip_parameters, get_additional_headers, deduplicate_tool_name
from mcp_openapi_proxy.protocol import (
    HEALTHZ_PATH,
    PACKAGE_VERSION,
    advertised_server_description,
    advertised_server_name,
    advertised_server_title,
    cache_hints,
    healthz_endpoint,
    json_response,
    mcp_host,
    mcp_path,
    mcp_port,
    request_state_security,
    transport_name,
    transport_security,
)
import sys

# Logger is now configured in logging_setup.py, just use it
# logger = setup_logging(debug=os.getenv("DEBUG", "").lower() in ("true", "1", "yes"))

logger.debug('Server CWD (details omitted)')

mcp = MCPServer(
    advertised_server_name(),
    version=PACKAGE_VERSION,
    title=advertised_server_title(),
    description=advertised_server_description(),
    cache_hints=cache_hints(),
    request_state_security=request_state_security(),
)
# Sibling Starlette route: process-local /healthz, no MCP lock (issue #66).
mcp.custom_route(HEALTHZ_PATH, methods=["GET"])(healthz_endpoint)

spec = None  # Global spec for resources

# Maps function names produced by list_functions to their operations, so that
# names deduplicated after TOOL_NAME_MAX_LENGTH truncation (issue #11) remain
# callable via call_function.
_FUNCTION_OPERATIONS: Dict[str, Dict] = {}
_SPEC_SNAPSHOTS: Dict[str, Dict] = {}
_OPERATION_SNAPSHOTS: Dict[str, Dict] = {}



# --- Native MCP prompts & resources for FastMCP/simple mode ---
# Previously simple mode advertised the prompts/resources capabilities (FastMCP
# does so automatically) but registered none, so prompts/list & resources/list
# came back EMPTY. Register them natively here for parity with the low-level
# server (same names/content): prompts summarize_spec + whimsical_blog, and the
# spec_file resource.

def _load_valid_spec(source_url):
    """Load only a real OpenAPI document; never synthesize a fallback."""
    try:
        result = fetch_openapi_spec(source_url)
        if isinstance(result, str):
            result = json.loads(result)
    except Exception:
        raise ToolError("OpenAPI specification unavailable or invalid") from None
    if not isinstance(result, dict) or not isinstance(result.get("paths"), dict):
        raise ToolError("OpenAPI specification unavailable or invalid")
    return result


def _identity(url, spec_data):
    """Use the shared spec identity, including the configured source URL."""
    return _spec_identity(spec_data, source_url=url)


def _spec_as_json() -> str:
    """Serialize the OpenAPI spec for the spec_file resource.

    Serves the in-memory spec that run_simple_server preloads once; only
    fetches as a lazy fallback. This avoids a live network re-fetch on every
    resources/read, respecting the live-first-once spec lifecycle (#28).
    Uses default=str so YAML datetime example values don't crash serialization.
    """
    global spec
    if spec is None:
        spec_url = os.environ.get("OPENAPI_SPEC_URL")
        if not spec_url:
            raise ToolError("OPENAPI_SPEC_URL is not configured")
        spec = _load_valid_spec(spec_url)
    if isinstance(spec, str):
        try:
            parsed_spec = json.loads(spec)
        except json.JSONDecodeError:
            raise ToolError("OpenAPI specification unavailable or invalid") from None
        if not isinstance(parsed_spec, dict) or not isinstance(parsed_spec.get("paths"), dict):
            raise ToolError("OpenAPI specification unavailable or invalid")
        return spec
    if not isinstance(spec, dict) or not isinstance(spec.get("paths"), dict):
        raise ToolError("OpenAPI specification unavailable or invalid")
    return json.dumps(spec, indent=2, default=str)


@mcp.resource("file:///openapi_spec.json", name="spec_file",
              description="The raw OpenAPI specification JSON", mime_type="application/json")
def _spec_file_resource() -> str:
    """Serve the configured OpenAPI spec as a native MCP resource."""
    return _spec_as_json()


@mcp.prompt(name="summarize_spec", description="Summarizes the OpenAPI specification")
def _summarize_spec_prompt() -> str:
    return ("This OpenAPI spec defines endpoints, parameters, and responses—a "
            "blueprint for developers to integrate effectively.")


@mcp.prompt(name="whimsical_blog", description="A whimsical WordPress blog-post starter inspired by this API")
def _whimsical_blog_prompt() -> str:
    return ("Once upon a JSON, in a land of tilde keys and sticky semicolons, a pet AI "
            "chatbot discovered it could whisper to WordPress through a magic OpenAPI proxy. "
            "✨ Write the next whimsical chapter.")


def register_fastmcp_env_prompt(raw: Optional[str] = None) -> None:
    """Register the PROMPT env prompt on the simple-mode server, if set.

    Built-ins are registered first, and FastMCP keeps the first prompt of a
    given name, so a colliding custom name is ignored here as well.
    """
    from mcp_openapi_proxy.prompt_env import BUILTIN_PROMPT_NAMES, parse_prompt_env

    parsed = parse_prompt_env(raw)
    if not parsed:
        return
    name = parsed["name"]
    if name in BUILTIN_PROMPT_NAMES:
        logger.error("Custom PROMPT uses a reserved built-in name; ignoring")
        return
    description = parsed["description"]
    messages = list(parsed["messages"])

    def _env_prompt() -> str:
        lines = [f"{item['role']}: {item['text']}" for item in messages]
        return "\n".join(lines) if lines else description

    _env_prompt.__doc__ = description
    mcp.prompt(name=name, description=description)(_env_prompt)
    logger.debug("Registered custom FastMCP prompt")


register_fastmcp_env_prompt()


def list_functions(*, env_key: str = "OPENAPI_SPEC_URL", _allow_fetch=True) -> str:
    """Lists available functions derived from the OpenAPI specification."""
    logger.debug("Executing list_functions tool.")
    spec_url = os.environ.get(env_key, os.environ.get("OPENAPI_SPEC_URL"))
    whitelist = os.getenv('TOOL_WHITELIST')
    logger.debug('Using spec_url (details omitted)')
    logger.debug('TOOL_WHITELIST value (details omitted)')
    if not spec_url:
        raise ToolError("OPENAPI_SPEC_URL is not configured")
    catalog_spec = (_load_valid_spec(spec_url) if _allow_fetch else _SPEC_SNAPSHOTS.get(spec_url))
    if catalog_spec is None:
        raise ToolError("OpenAPI specification unavailable or invalid; preload the configured catalog before serving")
    logger.debug('Raw spec loaded (details omitted)')
    paths = catalog_spec.get("paths", {})
    spec_identity = _identity(spec_url, catalog_spec)
    logger.debug('Paths extracted from spec (details omitted)')
    # Empty valid specs still expose the documented native resource/prompt helpers.
    functions = {}
    operations = {}
    for path, path_item in paths.items():
        logger.debug('Processing path (details omitted)')
        if not path_item:
            logger.debug('Path item is empty for (details omitted)')
            continue
        whitelist_env = os.getenv('TOOL_WHITELIST', '').strip()
        whitelist_check = is_tool_whitelisted(path)
        logger.debug('Whitelist check for (details omitted)')
        if whitelist_env and not whitelist_check:
            logger.debug('Path (details omitted)')
            continue
        for method, operation in path_item.items():
            logger.debug('Found method (details omitted)')
            if not method:
                logger.debug('Method is empty for (details omitted)')
                continue
            if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                logger.debug('Skipping unsupported method (details omitted)')
                continue
            raw_name = f"{method.upper()} {path}"
            function_name = normalize_tool_name(raw_name)
            if function_name in functions:
                # TOOL_NAME_MAX_LENGTH truncation can make distinct operations
                # collide; rename instead of silently dropping (issue #11).
                function_name = deduplicate_tool_name(function_name, functions)
            function_description = operation.get("summary", operation.get("description", "No description provided."))
            logger.debug('Registering function (details omitted)')
            input_schema = {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False
            }
            placeholder_params = [part.strip('{}') for part in path.split('/') if '{' in part and '}' in part]
            for param_name in placeholder_params:
                input_schema['properties'][param_name] = {
                    "type": "string",
                    "description": f"Path parameter {param_name}"
                }
                input_schema['required'].append(param_name)
            path_parameters = path_item.get("parameters", [])
            operation_parameters = operation.get("parameters", [])
            if not isinstance(path_parameters, list) or not isinstance(operation_parameters, list):
                logger.error("Invalid OpenAPI parameter list for operation")
                continue
            resolved_parameters = {}
            try:
                for declaration in path_parameters + operation_parameters:
                    param = resolve_parameter_reference(declaration, catalog_spec)
                    if param.get("name"):
                        resolved_parameters[param["name"]] = param
                resolved_schemas = {
                    name: resolve_parameter_schema(param, catalog_spec)
                    for name, param in resolved_parameters.items()
                }
            except (ValueError, TypeError):
                logger.error("Skipping operation with unresolved parameter schema")
                continue
            for param_name, param in resolved_parameters.items():
                param_schema = resolved_schemas[param_name]
                param_type = param_schema.get("type", param.get("type", "string"))
                if param_type not in ["string", "integer", "boolean", "number", "array"]:
                    param_type = "string"
                prop = {
                    "type": param_type,
                    "description": param.get("description", f"{param.get('in', 'unknown')} parameter {param_name}")
                }
                if param_schema.get("format"):
                    prop["format"] = param_schema["format"]
                if "enum" in param_schema:
                    prop["enum"] = param_schema["enum"]
                if param_type == "array":
                    # Arrays must carry an items schema (required by JSON Schema
                    # consumers such as the OpenAI API); fall back to string items.
                    items_schema = param_schema.get("items", param.get("items"))
                    if not isinstance(items_schema, dict) or not items_schema:
                        items_schema = {"type": "string"}
                    prop["items"] = items_schema
                input_schema["properties"][param_name] = prop
                if param.get("required", False) and param_name not in input_schema['required']:
                    input_schema["required"].append(param_name)
            functions[function_name] = {
                "name": function_name,
                "description": function_description,
                "path": path,
                "method": method.upper(),
                "operationId": operation.get("operationId"),
                "original_name": raw_name,
                "inputSchema": input_schema
            }
            operations[function_name] = {
                "path": path,
                "method": method.upper(),
                "operation": operation,
                "spec_identity": spec_identity
            }
    functions["list_resources"] = {
        "name": "list_resources",
        "description": "List available resources",
        "path": None,
        "method": None,
        "operationId": None,
        "original_name": "list_resources",
        "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    }
    functions["read_resource"] = {
        "name": "read_resource",
        "description": "Read a resource by URI",
        "path": None,
        "method": None,
        "operationId": None,
        "original_name": "read_resource",
        "inputSchema": {"type": "object", "properties": {"uri": {"type": "string", "description": "Resource URI"}}, "required": ["uri"], "additionalProperties": False}
    }
    functions["list_prompts"] = {
        "name": "list_prompts",
        "description": "List available prompts",
        "path": None,
        "method": None,
        "operationId": None,
        "original_name": "list_prompts",
        "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    }
    functions["get_prompt"] = {
        "name": "get_prompt",
        "description": "Get a prompt by name",
        "path": None,
        "method": None,
        "operationId": None,
        "original_name": "get_prompt",
        "inputSchema": {"type": "object", "properties": {"name": {"type": "string", "description": "Prompt name"}}, "required": ["name"], "additionalProperties": False}
    }
    logger.debug('Discovered (details omitted)')
    logger.debug('Functions list (details omitted)')
    global spec, _FUNCTION_OPERATIONS
    if spec_url == os.environ.get("OPENAPI_SPEC_URL"):
        spec = catalog_spec
    _SPEC_SNAPSHOTS[spec_url] = catalog_spec
    _FUNCTION_OPERATIONS = operations
    _OPERATION_SNAPSHOTS[spec_url] = operations
    for item in functions.values():
        item["handle"] = item["name"]
        registered = operations.get(item["name"])
        item["annotations"] = (
            annotations_wire_dict(item["method"], item["name"], registered["operation"])
            if registered else annotations_wire_dict(None, item["name"], read_only=True)
        )

    return json.dumps(list(functions.values()), indent=2)

def call_function(*, function_name: str = "", parameters: Optional[Dict] = None, env_key: str = "OPENAPI_SPEC_URL", handle: str = "", _cancel=None) -> str:
    """Calls a function derived from the OpenAPI specification."""
    function_name = function_name or handle
    logger.debug('call_function invoked with function_name (details omitted)')
    logger.debug('API_KEY (details omitted)')
    logger.debug('STRIP_PARAM (details omitted)')
    if not function_name:
        logger.error("function_name is empty or None")
        raise ToolError("function_name is required")

    # These native helpers return fixed MCP metadata and do not depend on the
    # external OpenAPI document. Keep them available if the spec source drops.
    if function_name == "list_resources":
        return json.dumps([{"name": "spec_file", "uri": "file:///openapi_spec.json", "description": "The raw OpenAPI specification JSON"}])
    if function_name == "list_prompts":
        return json.dumps([{"name": "summarize_spec", "description": "Summarizes the purpose of the OpenAPI specification", "arguments": []}])
    if function_name == "get_prompt":
        if not parameters or "name" not in parameters:
            raise ToolError("name parameter required")
        if parameters["name"] != "summarize_spec":
            raise ToolError("Prompt not found")
        return json.dumps([{"role": "assistant", "content": {"type": "text", "text": "This OpenAPI spec defines an API’s endpoints, parameters, and responses, making it a blueprint for devs to build and integrate stuff without messing it up."}}])
    if function_name == "read_resource":
        if not parameters or "uri" not in parameters:
            raise ToolError("uri parameter required")
        if parameters["uri"] != "file:///openapi_spec.json":
            raise ToolError("Resource not found")

    spec_url = os.environ.get(env_key, os.environ.get("OPENAPI_SPEC_URL"))
    if not spec_url:
        logger.error("No OPENAPI_SPEC_URL or custom env_key configured.")
        raise ToolError("OPENAPI_SPEC_URL is not configured")
    if _cancel is None:
        list_functions(env_key=env_key)
    call_spec = _SPEC_SNAPSHOTS.get(spec_url)
    operation_map = _OPERATION_SNAPSHOTS.get(spec_url, {})
    if call_spec is None:
        if function_name in operation_map:
            raise ToolError("Stale or cross-spec operation registration")
        raise ToolError("OpenAPI specification unavailable or invalid; call list_functions first")
    if function_name == "read_resource":
        # default=str: YAML datetime example values aren't JSON-serializable
        return json.dumps(call_spec, indent=2, default=str)
    logger.debug('Spec keys for call_function (details omitted)')
    # A registered name belongs only to the exact source URL and document
    # that produced the catalog.
    spec_identity = _identity(spec_url, call_spec)
    registered = operation_map.get(function_name)
    if registered and registered.get("spec_identity") != spec_identity:
        logger.error("Stale or cross-spec operation registration rejected")
        raise ToolError("Stale or cross-spec operation registration")
    function_def = dict(registered) if registered else None
    paths = call_spec.get("paths", {})
    logger.debug('Paths for function lookup (details omitted)')

    for path, path_item in paths.items():
        if function_def:
            break
        logger.debug('Checking path (details omitted)')
        for method, operation in path_item.items():
            logger.debug('Checking method (details omitted)')
            if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                logger.debug('Skipping unsupported method (details omitted)')
                continue
            raw_name = f"{method.upper()} {path}"
            current_function_name = normalize_tool_name(raw_name)
            logger.debug('Comparing (details omitted)')
            if current_function_name == function_name:
                function_def = {
                    "path": path,
                    "method": method.upper(),
                    "operation": operation
                }
                logger.debug('Matched function definition for (details omitted)')
                break
        if function_def:
            break
    if not function_def:
        raise ToolError("Unknown OpenAPI operation")
    logger.debug('Function def found (details omitted)')

    operation = dict(function_def["operation"])
    operation["method"] = function_def["method"]
    headers = handle_auth(operation)
    additional_headers = get_additional_headers()
    headers = {**headers, **additional_headers}
    if parameters is None:
        parameters = {}
    parameters = strip_parameters(parameters)
    logger.debug('Parameters after strip (details omitted)')
    if function_def["method"] != "GET":
        headers["Content-Type"] = "application/json"

    if not is_tool_whitelisted(function_def["path"]):
        logger.error('Access to function (details omitted)')
        raise ToolError("Operation not authorized")

    base_url = build_base_url(call_spec)
    if not base_url:
        logger.error("Failed to construct base URL from spec or SERVER_URL_OVERRIDE.")
        raise ToolError("No base URL defined in spec or SERVER_URL_OVERRIDE")

    path = function_def["path"]
    path_item = call_spec.get("paths", {}).get(path, {})
    try:
        verified = validate_path_arguments(path, parameters, operation, path_item, call_spec)
        api_url, used_path_parameters = safe_url(base_url, path, verified)
    except (ValueError, TypeError):
        raise ToolError("Invalid or unsafe path parameters")
    for key in used_path_parameters:
        parameters.pop(key, None)

    request_params = {}
    request_body = None

    if isinstance(parameters, dict):
        if "stream" in parameters and parameters["stream"]:
            del parameters["stream"]
        if function_def["method"] == "GET":
            request_params = parameters
        else:
            request_body = parameters
    else:
        parameters = {}
        logger.debug("No valid parameters provided, proceeding without params/body")

    logger.debug('Sending request - Method (details omitted)')
    try:
        # Add SSL verification control for API calls using IGNORE_SSL_TOOLS
        ignore_ssl_tools = os.getenv("IGNORE_SSL_TOOLS", "false").lower() in ("true", "1", "yes")
        verify_ssl_tools = not ignore_ssl_tools
        logger.debug('Sending API request with SSL verification (details omitted)')
        if not is_tool_whitelisted(function_def["path"]):
            logger.error("OpenAPI operation no longer authorized")
            raise ToolError("OpenAPI operation no longer authorized")
        request_started = time.monotonic()
        log_http_event("sending", method=function_def["method"])
        response = bounded_request(
            _cancel=_cancel,
            method=function_def["method"],
            url=api_url,
            headers=headers,
            params=request_params if function_def["method"] == "GET" else None,
            json=request_body if function_def["method"] != "GET" else None,
            verify=verify_ssl_tools
        )
        response.raise_for_status()
        log_http_event("completed", method=function_def["method"],
                       status=getattr(response, "status_code", None),
                       started=request_started)
        logger.debug('API response received (details omitted)')
        return response.text
    except requests.exceptions.RequestException as e:
        logger.error('API request failed (details omitted)')
        raise ToolError(("Upstream redirect refused" if isinstance(e, RedirectRefused) else "Upstream request failed"))

@mcp.tool(name="list_functions", title="List Functions",
          annotations=mcp_types.ToolAnnotations(title="List Functions", read_only_hint=True, idempotent_hint=True))
async def list_functions_tool(*, env_key: str = "OPENAPI_SPEC_URL") -> str:
    """List operations from the configured catalog without remote runtime fetches."""
    return list_functions(env_key=env_key, _allow_fetch=False)


@mcp.tool(name="call_function", title="Call Function",
          annotations=mcp_types.ToolAnnotations(title="Call Function", destructive_hint=True))
async def call_function_tool(*, function_name: str = "", parameters: Optional[Dict] = None,
                             env_key: str = "OPENAPI_SPEC_URL", handle: str = "") -> str:
    """Call an OpenAPI operation by function_name or its stateless handle."""
    return await run_cancellable(call_function, function_name=function_name,
                                 parameters=parameters, env_key=env_key, handle=handle)


def run_simple_server():
    """Runs the FastMCP server."""
    logger.debug("Starting run_simple_server")
    spec_url = os.environ.get("OPENAPI_SPEC_URL")
    if not spec_url:
        logger.error("OPENAPI_SPEC_URL environment variable is required for FastMCP mode.")
        sys.exit(1)
    assert isinstance(spec_url, str)

    logger.debug("Preloading functions from OpenAPI spec...")
    global spec
    spec = fetch_openapi_spec(spec_url)
    if spec is None:
        logger.error("Failed to fetch OpenAPI spec, no functions to preload.")
        sys.exit(1)
    for key in sorted(os.environ):
        if key == "OPENAPI_SPEC_URL" or key.startswith("OPENAPI_SPEC_URL_"):
            list_functions(env_key=key)

    try:
        selected = transport_name()
        logger.debug('Starting MCP server (MCPServer/simple mode) transport (details omitted)')
        if selected == "streamable-http":
            mcp.run(
                transport="streamable-http",
                host=mcp_host(),
                port=mcp_port(),
                streamable_http_path=mcp_path(),
                json_response=json_response(),
                stateless_http=True,
                transport_security=transport_security(),
            )
        else:
            mcp.run(transport="stdio")
    except Exception as e:
        logger.error('Unhandled exception in MCP server (FastMCP) (details omitted)')
        sys.exit(1)

from mcp_openapi_proxy.sdk_privacy import install_mcpserver_guards
install_mcpserver_guards(mcp)

if __name__ == "__main__":
    run_simple_server()
