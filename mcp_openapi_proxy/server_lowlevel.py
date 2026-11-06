"""
Low-Level Server for mcp-openapi-proxy.

Dynamically registers tools from an OpenAPI spec. Speaks MCP 2026-07-28
(stateless, dual-stack with the legacy initialize handshake on stdio).
"""

import os
import sys
import asyncio
import json
import requests
import time
from mcp_openapi_proxy.bounded_http import bounded_request_async
from mcp_openapi_proxy.request_security import RedirectRefused
from mcp_openapi_proxy.privacy_diagnostics import log_http_event
from mcp_openapi_proxy.path_safety import safe_url, validate_path_arguments
from typing import List, Dict, Any, Optional, cast
import anyio

from mcp import types as mcp_types

types = mcp_types  # re-export; tests may rebind this name — handlers use mcp_types
from mcp.server.lowlevel import Server, NotificationOptions
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
from mcp_openapi_proxy.protocol import (
    PACKAGE_VERSION,
    McpRpcLogMiddleware,
    advertised_server_description,
    advertised_server_name,
    advertised_server_title,
    cache_hints,
    healthz_route,
    json_response,
    log_raw_command,
    mcp_host,
    mcp_path,
    mcp_port,
    transport_name,
    transport_security,
    unpack_handler_args,
)

DEBUG = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
logger = setup_logging(debug=DEBUG)

tools: List[mcp_types.Tool] = []
CAPABILITIES_TOOLS = os.getenv("CAPABILITIES_TOOLS", "false").lower() == "true"
CAPABILITIES_RESOURCES = os.getenv("CAPABILITIES_RESOURCES", "false").lower() == "true"
CAPABILITIES_PROMPTS = os.getenv("CAPABILITIES_PROMPTS", "false").lower() == "true"

ENABLE_TOOLS = os.getenv("ENABLE_TOOLS", "true").lower() == "true"
ENABLE_RESOURCES = os.getenv("ENABLE_RESOURCES", "true").lower() == "true"
ENABLE_PROMPTS = os.getenv("ENABLE_PROMPTS", "true").lower() == "true"

resources: List[mcp_types.Resource] = [
    mcp_types.Resource(
        name="spec_file",
        uri="file:///openapi_spec.json",
        description="The raw OpenAPI specification JSON",
    )
]


def _load_additional_resources() -> Dict[str, str]:
    """Parse ADDITIONAL_RESOURCES ("name=/path/file.md,name2=/path2") into
    {name: path} and register each as a listed resource."""
    mapping: Dict[str, str] = {}
    for entry in os.getenv("ADDITIONAL_RESOURCES", "").split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        name, path = (part.strip() for part in entry.split("=", 1))
        if not name or not path:
            continue
        mapping[name] = path
        resources.append(
            mcp_types.Resource(
                name=name,
                uri=f"file:///{name}",
                description=f"Additional resource served from {os.path.basename(path)}",
            )
        )
    return mapping


ADDITIONAL_RESOURCES: Dict[str, str] = _load_additional_resources()

prompts: List[mcp_types.Prompt] = [
    mcp_types.Prompt(
        name="summarize_spec",
        description="Summarizes the OpenAPI specification",
        arguments=[],
    ),
    mcp_types.Prompt(
        name="whimsical_blog",
        description="A whimsical WordPress blog-post starter inspired by this API",
        arguments=[],
    ),
]

PROMPT_TEMPLATES: Dict[str, Any] = {
    "summarize_spec": lambda args: [
        mcp_types.PromptMessage(
            role="assistant",
            content=mcp_types.TextContent(
                type="text",
                text="This OpenAPI spec defines endpoints, parameters, and responses—a blueprint for developers to integrate effectively.",
            ),
        )
    ],
    "whimsical_blog": lambda args: [
        mcp_types.PromptMessage(
            role="assistant",
            content=mcp_types.TextContent(
                type="text",
                text=(
                    "Once upon a JSON, in a land of tilde keys and sticky semicolons, a pet AI "
                    "chatbot discovered it could whisper to WordPress through a magic OpenAPI proxy. "
                    "✨ Write the next whimsical chapter: how this humble API became a digital "
                    "playground where agents publish tales at the speed of thought."
                ),
            ),
        )
    ],
}


def register_env_prompt(raw: Optional[str] = None) -> None:
    """Register one extra prompt from the PROMPT env var when prompts are enabled.

    Read at call time so tests can set PROMPT without reloading the module.
    Import-time registration covers a normal process start.
    """
    from mcp_openapi_proxy.prompt_env import BUILTIN_PROMPT_NAMES, parse_prompt_env

    if os.getenv("ENABLE_PROMPTS", "true").lower() != "true":
        return
    parsed = parse_prompt_env(raw)
    if not parsed:
        return
    name = parsed["name"]
    if name in BUILTIN_PROMPT_NAMES:
        logger.error("Custom PROMPT uses a reserved built-in name; ignoring")
        return
    prompts[:] = [p for p in prompts if p.name != name]
    prompts.append(
        mcp_types.Prompt(
            name=name,
            description=parsed["description"],
            arguments=[],
        )
    )
    stored = [
        mcp_types.PromptMessage(
            role=item["role"],
            content=mcp_types.TextContent(type="text", text=item["text"]),
        )
        for item in parsed["messages"]
    ]

    def _messages(_args: Any) -> List[mcp_types.PromptMessage]:
        return list(stored)

    PROMPT_TEMPLATES[name] = _messages
    logger.debug("Registered custom low-level MCP prompt")


register_env_prompt()


def build_capabilities() -> "mcp_types.ServerCapabilities":
    """Advertise a capability whenever its feature is enabled (ENABLE_*)."""
    return mcp_types.ServerCapabilities(
        tools=mcp_types.ToolsCapability(list_changed=CAPABILITIES_TOOLS) if ENABLE_TOOLS else None,
        prompts=mcp_types.PromptsCapability(list_changed=CAPABILITIES_PROMPTS) if ENABLE_PROMPTS else None,
        resources=mcp_types.ResourcesCapability(list_changed=CAPABILITIES_RESOURCES) if ENABLE_RESOURCES else None,
    )


openapi_spec_data: Optional[Dict[str, Any]] = None

_spec_load_lock: Optional[asyncio.Lock] = None
_spec_load_error: Optional[str] = None


async def ensure_spec_loaded() -> Optional[Dict[str, Any]]:
    """Fetch and register the OpenAPI spec on first use. Safe to call from any
    handler; concurrent callers await the same fetch. Process-local, not a
    protocol session — any instance can rebuild this from OPENAPI_SPEC_URL."""
    global openapi_spec_data, _spec_load_lock, _spec_load_error
    if openapi_spec_data is not None or _spec_load_error is not None:
        return openapi_spec_data
    if _spec_load_lock is None:
        _spec_load_lock = asyncio.Lock()
    async with _spec_load_lock:
        if openapi_spec_data is not None or _spec_load_error is not None:
            return openapi_spec_data
        openapi_url = os.getenv("OPENAPI_SPEC_URL")
        if not openapi_url:
            _spec_load_error = "OPENAPI_SPEC_URL not set"
            logger.critical('Proxy operation (details omitted)')
            return None
        logger.debug('Lazily fetching OpenAPI spec from (details omitted)')
        spec = await anyio.to_thread.run_sync(fetch_openapi_spec, openapi_url)
        if not spec:
            _spec_load_error = f"Failed to fetch or parse OpenAPI spec from {openapi_url}"
            logger.critical('Proxy operation (details omitted)')
            return None
        openapi_spec_data = spec
        if ENABLE_TOOLS:
            from mcp_openapi_proxy.handlers import register_functions
            register_functions(spec)
            logger.debug('Tools registered lazily (details omitted)')
            if not tools:
                logger.critical("No valid tools registered from spec.")
        return openapi_spec_data


async def dispatcher_handler(ctx_or_request: Any, params: Any = None) -> mcp_types.CallToolResult:
    _, params = unpack_handler_args(ctx_or_request, params)
    """
    Dispatcher handler that routes CallToolRequest to the appropriate function (tool).
    """
    global openapi_spec_data
    try:
        await ensure_spec_loaded()
        function_name = params.name
        logger.debug('Dispatcher received CallToolRequest for function (details omitted)')
        logger.debug('API_KEY (details omitted)')
        logger.debug('STRIP_PARAM (details omitted)')
        tool = next((t for t in tools if t.name == function_name), None)
        if not tool:
            logger.error('Unknown function requested (details omitted)')
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Unknown function requested")],
                is_error=True,
            )
        arguments = params.arguments or {}
        log_raw_command(function_name, arguments)
        logger.debug('Raw arguments before processing (details omitted)')

        if openapi_spec_data is None:
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="OpenAPI spec not loaded")],
                is_error=True,
            )
        # Since we've checked openapi_spec_data is not None, cast it to Dict.
        operation_details = lookup_operation_details(function_name, cast(Dict, openapi_spec_data))
        if not operation_details:
            logger.error('Could not find OpenAPI operation for function (details omitted)')
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Could not find OpenAPI operation for function")],
                is_error=True,
            )

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
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Operation not authorized")],
                is_error=True,
            )
        base_url = build_base_url(cast(Dict, openapi_spec_data))
        if not base_url:
            logger.critical("Failed to construct base URL from spec or SERVER_URL_OVERRIDE.")
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="No base URL defined in spec or SERVER_URL_OVERRIDE")],
                is_error=True,
            )
        try:
            path_item = openapi_spec_data.get("paths", {}).get(original_path, {})
            verified = validate_path_arguments(path, parameters, operation, path_item, openapi_spec_data)
            api_url, used_path_parameters = safe_url(base_url, path, verified)
        except (ValueError, TypeError):
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="Invalid or unsafe path parameters")],
                is_error=True,
            )
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
                    return mcp_types.CallToolResult(
                        content=[mcp_types.TextContent(type="text", text="Missing required path parameters")],
                        is_error=True,
                    )
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
            if not is_tool_whitelisted(original_path):
                return mcp_types.CallToolResult(
                    content=[mcp_types.TextContent(type="text", text="Operation no longer authorized")],
                    is_error=True,
                )
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
            # Expect content to be of a type that can be included as is.
            final_content = [content]
        except requests.exceptions.RequestException as e:
            logger.error('API request failed (details omitted)')
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=("Upstream redirect refused" if isinstance(e, RedirectRefused) else "Upstream request failed"))],
                is_error=True,
            )
        logger.debug('Response content type (details omitted)')
        logger.debug('Response sent to client (details omitted)')
        return mcp_types.CallToolResult(content=final_content, is_error=False)
    except Exception as e:
        logger.error('Unhandled exception in dispatcher_handler (details omitted)')
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="Internal processing failed")],
            is_error=True,
        )


async def list_tools(ctx_or_request: Any = None, params: Any = None) -> mcp_types.ListToolsResult:
    logger.debug("Handling list_tools request - start")
    await ensure_spec_loaded()
    logger.debug('Tools list length (details omitted)')
    return mcp_types.ListToolsResult(tools=tools)


async def list_resources(ctx_or_request: Any = None, params: Any = None) -> mcp_types.ListResourcesResult:
    logger.debug('Handling list_resources request ( (details omitted)')
    if not resources:
        logger.debug("Resources empty; repopulating default resource")
        resources.append(
            mcp_types.Resource(
                name="spec_file",
                uri="file:///openapi_spec.json",
                description="The raw OpenAPI specification JSON",
            )
        )
    return mcp_types.ListResourcesResult(resources=resources)


async def read_resource(ctx_or_request: Any, params: Any = None) -> mcp_types.ReadResourceResult:
    _, params = unpack_handler_args(ctx_or_request, params)
    uri_str = str(params.uri)
    if uri_str not in {str(item.uri) for item in resources} | {"file:///openapi_spec.json"}:
        raise ValueError("Resource not found")
    logger.debug('START read_resource for URI (details omitted)')
    try:
        for name, path in ADDITIONAL_RESOURCES.items():
            if uri_str == f"file:///{name}":
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                except OSError:
                    text = "Resource unavailable"
                mime = "text/markdown" if path.endswith((".md", ".markdown")) else "text/plain"
                return mcp_types.ReadResourceResult(
                    contents=[
                        mcp_types.TextResourceContents(
                            uri=uri_str, text=text, mime_type=mime
                        )
                    ]
                )
        openapi_url = os.getenv("OPENAPI_SPEC_URL")
        logger.debug('Got OPENAPI_SPEC_URL (details omitted)')
        if not openapi_url:
            logger.error("OPENAPI_SPEC_URL not set")
            return mcp_types.ReadResourceResult(
                contents=[
                    mcp_types.TextResourceContents(
                        uri=uri_str,
                        text="Spec unavailable: OPENAPI_SPEC_URL not set"
                    )
                ]
            )
        logger.debug("Fetching spec...")
        spec_data = fetch_openapi_spec(openapi_url)
        logger.debug('Spec fetched (details omitted)')
        if not spec_data:
            logger.error("Failed to fetch OpenAPI spec")
            return mcp_types.ReadResourceResult(
                contents=[
                    mcp_types.TextResourceContents(
                        uri=uri_str,
                        text="Spec data unavailable after fetch attempt"
                    )
                ]
            )
        logger.debug("Dumping spec to JSON...")
        spec_json = json.dumps(spec_data, indent=2, default=str)
        logger.debug('Forcing spec JSON return (details omitted)')
        return mcp_types.ReadResourceResult(
            contents=[
                mcp_types.TextResourceContents(
                    uri="file:///openapi_spec.json",
                    text=spec_json,
                    mime_type="application/json"
                )
            ]
        )
    except Exception as e:
        logger.error('Error forcing resource (details omitted)')
        return mcp_types.ReadResourceResult(
            contents=[
                mcp_types.TextResourceContents(
                    uri=uri_str,
                    text="Resource operation failed"
                )
            ]
        )


async def list_prompts(ctx_or_request: Any = None, params: Any = None) -> mcp_types.ListPromptsResult:
    logger.debug("Handling list_prompts request")
    logger.debug('Prompts list length (details omitted)')
    return mcp_types.ListPromptsResult(prompts=prompts)


async def get_prompt(ctx_or_request: Any, params: Any = None) -> mcp_types.GetPromptResult:
    _, params = unpack_handler_args(ctx_or_request, params)
    name = params.name
    logger.debug("Handling MCP prompt request")
    template = PROMPT_TEMPLATES.get(name)
    if template is None:
        logger.error("MCP prompt not found")
        return mcp_types.GetPromptResult(
            description="Prompt not found",
            messages=[
                mcp_types.PromptMessage(
                    role="assistant",
                    content=mcp_types.TextContent(type="text", text="Prompt not found"),
                )
            ],
        )
    try:
        messages = template(getattr(params, "arguments", None) or {})
        logger.debug("MCP prompt messages generated")
        return mcp_types.GetPromptResult(messages=messages)
    except Exception as e:
        logger.error('MCP prompt generation failed (%s) (details omitted)')
        return mcp_types.GetPromptResult(
            messages=[
                mcp_types.PromptMessage(
                    role="assistant",
                    content=mcp_types.TextContent(type="text", text="Prompt operation failed"),
                )
            ],
        )


def lookup_operation_details(function_name: str, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from mcp_openapi_proxy.openapi import lookup_operation_details as lookup
    from mcp_openapi_proxy.openapi import _REGISTERED_OPERATIONS
    if spec and not _REGISTERED_OPERATIONS:
        from mcp_openapi_proxy.handlers import register_functions
        register_functions(spec)
    return lookup(function_name, spec)


def _is_closed_stream_error(exc: BaseException) -> bool:
    """True when the failure means the client hung up — retrying is pointless."""
    if isinstance(exc, (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream)):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_closed_stream_error(sub) for sub in exc.exceptions)
    return False


def build_server() -> Server:
    """Construct a low-level Server from the current handler callables.

    Rebuilt in run_server() so gateway monkeypatches of dispatcher_handler
    are picked up (the v2 Server captures on_* at construction time).
    """
    name = advertised_server_name()
    kwargs: Dict[str, Any] = {
        "version": PACKAGE_VERSION,
        "cache_hints": cache_hints(),
    }
    title = advertised_server_title()
    if title:
        kwargs["title"] = title
    description = advertised_server_description()
    if description:
        kwargs["description"] = description
    if ENABLE_TOOLS:
        kwargs["on_list_tools"] = list_tools
        kwargs["on_call_tool"] = dispatcher_handler
    if ENABLE_RESOURCES:
        kwargs["on_list_resources"] = list_resources
        kwargs["on_read_resource"] = read_resource
    if ENABLE_PROMPTS:
        kwargs["on_list_prompts"] = list_prompts
        kwargs["on_get_prompt"] = get_prompt
    logger.debug('Building MCP server identity name (details omitted)')
    return Server(name, **kwargs)


mcp = build_server()


def _initialization_options() -> InitializationOptions:
    return mcp.create_initialization_options(
        notification_options=NotificationOptions(
            tools_changed=CAPABILITIES_TOOLS,
            prompts_changed=CAPABILITIES_PROMPTS,
            resources_changed=CAPABILITIES_RESOURCES,
        )
    )


async def start_server():
    logger.debug("Starting Low-Level MCP server (stdio, dual-stack)...")
    prewarm = asyncio.create_task(ensure_spec_loaded())
    async with stdio_server() as (read_stream, write_stream):
        while True:
            try:
                await mcp.run(
                    read_stream,
                    write_stream,
                    initialization_options=_initialization_options(),
                )
                logger.debug("MCP session ended normally; exiting.")
                break
            except BaseException as e:
                if _is_closed_stream_error(e):
                    logger.warning("Client closed the stream; shutting down cleanly.")
                    break
                logger.error('MCP run crashed (details omitted)')
                await anyio.sleep(1)
    prewarm.cancel()


def build_streamable_http_app(*, host: Optional[str] = None, path: Optional[str] = None):
    """Starlette app for native Streamable HTTP plus process-local GET /healthz.

    /healthz is a sibling custom_starlette_route so it never enters
    StreamableHTTPSessionManager or the MCP request lock.

    Raw ASGI middleware logs one INFO line per inbound JSON-RPC method
    (plus tools/call name) before StreamableHTTPSessionManager. Stdio is
    unchanged.
    """
    app = mcp.streamable_http_app(
        streamable_http_path=path or mcp_path(),
        json_response=json_response(),
        stateless_http=True,
        transport_security=transport_security(),
        host=host or mcp_host(),
        custom_starlette_routes=[healthz_route()],
    )
    app.add_middleware(McpRpcLogMiddleware, known_tool_names=lambda: {tool.name for tool in tools})
    return app


def _run_streamable_http() -> None:
    """Stateless Streamable HTTP: no Mcp-Session-Id, no sticky routing."""
    import uvicorn

    host = mcp_host()
    port = mcp_port()
    path = mcp_path()
    logger.debug('Starting Low-Level MCP server (streamable-http, stateless) on (details omitted)')
    app = build_streamable_http_app(host=host, path=path)
    uvicorn.run(app, host=host, port=port)


def run_server():
    global mcp
    try:
        if not os.getenv('OPENAPI_SPEC_URL'):
            logger.critical("OPENAPI_SPEC_URL environment variable is required but not set.")
            sys.exit(1)
        # Rebuild so monkeypatches (gateway query-auth) bind into on_call_tool.
        mcp = build_server()
        logger.debug("Handlers registered based on capabilities and enablement envvars.")
        if transport_name() == "streamable-http":
            _run_streamable_http()
        else:
            asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.debug("MCP server shutdown initiated by user.")
    except Exception as e:
        logger.critical('Failed to start MCP server (details omitted)')
        sys.exit(1)


if __name__ == "__main__":
    run_server()
