"""
MCP request handlers for mcp-openapi-proxy.
"""

import os
import json
from typing import Any, Dict, List, Union
from types import SimpleNamespace

import requests
import time
from mcp_openapi_proxy.bounded_http import bounded_request_async
from mcp_openapi_proxy.request_security import RedirectRefused
from mcp_openapi_proxy.privacy_diagnostics import log_http_event
from mcp_openapi_proxy.path_safety import safe_url, validate_path_arguments
from mcp import types as mcp_types
types = mcp_types
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
    try:
        _, params = unpack_handler_args(ctx_or_request, params)
        function_name = params.name
        logger.debug('Dispatcher received CallToolRequest for function (details omitted)')
        api_key = os.getenv("API_KEY")
        logger.debug('API_KEY (details omitted)')
        logger.debug('STRIP_PARAM (details omitted)')
        tool = next((t for t in tools if t.name == function_name), None)
        if not tool:
            logger.error('Unknown function requested (details omitted)')
            result = mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Unknown function requested")],
                is_error=True,
            )
            return result
        arguments = params.arguments or {}
        logger.debug('Raw arguments before processing (details omitted)')

        if openapi_spec_data is None:
            result = mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="OpenAPI spec not loaded")],
                is_error=True,
            )
            return result
        operation_details = lookup_operation_details(function_name, openapi_spec_data)
        if not operation_details:
            logger.error('Could not find OpenAPI operation for function (details omitted)')
            result = mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Could not find OpenAPI operation for function")],
                is_error=True,
            )
            return result

        operation = dict(operation_details["operation"])
        operation["method"] = operation_details["method"]
        headers = handle_auth(operation)
        additional_headers = get_additional_headers()
        headers = {**headers, **additional_headers}
        parameters = dict(strip_parameters(arguments))
        method = operation_details["method"]
        if method != "GET":
            headers["Content-Type"] = "application/json"

        path = operation_details["path"]
        original_path = operation_details["original_path"]
        if not is_tool_whitelisted(original_path):
            result = mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Operation not authorized")],
                is_error=True,
            )
            return result
        base_url = build_base_url(openapi_spec_data)
        if not base_url:
            logger.critical("Failed to construct base URL from spec or SERVER_URL_OVERRIDE.")
            result = mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="No base URL defined in spec or SERVER_URL_OVERRIDE")],
                is_error=True,
            )
            return result
        try:
            path_item = openapi_spec_data.get("paths", {}).get(original_path, {})
            verified = validate_path_arguments(path, parameters, operation, path_item, openapi_spec_data)
            api_url, used_path_parameters = safe_url(base_url, path, verified)
        except (ValueError, TypeError):
            result = mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Invalid or unsafe path parameters")],
                is_error=True,
            )
            return result
        for key in used_path_parameters:
            parameters.pop(key, None)
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
                    logger.error('Missing required path parameters (details omitted)')
                    result = mcp_types.CallToolResult(
                        content=[mcp_types.TextContent(type="text", text="Missing required path parameters")],
                        is_error=True,
                    )
                    return result
            if method == "GET":
                request_params = parameters
            else:
                request_body = parameters
        else:
            logger.debug("No valid parameters provided, proceeding without params/body")

        logger.debug('API Request - URL (details omitted)')
        logger.debug('Headers (details omitted)')
        logger.debug('Query Params (details omitted)')
        logger.debug('Request Body (details omitted)')

        try:
            ignore_ssl_tools = os.getenv("IGNORE_SSL_TOOLS", "false").lower() in ("true", "1", "yes")
            verify_ssl_tools = not ignore_ssl_tools
            logger.debug('Sending API request with SSL verification (details omitted)')
            if not is_tool_whitelisted(original_path):
                result = mcp_types.CallToolResult(
                    content=[mcp_types.TextContent(type="text", text="Operation no longer authorized")],
                    is_error=True,
                )
                return result
            request_started = time.monotonic()
            log_http_event("sending", method=method)
            response = await bounded_request_async(
                method=method,
                url=api_url,
                headers=headers,
                params=request_params if method == "GET" else None,
                json=request_body if method != "GET" else None,
                verify=verify_ssl_tools,
            )
            response.raise_for_status()
            log_http_event("completed", method=method,
                           status=getattr(response, "status_code", None),
                           started=request_started)
            response_text = (response.text or "No response body").strip()
            content, log_message = detect_response_type(response_text)
            logger.debug(log_message)
            final_content = [content.model_dump()]
        except requests.exceptions.RequestException as e:
            logger.error('API request failed (details omitted)')
            result = mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=("Upstream redirect refused" if isinstance(e, RedirectRefused) else "Upstream request failed"))],
                is_error=True,
            )
            return result

        logger.debug('Response content type (details omitted)')
        logger.debug('Response sent to client (details omitted)')
        result = mcp_types.CallToolResult(content=final_content, is_error=False)  # type: ignore
        return result
    except Exception as e:
        logger.error('Unhandled exception in dispatcher_handler (details omitted)')
        result = mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="Internal processing failed")],
            is_error=True,
        )
        return result


async def list_tools(ctx_or_request: Any = None, params: Any = None) -> Any:
    """Return a list of registered tools."""
    logger.debug("Handling list_tools request - start")
    logger.debug('Tools list length (details omitted)')
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
    logger.debug('Resources list length (details omitted)')
    result = types.ListResourcesResult(resources=resources)
    return result


async def read_resource(ctx_or_request: Any, params: Any = None) -> Any:
    """Read a specific resource identified by its URI."""
    _, params = unpack_handler_args(ctx_or_request, params)
    uri_str = str(params.uri)
    if uri_str not in {str(item.uri) for item in resources} | {"file:///openapi_spec.json"}:
        raise ValueError("Resource not found")
    logger.debug('START read_resource for URI (details omitted)')
    try:
        global openapi_spec_data
        spec_data = openapi_spec_data

        if not spec_data:
            openapi_url = os.getenv("OPENAPI_SPEC_URL")
            logger.debug('Got OPENAPI_SPEC_URL (details omitted)')
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

        logger.debug('Spec fetched (details omitted)')
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
        logger.debug('Forcing spec JSON return (details omitted)')
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
        logger.error('Error forcing resource (details omitted)')
        result = types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    text="Resource operation failed", uri=uri_str
                )
            ]
        )
        return result


async def list_prompts(ctx_or_request: Any = None, params: Any = None) -> Any:
    """Return a list of registered prompts."""
    logger.debug("Handling list_prompts request")
    logger.debug('Prompts list length (details omitted)')
    result = types.ListPromptsResult(prompts=prompts)
    return result


async def get_prompt(ctx_or_request: Any, params: Any = None) -> Any:
    """Return a specific prompt by name."""
    _, params = unpack_handler_args(ctx_or_request, params)
    name = params.name
    logger.debug('Handling get_prompt request for (details omitted)')
    prompt = next((p for p in prompts if p.name == name), None)
    if not prompt:
        logger.error("Prompt ' (details omitted)")
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
        logger.error('Error generating prompt (details omitted)')
        result = types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(type="text", text="Prompt operation failed"),
                )
            ]
        )
        return result