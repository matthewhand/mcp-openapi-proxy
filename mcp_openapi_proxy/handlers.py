"""
MCP request handlers for mcp-openapi-proxy.
"""

import os
import json
from typing import Any, Dict, List, Union
from types import SimpleNamespace

import requests
from mcp import types
from mcp_openapi_proxy.logging_setup import logger
from mcp_openapi_proxy.protocol import unpack_handler_args
from mcp_openapi_proxy.utils import (
    normalize_tool_name,
    is_tool_whitelisted,
    strip_parameters,
    detect_response_type,
    get_additional_headers,
)
from mcp_openapi_proxy.openapi import (
    fetch_openapi_spec,
    build_base_url,
    handle_auth,
    register_functions,
    lookup_operation_details,
)

# Global variables used by handlers
tools: List[types.Tool] = []
resources: List[types.Resource] = []
prompts: List[types.Prompt] = []
openapi_spec_data = None


async def dispatcher_handler(ctx_or_request: Any, params: Any = None) -> Any:
    """
    Dispatcher handler that routes CallToolRequest to the appropriate function (tool).
    """
    global openapi_spec_data
    _, params = unpack_handler_args(ctx_or_request, params)
    try:
        function_name = params.name
        logger.debug(f"Dispatcher received CallToolRequest for function: {function_name}")
        api_key = os.getenv("API_KEY")
        logger.debug(f"API_KEY: {api_key[:5] + '...' if api_key else '<not set>'}")
        logger.debug(f"STRIP_PARAM: {os.getenv('STRIP_PARAM', '<not set>')}")
        tool = next((t for t in tools if t.name == function_name), None)
        if not tool:
            logger.error(f"Unknown function requested: {function_name}")
            result = types.CallToolResult(
                content=[types.TextContent(type="text", text="Unknown function requested")],
                is_error=False,
            )
            return result
        arguments = params.arguments or {}
        logger.debug(f"Raw arguments before processing: {arguments}")

        if openapi_spec_data is None:
            result = types.CallToolResult(
                content=[types.TextContent(type="text", text="OpenAPI spec not loaded")],
                is_error=True,
            )
            return result
        operation_details = lookup_operation_details(function_name, openapi_spec_data)
        if not operation_details:
            logger.error(f"Could not find OpenAPI operation for function: {function_name}")
            result = types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Could not find OpenAPI operation for function: {function_name}")],
                is_error=False,
            )
            return result

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
            result = types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Missing parameter: {e}")],
                is_error=False,
            )
            return result

        base_url = build_base_url(openapi_spec_data)
        if not base_url:
            logger.critical("Failed to construct base URL from spec or SERVER_URL_OVERRIDE.")
            result = types.CallToolResult(
                content=[types.TextContent(type="text", text="No base URL defined in spec or SERVER_URL_OVERRIDE")],
                is_error=False,
            )
            return result

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
                    result = types.CallToolResult(
                        content=[types.TextContent(type="text", text=f"Missing required path parameters: {missing_required}")],
                        is_error=False,
                    )
                    return result
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
            final_content = [content]
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            result = types.CallToolResult(
                content=[types.TextContent(type="text", text=str(e))],
                is_error=False,
            )
            return result

        logger.debug(f"Response content type: {content.type}")
        logger.debug(f"Response sent to client: {content.text}")
        result = types.CallToolResult(content=final_content, is_error=False)
        return result
    except Exception as e:
        logger.error(f"Unhandled exception in dispatcher_handler: {e}", exc_info=True)
        result = types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Internal error: {str(e)}")],
            is_error=False,
        )
        return result


async def list_tools(ctx_or_request: Any = None, params: Any = None) -> Any:
    """Return a list of registered tools."""
    logger.debug("Handling list_tools request - start")
    logger.debug(f"Tools list length: {len(tools)}")
    result = types.ListToolsResult(tools=tools)
    return result


async def list_resources(ctx_or_request: Any = None, params: Any = None) -> Any:
    """Return a list of registered resources."""
    logger.debug("Handling list_resources request")
    if not resources:
        logger.debug("Populating resources as none exist")
        resources.clear()
        resources.append(
            types.Resource(
                name="spec_file",
                uri="file:///openapi_spec.json",
                description="The raw OpenAPI specification JSON",
            )
        )
    logger.debug(f"Resources list length: {len(resources)}")
    result = types.ListResourcesResult(resources=resources)
    return result


async def read_resource(ctx_or_request: Any, params: Any = None) -> Any:
    """Read a specific resource identified by its URI."""
    _, params = unpack_handler_args(ctx_or_request, params)
    uri_str = str(params.uri)
    logger.debug(f"START read_resource for URI: {uri_str}")
    try:
        global openapi_spec_data
        spec_data = openapi_spec_data

        if not spec_data:
            openapi_url = os.getenv("OPENAPI_SPEC_URL")
            logger.debug(f"Got OPENAPI_SPEC_URL: {openapi_url}")
            if not openapi_url:
                logger.error("OPENAPI_SPEC_URL not set and no spec data loaded")
                result = types.ReadResourceResult(
                    contents=[
                        types.TextResourceContents(
                            text="Spec unavailable: OPENAPI_SPEC_URL not set and no spec data loaded",
                            uri=uri_str,
                        )
                    ]
                )
                return result
            logger.debug("Fetching spec...")
            spec_data = fetch_openapi_spec(openapi_url)
        else:
            logger.debug("Using pre-loaded openapi_spec_data for read_resource")

        logger.debug(f"Spec fetched: {spec_data is not None}")
        if not spec_data:
            logger.error("Failed to fetch OpenAPI spec")
            result = types.ReadResourceResult(
                contents=[
                    types.TextResourceContents(
                        text="Spec data unavailable after fetch attempt",
                        uri=uri_str,
                    )
                ]
            )
            return result
        logger.debug("Dumping spec to JSON...")
        spec_json = json.dumps(spec_data, indent=2)
        logger.debug(f"Forcing spec JSON return: {spec_json[:50]}...")
        result_data = types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    text=spec_json,
                    uri="file:///openapi_spec.json",
                    mime_type="application/json"
                )
            ]
        )
        logger.debug("Returning result from read_resource")
        return result_data
    except Exception as e:
        logger.error(f"Error forcing resource: {e}", exc_info=True)
        result = types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    text=f"Resource error: {str(e)}", uri=uri_str
                )
            ]
        )
        return result


async def list_prompts(ctx_or_request: Any = None, params: Any = None) -> Any:
    """Return a list of registered prompts."""
    logger.debug("Handling list_prompts request")
    logger.debug(f"Prompts list length: {len(prompts)}")
    result = types.ListPromptsResult(prompts=prompts)
    return result


async def get_prompt(ctx_or_request: Any, params: Any = None) -> Any:
    """Return a specific prompt by name."""
    _, params = unpack_handler_args(ctx_or_request, params)
    name = params.name
    logger.debug(f"Handling get_prompt request for {name}")
    prompt = next((p for p in prompts if p.name == name), None)
    if not prompt:
        logger.error(f"Prompt '{name}' not found")
        result = types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(type="text", text="Prompt not found"),
                )
            ]
        )
        return result
    try:
        default_text = (
            "This OpenAPI spec defines endpoints, parameters, and responses—a blueprint for developers to integrate effectively."
        )
        result = types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(type="text", text=default_text),
                )
            ]
        )
        return result
    except Exception as e:
        logger.error(f"Error generating prompt: {e}", exc_info=True)
        result = types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(type="text", text=f"Prompt error: {str(e)}"),
                )
            ]
        )
        return result