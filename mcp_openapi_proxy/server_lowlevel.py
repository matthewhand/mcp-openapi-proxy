"""
Low-Level Server for mcp-openapi-proxy.

This server dynamically registers functions (tools) based on an OpenAPI specification,
directly utilizing the spec for tool definitions and invocation.
Configuration is controlled via environment variables:
- OPENAPI_SPEC_URL: URL to the OpenAPI specification.
- TOOL_WHITELIST: Comma-separated list of allowed endpoint paths.
- SERVER_URL_OVERRIDE: Optional override for the base URL from the OpenAPI spec.
- API_KEY: Generic token for Bearer header.
- STRIP_PARAM: Param name (e.g., "auth") to remove from parameters.
- EXTRA_HEADERS: Additional headers in 'Header: Value' format, one per line.
- CAPABILITIES_TOOLS: Set to "true" to enable tools advertising (default: false).
- CAPABILITIES_RESOURCES: Set to "true" to enable resources advertising (default: false).
- CAPABILITIES_PROMPTS: Set to "true" to enable prompts advertising (default: false).
- ENABLE_TOOLS: Set to "false" to disable tools functionality (default: true).
- ENABLE_RESOURCES: Set to "true" to enable resources functionality (default: false).
- ENABLE_PROMPTS: Set to "true" to enable prompts functionality (default: false).
"""

import os
import sys
import asyncio
import json
import requests
from typing import List, Dict, Any, Optional, cast
import anyio
from pydantic import AnyUrl

from mcp import types
from urllib.parse import unquote
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp_openapi_proxy.utils import (
    setup_logging,
    normalize_tool_name,
    is_tool_whitelisted,
    fetch_openapi_spec,
    build_base_url,
    handle_auth,
    strip_parameters,
    detect_response_type,
    get_additional_headers
)

DEBUG = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
logger = setup_logging(debug=DEBUG)

tools: List[types.Tool] = []
# Check capability advertisement envvars (off by default)
CAPABILITIES_TOOLS = os.getenv("CAPABILITIES_TOOLS", "false").lower() == "true"
CAPABILITIES_RESOURCES = os.getenv("CAPABILITIES_RESOURCES", "false").lower() == "true"
CAPABILITIES_PROMPTS = os.getenv("CAPABILITIES_PROMPTS", "false").lower() == "true"

# Check feature enablement envvars (tools on, others off by default)
ENABLE_TOOLS = os.getenv("ENABLE_TOOLS", "true").lower() == "true"
ENABLE_RESOURCES = os.getenv("ENABLE_RESOURCES", "false").lower() == "true"
ENABLE_PROMPTS = os.getenv("ENABLE_PROMPTS", "false").lower() == "true"

resources: List[types.Resource] = []
prompts: List[types.Prompt] = []

if ENABLE_RESOURCES:
    resources.append(
        types.Resource(
            name="spec_file",
            uri=AnyUrl("file:///openapi_spec.json"),
            description="The raw OpenAPI specification JSON"
        )
    )

if ENABLE_PROMPTS:
    prompts.append(
        types.Prompt(
            name="summarize_spec",
            description="Summarizes the OpenAPI specification",
            arguments=[],
            messages=lambda args: [
                {"role": "assistant", "content": {"text": "This OpenAPI spec defines endpoints, parameters, and responses—a blueprint for developers to integrate effectively."}}
            ]
        )
    )

openapi_spec_data: Optional[Dict[str, Any]] = None

mcp = Server("OpenApiProxy-LowLevel")

async def dispatcher_handler(request: types.CallToolRequest) -> types.CallToolResult:
    """
    Dispatcher handler that routes CallToolRequest to the appropriate function (tool).
    """
    global openapi_spec_data
    try:
        function_name = request.params.name
        logger.debug(f"Dispatcher received CallToolRequest for function: {function_name}")
        logger.debug(f"API_KEY: {os.getenv('API_KEY', '<not set>')[:5] + '...' if os.getenv('API_KEY') else '<not set>'}")
        logger.debug(f"STRIP_PARAM: {os.getenv('STRIP_PARAM', '<not set>')}")
        tool = next((t for t in tools if t.name == function_name), None)
        if not tool:
            logger.error(f"Unknown function requested: {function_name}")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="Unknown function requested")],
                isError=False,
            )
        arguments = request.params.arguments or {}
        logger.debug(f"Raw arguments before processing: {arguments}")

        if openapi_spec_data is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="OpenAPI spec not loaded")],
                isError=True,
            )
        # Since we've checked openapi_spec_data is not None, cast it to Dict.
        operation_details = lookup_operation_details(function_name, cast(Dict, openapi_spec_data))
        if not operation_details:
            logger.error(f"Could not find OpenAPI operation for function: {function_name}")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Could not find OpenAPI operation for function: {function_name}")],
                isError=False,
            )

        operation = operation_details["operation"]
        operation["method"] = operation_details["method"]
        headers = handle_auth(operation)
        additional_headers = get_additional_headers()
        headers = {**headers, **additional_headers}
        parameters = dict(strip_parameters(arguments))
        method = operation_details["method"]
        if method != "GET":
            headers["Content-Type"] = "application/json"

        path = operation_details["path"]
        try:
            path = path.format(**parameters)
            logger.debug(f"Substituted path using format(): {path}")
            if method == "GET":
                placeholder_keys = [
                    seg.strip("{}")
                    for seg in operation_details["original_path"].split("/")
                    if seg.startswith("{") and seg.endswith("}")
                ]
                for key in placeholder_keys:
                    parameters.pop(key, None)
        except KeyError as e:
            logger.error(f"Missing parameter for substitution: {e}")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Missing parameter: {e}")],
                isError=False,
            )

        base_url = build_base_url(cast(Dict, openapi_spec_data))
        if not base_url:
            logger.critical("Failed to construct base URL from spec or SERVER_URL_OVERRIDE.")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="No base URL defined in spec or SERVER_URL_OVERRIDE")],
                isError=False,
            )

        api_url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        request_params = {}
        request_body = None
        if isinstance(parameters, dict):
            merged_params = []
            path_item = openapi_spec_data.get("paths", {}).get(operation_details["original_path"], {})
            if isinstance(path_item, dict) and "parameters" in path_item:
                merged_params.extend(path_item["parameters"])
            if "parameters" in operation:
                merged_params.extend(operation["parameters"])
            path_params_in_openapi = [param["name"] for param in merged_params if param.get("in") == "path"]
            if path_params_in_openapi:
                missing_required = [
                    param["name"]
                    for param in merged_params
                    if param.get("in") == "path" and param.get("required", False) and param["name"] not in arguments
                ]
                if missing_required:
                    logger.error(f"Missing required path parameters: {missing_required}")
                    return types.CallToolResult(
                        content=[types.TextContent(type="text", text=f"Missing required path parameters: {missing_required}")],
                        isError=False,
                    )
            if method == "GET":
                request_params = parameters
            else:
                request_body = parameters
        else:
            logger.debug("No valid parameters provided, proceeding without params/body")

        logger.debug(f"API Request - URL: {api_url}, Method: {method}")
        logger.debug(f"Headers: {headers}")
        logger.debug(f"Query Params: {request_params}")
        logger.debug(f"Request Body: {request_body}")

        try:
            ignore_ssl_tools = os.getenv("IGNORE_SSL_TOOLS", "false").lower() in ("true", "1", "yes")
            verify_ssl_tools = not ignore_ssl_tools
            logger.debug(f"Sending API request with SSL verification: {verify_ssl_tools} (IGNORE_SSL_TOOLS={ignore_ssl_tools})")
            response = requests.request(
                method=method,
                url=api_url,
                headers=headers,
                params=request_params if method == "GET" else None,
                json=request_body if method != "GET" else None,
                verify=verify_ssl_tools,
            )
            response.raise_for_status()
            response_text = (response.text or "No response body").strip()
            content, log_message = detect_response_type(response_text)
            logger.debug(log_message)
            # Expect content to be of a type that can be included as is.
            final_content = [content]
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                isError=False,
            )
        logger.debug(f"Response content type: {content.type}")
        logger.debug(f"Response sent to client: {content.text}")
        return types.CallToolResult(content=final_content, isError=False)
    except Exception as e:
        logger.error(f"Unhandled exception in dispatcher_handler: {e}", exc_info=True)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Internal error: {str(e)}")],
            isError=False,
        )


async def list_tools(request: types.ListToolsRequest) -> types.ListToolsResult:
    logger.debug("Handling list_tools request - start")
    logger.debug(f"Tools list length: {len(tools)}")
    return types.ListToolsResult(tools=tools)

async def list_resources(request: types.ListResourcesRequest) -> types.ListResourcesResult:
    logger.debug("Handling list_resources request")
    from pydantic import AnyUrl
    from types import SimpleNamespace
    if not resources:
        logger.debug("Resources empty; populating default resource")
        resources.append(
            types.Resource(
                name="spec_file",
                uri=AnyUrl("file:///openapi_spec.json"),
                description="The raw OpenAPI specification JSON"
            )
        )
    logger.debug(f"Resources list length: {len(resources)}")
    class ResourcesHolder:
        pass
    result = ResourcesHolder()
    result.resources = resources
    return result


async def read_resource(request: types.ReadResourceRequest) -> types.ReadResourceResult:
    logger.debug(f"START read_resource for URI: {request.params.uri}")
    try:
        openapi_url = os.getenv("OPENAPI_SPEC_URL")
        logger.debug(f"Got OPENAPI_SPEC_URL: {openapi_url}")
        if not openapi_url:
            logger.error("OPENAPI_SPEC_URL not set")
            return types.ReadResourceResult(
                contents=[
                    types.TextResourceContents(
                        uri=request.params.uri,
                        text="Spec unavailable: OPENAPI_SPEC_URL not set"
                    )
                ]
            )
        logger.debug("Fetching spec...")
        spec_data = fetch_openapi_spec(openapi_url)
        logger.debug(f"Spec fetched: {spec_data is not None}")
        if not spec_data:
            logger.error("Failed to fetch OpenAPI spec")
            return types.ReadResourceResult(
                contents=[
                    types.TextResourceContents(
                        uri=request.params.uri,
                        text="Spec data unavailable after fetch attempt"
                    )
                ]
            )
        logger.debug("Dumping spec to JSON...")
        spec_json = json.dumps(spec_data, indent=2)
        logger.debug(f"Forcing spec JSON return: {spec_json[:50]}...")
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri="file:///openapi_spec.json",
                    text=spec_json,
                    mimeType="application/json"
                )
            ]
        )
    except Exception as e:
        logger.error(f"Error forcing resource: {e}", exc_info=True)
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=request.params.uri,
                    text=f"Resource error: {str(e)}"
                )
            ]
        )


async def list_prompts(request: types.ListPromptsRequest) -> types.ListPromptsResult:
    logger.debug("Handling list_prompts request")
    logger.debug(f"Prompts list length: {len(prompts)}")
    return types.ListPromptsResult(prompts=prompts)


async def get_prompt(request: types.GetPromptRequest) -> types.GetPromptResult:
    logger.debug(f"Handling get_prompt request for {request.params.name}")
    prompt = next((p for p in prompts if p.name == request.params.name), None)
    if not prompt:
        logger.error(f"Prompt '{request.params.name}' not found")
        return types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="system",
                    content={"text": "Prompt not found"}
                )
            ]
        )
    try:
        messages = prompt.messages(request.params.arguments or {})
        logger.debug(f"Generated messages: {messages}")
        return types.GetPromptResult(messages=messages)
    except Exception as e:
        logger.error(f"Error generating prompt: {e}", exc_info=True)
        return types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="system",
                    content={"text": f"Prompt error: {str(e)}"}
                )
            ]
        )


def lookup_operation_details(function_name: str, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not spec or 'paths' not in spec:
        return None
    for path, path_item in spec['paths'].items():
        for method, operation in path_item.items():
            if method.lower() not in ['get', 'post', 'put', 'delete', 'patch']:
                continue
            raw_name = f"{method.upper()} {path}"
            current_function_name = normalize_tool_name(raw_name)
            if current_function_name == function_name:
                return {"path": path, "method": method.upper(), "operation": operation, "original_path": path}
    return None


async def start_server():
    logger.debug("Starting Low-Level MCP server...")
    async with stdio_server() as (read_stream, write_stream):
        while True:
            try:
                capabilities = types.ServerCapabilities(
                    tools=types.ToolsCapability(listChanged=True) if CAPABILITIES_TOOLS else None,
                    prompts=types.PromptsCapability(listChanged=True) if CAPABILITIES_PROMPTS else None,
                    resources=types.ResourcesCapability(listChanged=True) if CAPABILITIES_RESOURCES else None
                )
                await mcp.run(
                    read_stream,
                    write_stream,
                    initialization_options=InitializationOptions(
                        server_name="AnyOpenAPIMCP-LowLevel",
                        server_version="0.1.0",
                        capabilities=capabilities,
                    ),
                )
            except Exception as e:
                logger.error(f"MCP run crashed: {e}", exc_info=True)
                await anyio.sleep(1)


def run_server():
    global openapi_spec_data
    try:
        openapi_url = os.getenv('OPENAPI_SPEC_URL')
        if not openapi_url:
            logger.critical("OPENAPI_SPEC_URL environment variable is required but not set.")
            sys.exit(1)
        openapi_spec_data = fetch_openapi_spec(openapi_url)
        if not openapi_spec_data:
            logger.critical("Failed to fetch or parse OpenAPI specification from OPENAPI_SPEC_URL.")
            sys.exit(1)
        logger.debug("OpenAPI specification fetched successfully.")
        if ENABLE_TOOLS:
            from mcp_openapi_proxy.handlers import register_functions
            register_functions(openapi_spec_data)
        logger.debug(f"Tools after registration: {[tool.name for tool in tools]}")
        if ENABLE_TOOLS and not tools:
            logger.critical("No valid tools registered. Shutting down.")
            sys.exit(1)
        if ENABLE_TOOLS:
            mcp.request_handlers[types.ListToolsRequest] = list_tools
            mcp.request_handlers[types.CallToolRequest] = dispatcher_handler
        if ENABLE_RESOURCES:
            mcp.request_handlers[types.ListResourcesRequest] = list_resources
            mcp.request_handlers[types.ReadResourceRequest] = read_resource
        if ENABLE_PROMPTS:
            mcp.request_handlers[types.ListPromptsRequest] = list_prompts
            mcp.request_handlers[types.GetPromptRequest] = get_prompt
        logger.debug("Handlers registered based on capabilities and enablement envvars.")
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.debug("MCP server shutdown initiated by user.")
    except Exception as e:
        logger.critical(f"Failed to start MCP server: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run_server()
