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

# Resource and prompt DEFINITIONS are always present so the feature is
# deterministically testable. Whether they are EXPOSED to clients is gated
# separately by ENABLE_RESOURCES / ENABLE_PROMPTS, which control handler
# registration (run_server) and capability advertisement (build_capabilities).
resources: List[types.Resource] = [
    types.Resource(
        name="spec_file",
        uri=AnyUrl("file:///openapi_spec.json"),
        description="The raw OpenAPI specification JSON",
    )
]


def _load_additional_resources() -> Dict[str, str]:
    """Parse ADDITIONAL_RESOURCES ("name=/path/file.md,name2=/path2") into
    {name: path} and register each as a listed resource. Lets a deployment
    ship use-case documents (naming policies, layout conventions) alongside
    the spec — see examples/resources/."""
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
            types.Resource(
                name=name,
                uri=AnyUrl(f"file:///{name}"),
                description=f"Additional resource served from {os.path.basename(path)}",
            )
        )
    return mapping


ADDITIONAL_RESOURCES: Dict[str, str] = _load_additional_resources()

prompts: List[types.Prompt] = [
    types.Prompt(
        name="summarize_spec",
        description="Summarizes the OpenAPI specification",
        arguments=[],
    ),
    types.Prompt(
        name="whimsical_blog",
        description="A whimsical WordPress blog-post starter inspired by this API",
        arguments=[],
    ),
]

# Prompt message templates, keyed by prompt name. Kept separate from the
# types.Prompt metadata, which has no `messages` field — get_prompt() builds
# the actual PromptMessage list from these.
PROMPT_TEMPLATES: Dict[str, Any] = {
    "summarize_spec": lambda args: [
        types.PromptMessage(
            role="assistant",
            content=types.TextContent(
                type="text",
                text="This OpenAPI spec defines endpoints, parameters, and responses—a blueprint for developers to integrate effectively.",
            ),
        )
    ],
    "whimsical_blog": lambda args: [
        types.PromptMessage(
            role="assistant",
            content=types.TextContent(
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


def build_capabilities() -> "types.ServerCapabilities":
    """Advertise a capability whenever its feature is enabled (ENABLE_*).

    A capability object must be present for strict MCP clients (e.g. Gemini,
    Codex, Qwen) to attempt list_tools/list_resources/list_prompts at all;
    `listChanged` is a sub-detail controlled by the CAPABILITIES_* envvars.
    """
    return types.ServerCapabilities(
        tools=types.ToolsCapability(listChanged=CAPABILITIES_TOOLS) if ENABLE_TOOLS else None,
        prompts=types.PromptsCapability(listChanged=CAPABILITIES_PROMPTS) if ENABLE_PROMPTS else None,
        resources=types.ResourcesCapability(listChanged=CAPABILITIES_RESOURCES) if ENABLE_RESOURCES else None,
    )

openapi_spec_data: Optional[Dict[str, Any]] = None

# Lazy spec loading (issue #28): the MCP handshake must be answered immediately,
# even when OPENAPI_SPEC_URL is slow to download/parse. Clients with short
# connect timeouts (observed: Kilocode, Vibe) otherwise hang up mid-handshake,
# the proxy dies on the closed stream, the client respawns it — a crash loop.
_spec_load_lock: Optional[asyncio.Lock] = None
_spec_load_error: Optional[str] = None


async def ensure_spec_loaded() -> Optional[Dict[str, Any]]:
    """Fetch and register the OpenAPI spec on first use. Safe to call from any
    handler; concurrent callers await the same fetch."""
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
            logger.critical(_spec_load_error)
            return None
        logger.debug(f"Lazily fetching OpenAPI spec from {openapi_url}...")
        spec = await anyio.to_thread.run_sync(fetch_openapi_spec, openapi_url)
        if not spec:
            _spec_load_error = f"Failed to fetch or parse OpenAPI spec from {openapi_url}"
            logger.critical(_spec_load_error)
            return None
        openapi_spec_data = spec
        if ENABLE_TOOLS:
            from mcp_openapi_proxy.handlers import register_functions
            register_functions(spec)
            logger.debug(f"Tools registered lazily: {[tool.name for tool in tools]}")
            if not tools:
                logger.critical("No valid tools registered from spec.")
        return openapi_spec_data


mcp = Server("OpenApiProxy-LowLevel")

async def dispatcher_handler(request: types.CallToolRequest) -> types.CallToolResult:
    """
    Dispatcher handler that routes CallToolRequest to the appropriate function (tool).
    """
    global openapi_spec_data
    try:
        await ensure_spec_loaded()
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
    await ensure_spec_loaded()
    logger.debug(f"Tools list length: {len(tools)}")
    return types.ListToolsResult(tools=tools)

async def list_resources(request: types.ListResourcesRequest) -> types.ListResourcesResult:
    """List the spec_file resource plus any ADDITIONAL_RESOURCES entries.

    The module-level `resources` list is always seeded with spec_file; the
    guard below only matters if a caller mutated it at runtime.
    """
    logger.debug(f"Handling list_resources request ({len(resources)} resources)")
    if not resources:
        logger.debug("Resources empty; repopulating default resource")
        resources.append(
            types.Resource(
                name="spec_file",
                uri=AnyUrl("file:///openapi_spec.json"),
                description="The raw OpenAPI specification JSON",
            )
        )
    return types.ListResourcesResult(resources=resources)


async def read_resource(request: types.ReadResourceRequest) -> types.ReadResourceResult:
    logger.debug(f"START read_resource for URI: {request.params.uri}")
    try:
        uri_str = str(request.params.uri)
        for name, path in ADDITIONAL_RESOURCES.items():
            if uri_str == f"file:///{name}":
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                except OSError as exc:
                    text = f"Resource '{name}' unavailable: {exc}"
                mime = "text/markdown" if path.endswith((".md", ".markdown")) else "text/plain"
                return types.ReadResourceResult(
                    contents=[
                        types.TextResourceContents(
                            uri=request.params.uri, text=text, mimeType=mime
                        )
                    ]
                )
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
        spec_json = json.dumps(spec_data, indent=2, default=str)
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
    template = PROMPT_TEMPLATES.get(request.params.name)
    if template is None:
        logger.error(f"Prompt '{request.params.name}' not found")
        return types.GetPromptResult(
            description="Prompt not found",
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(type="text", text=f"Prompt '{request.params.name}' not found"),
                )
            ],
        )
    try:
        messages = template(request.params.arguments or {})
        logger.debug(f"Generated messages: {messages}")
        return types.GetPromptResult(messages=messages)
    except Exception as e:
        logger.error(f"Error generating prompt: {e}", exc_info=True)
        return types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(type="text", text=f"Prompt error: {str(e)}"),
                )
            ],
        )


def lookup_operation_details(function_name: str, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # Resolve names recorded at registration time first: names deduplicated
    # after TOOL_NAME_MAX_LENGTH truncation (issue #11) cannot be regenerated
    # from the spec alone.
    from mcp_openapi_proxy.openapi import _REGISTERED_OPERATIONS
    registered = _REGISTERED_OPERATIONS.get(function_name)
    if registered:
        return dict(registered)
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


def _is_closed_stream_error(exc: BaseException) -> bool:
    """True when the failure means the client hung up — retrying is pointless."""
    if isinstance(exc, (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream)):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_closed_stream_error(sub) for sub in exc.exceptions)
    return False


async def start_server():
    logger.debug("Starting Low-Level MCP server...")
    # Pre-warm the spec in the background: the handshake is served immediately
    # while the (possibly slow) spec download proceeds (issue #28).
    prewarm = asyncio.create_task(ensure_spec_loaded())
    async with stdio_server() as (read_stream, write_stream):
        while True:
            try:
                capabilities = build_capabilities()
                await mcp.run(
                    read_stream,
                    write_stream,
                    initialization_options=InitializationOptions(
                        server_name="AnyOpenAPIMCP-LowLevel",
                        server_version="0.1.0",
                        capabilities=capabilities,
                    ),
                )
                logger.debug("MCP session ended normally; exiting.")
                break
            except BaseException as e:
                if _is_closed_stream_error(e):
                    # Client disconnected (e.g. short connect timeout while the
                    # spec was still loading). Exit cleanly instead of spinning
                    # on a dead stream — the client respawns us if it wants to.
                    logger.warning("Client closed the stream; shutting down cleanly.")
                    break
                logger.error(f"MCP run crashed: {e}", exc_info=True)
                await anyio.sleep(1)
    prewarm.cancel()


def run_server():
    try:
        if not os.getenv('OPENAPI_SPEC_URL'):
            logger.critical("OPENAPI_SPEC_URL environment variable is required but not set.")
            sys.exit(1)
        # Spec fetch + tool registration are lazy (ensure_spec_loaded) so the
        # MCP handshake is never blocked by a slow spec download (issue #28).
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
