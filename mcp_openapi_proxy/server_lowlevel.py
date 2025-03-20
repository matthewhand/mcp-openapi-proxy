"""
Low-Level Server for mcp-openapi-proxy.

Dynamically registers tools from an OpenAPI spec, adds a prompt to summarize the spec,
and a resource for the spec itself.
"""

import os
import sys
import asyncio
import json
import requests
from typing import List, Dict, Any
from mcp.types import Tool, Prompt, Resource, ServerResult, ListToolsResult, CallToolResult, ListPromptsResult, GetPromptResult, ListResourcesResult, ReadResourceResult, ListToolsRequest, CallToolRequest, ListPromptsRequest, GetPromptRequest, ListResourcesRequest, ReadResourceRequest, TextContent, ServerCapabilities, ToolsCapability, PromptsCapability, ResourcesCapability
from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp_openapi_proxy.utils import setup_logging, normalize_tool_name, is_tool_whitelisted, fetch_openapi_spec, build_base_url, handle_auth, strip_parameters, detect_response_type, get_additional_headers

DEBUG = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
logger = setup_logging(debug=DEBUG)

tools: List[Tool] = []
prompts: List[Prompt] = [
    Prompt(
        name="summarize_spec",
        description="Summarizes the purpose of the OpenAPI specification",
        arguments=[],
        messages=lambda args: [
            {"role": "assistant", "content": {"type": "text", "text": "This OpenAPI spec defines an API’s endpoints, parameters, and responses, making it a blueprint for devs to build and integrate stuff without messing it up."}}
        ]
    )
]
resources: List[Resource] = [
    Resource(
        name="spec_file",
        uri="file:///openapi_spec.json",
        description="The raw OpenAPI specification JSON"
    )
]
openapi_spec_data = None

mcp = Server("OpenApiProxy-LowLevel")

async def dispatcher_handler(request: CallToolRequest) -> ServerResult:
    global openapi_spec_data
    try:
        function_name = request.params.name
        logger.debug(f"Dispatcher received CallToolRequest for function: {function_name}")
        tool = next((tool for tool in tools if tool.name == function_name), None)
        if not tool:
            logger.error(f"Unknown function requested: {function_name}")
            return ServerResult(
                root=CallToolResult(
                    content=[TextContent(type="text", text="Unknown function requested")]
                )
            )
        arguments = request.params.arguments or {}
        operation_details = lookup_operation_details(function_name, openapi_spec_data)
        if not operation_details:
            logger.error(f"Could not find OpenAPI operation for function: {function_name}")
            return ServerResult(
                root=CallToolResult(
                    content=[TextContent(type="text", text=f"Could not find OpenAPI operation for function: {function_name}")]
                )
            )
        operation = operation_details['operation']
        operation['method'] = operation_details['method']
        headers = handle_auth(operation)
        additional_headers = get_additional_headers()  # Yer precious extra headers
        headers = {**headers, **additional_headers}
        parameters = strip_parameters(arguments)
        method = operation_details['method']
        if method != "GET":
            headers["Content-Type"] = "application/json"
        path = operation_details['path']
        base_url = build_base_url(openapi_spec_data)
        if not base_url:
            logger.critical("Failed to construct base URL from spec or SERVER_URL_OVERRIDE.")
            return ServerResult(
                root=CallToolResult(
                    content=[TextContent(type="text", text="No base URL defined in spec or SERVER_URL_OVERRIDE")]
                )
            )
        api_url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        request_params = {}
        request_body = None
        if isinstance(parameters, dict):
            merged_params = []
            path_item = openapi_spec_data.get("paths", {}).get(path, {})
            if isinstance(path_item, dict) and "parameters" in path_item:
                merged_params.extend(path_item["parameters"])
            if "parameters" in operation:
                merged_params.extend(operation["parameters"])
            path_params_in_openapi = [param["name"] for param in merged_params if param.get("in") == "path"]
            if path_params_in_openapi:
                missing_required = [
                    param["name"] for param in merged_params
                    if param.get("in") == "path" and param.get("required", False) and param["name"] not in parameters
                ]
                if missing_required:
                    logger.error(f"Missing required path parameters: {missing_required}")
                    return ServerResult(
                        root=CallToolResult(
                            content=[TextContent(type="text", text=f"Missing required path parameters: {missing_required}")]
                        )
                    )
                for param_name in path_params_in_openapi:
                    if param_name in parameters:
                        value = str(parameters.pop(param_name))
                        api_url = api_url.replace(f"{{{param_name}}}", value)
                        api_url = api_url.replace(f"%7B{param_name}%7D", value)
                        logger.debug(f"Replaced path param {param_name} in URL: {api_url}")
            if method == "GET":
                request_params = parameters
            else:
                request_body = parameters
        else:
            logger.debug("No valid parameters provided, proceeding without params/body")
        try:
            response = requests.request(
                method=method,
                url=api_url,
                headers=headers,
                params=request_params if method == "GET" else None,
                json=request_body if method != "GET" else None
            )
            response.raise_for_status()
            response_text = response.text or "No response body"
            content, log_message = detect_response_type(response_text)
            logger.debug(log_message)
            return ServerResult(
                root=CallToolResult(
                    content=[content]
                )
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return ServerResult(
                root=CallToolResult(
                    content=[TextContent(type="text", text=str(e))]
                )
            )
    except Exception as e:
        logger.error(f"Unhandled exception in dispatcher_handler: {e}", exc_info=True)
        return ServerResult(
            root=CallToolResult(
                content=[TextContent(type="text", text=f"Internal error: {str(e)}")]
            )
        )

async def list_tools(request: ListToolsRequest) -> ServerResult:
    logger.debug("Handling list_tools request")
    logger.debug(f"Tools list length: {len(tools)}")
    result = ServerResult(root=ListToolsResult(tools=tools))
    logger.debug("list_tools result prepared")
    sys.stderr.flush()
    return result

async def list_prompts(request: ListPromptsRequest) -> ServerResult:
    logger.debug("Handling list_prompts request")
    logger.debug(f"Prompts list length: {len(prompts)}")
    return ServerResult(root=ListPromptsResult(prompts=prompts))

async def get_prompt(request: GetPromptRequest) -> ServerResult:
    logger.debug(f"Handling get_prompt request for {request.params.name}")
    prompt = next((p for p in prompts if p.name == request.params.name), None)
    if not prompt:
        logger.error(f"Prompt '{request.params.name}' not found")
        return ServerResult(
            root=GetPromptResult(
                messages=[{"role": "system", "content": {"type": "text", "text": "Prompt not found"}}]
            )
        )
    try:
        messages = prompt.messages(request.params.arguments or {})
        logger.debug(f"Generated messages: {messages}")
        return ServerResult(root=GetPromptResult(messages=messages))
    except Exception as e:
        logger.error(f"Error generating prompt: {e}", exc_info=True)
        return ServerResult(
            root=GetPromptResult(
                messages=[{"role": "system", "content": {"type": "text", "text": f"Prompt error: {str(e)}"}}]
            )
        )

async def list_resources(request: ListResourcesRequest) -> ServerResult:
    logger.debug("Handling list_resources request")
    logger.debug(f"Resources list length: {len(resources)}")
    return ServerResult(
        root=ListResourcesResult(
            resources=resources,
            resourceTemplates=[]
        )
    )

async def read_resource(request: ReadResourceRequest) -> ServerResult:
    logger.debug(f"Handling read_resource request for {request.params.uri}")
    global openapi_spec_data
    resource = next((r for r in resources if r.uri == request.params.uri), None)
    if not resource or request.params.uri != "file:///openapi_spec.json":
        logger.error(f"Resource '{request.params.uri}' not found")
        return ServerResult(
            root=ReadResourceResult(
                contents=[{"type": "text", "content": "Resource not found"}]
            )
        )
    try:
        if not openapi_spec_data:
            logger.error("OpenAPI spec data not loaded")
            return ServerResult(
                root=ReadResourceResult(
                    contents=[{"type": "text", "content": "Spec data unavailable"}]
                )
            )
        spec_json = json.dumps(openapi_spec_data, indent=2)
        logger.debug(f"Serving spec JSON: {spec_json[:50]}...")
        return ServerResult(
            root=ReadResourceResult(
                contents=[{"type": "text", "content": spec_json}]
            )
        )
    except Exception as e:
        logger.error(f"Error reading resource: {e}", exc_info=True)
        return ServerResult(
            root=ReadResourceResult(
                contents=[{"type": "text", "content": f"Resource error: {str(e)}"}]
            )
        )

def register_functions(spec: Dict) -> List[Tool]:
    """Register tools from OpenAPI spec."""
    global tools, openapi_spec_data
    openapi_spec_data = spec
    logger.debug("Clearing previously registered tools")
    tools.clear()
    if not spec or 'paths' not in spec:
        logger.error("No valid paths in OpenAPI spec.")
        return tools
    logger.debug(f"Spec paths: {list(spec['paths'].keys())}")
    filtered_paths = {path: item for path, item in spec['paths'].items() if is_tool_whitelisted(path)}
    logger.debug(f"Filtered paths: {list(filtered_paths.keys())}")
    if not filtered_paths:
        logger.warning("No whitelisted paths found in OpenAPI spec.")
        return tools
    for path, path_item in filtered_paths.items():
        if not path_item:
            logger.debug(f"Empty path item for {path}")
            continue
        for method, operation in path_item.items():
            if method.lower() not in ['get', 'post', 'put', 'delete', 'patch']:
                logger.debug(f"Skipping unsupported method {method} for {path}")
                continue
            try:
                raw_name = f"{method.upper()} {path}"
                function_name = normalize_tool_name(raw_name)
                description = operation.get('summary', operation.get('description', 'No description available'))
                input_schema = {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False
                }
                parameters = operation.get('parameters', [])
                for param in parameters:
                    param_name = param.get('name')
                    param_in = param.get('in')
                    if param_in in ['path', 'query']:
                        param_type = param.get('schema', {}).get('type', 'string')
                        schema_type = param_type if param_type in ['string', 'integer', 'boolean', 'number'] else 'string'
                        input_schema['properties'][param_name] = {
                            "type": schema_type,
                            "description": param.get('description', f"{param_in} parameter {param_name}")
                        }
                        if param.get('required', False):
                            input_schema['required'].append(param_name)
                tool = Tool(
                    name=function_name,
                    description=description,
                    inputSchema=input_schema,
                    handler=lambda arguments: handle_request(method, path, arguments)
                )
                tools.append(tool)
                logger.debug(f"Registered function: {function_name}")
            except Exception as e:
                logger.error(f"Error registering function for {method.upper()} {path}: {e}", exc_info=True)
    logger.info(f"Registered {len(tools)} functions from OpenAPI spec.")
    return tools

def lookup_operation_details(function_name: str, spec: Dict) -> Dict or None:
    if not spec or 'paths' not in spec:
        return None
    for path, path_item in spec['paths'].items():
        for method, operation in path_item.items():
            if method.lower() not in ['get', 'post', 'put', 'delete', 'patch']:
                continue
            raw_name = f"{method.upper()} {path}"
            current_function_name = normalize_tool_name(raw_name)
            if current_function_name == function_name:
                return {"path": path, "method": method.upper(), "operation": operation}
    return None

async def start_server():
    logger.debug("Starting Low-Level MCP server...")
    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            initialization_options=InitializationOptions(
                server_name="AnyOpenAPIMCP-LowLevel",
                server_version="0.1.0",
                capabilities=ServerCapabilities(
                    tools=ToolsCapability(listChanged=True),
                    prompts=PromptsCapability(listChanged=True),
                    resources=ResourcesCapability(listChanged=True)
                ),
            ),
        )

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
        logger.info("OpenAPI specification fetched successfully.")
        logger.debug(f"Full OpenAPI spec: {json.dumps(openapi_spec_data, indent=2)}")
        register_functions(openapi_spec_data)
        logger.debug(f"Tools after registration: {[tool.name for tool in tools]}")
        if not tools:
            logger.critical("No valid tools registered. Shutting down.")
            sys.exit(1)
        mcp.request_handlers[ListToolsRequest] = list_tools
        mcp.request_handlers[CallToolRequest] = dispatcher_handler
        mcp.request_handlers[ListPromptsRequest] = list_prompts
        mcp.request_handlers[GetPromptRequest] = get_prompt
        mcp.request_handlers[ListResourcesRequest] = list_resources
        mcp.request_handlers[ReadResourceRequest] = read_resource
        logger.debug("All handlers registered.")
        asyncio.run(start_server())
    except KeyboardInterrupt:
        logger.debug("MCP server shutdown initiated by user.")
    except Exception as e:
        logger.critical(f"Failed to start MCP server: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    run_server()
