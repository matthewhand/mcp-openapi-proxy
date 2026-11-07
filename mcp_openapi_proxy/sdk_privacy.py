"""Application-owned SDK2 failure boundary, preserving native response contracts."""
import base64
import pydantic_core
from mcp import types
from mcp.shared.exceptions import MCPError
from mcp.server.mcpserver import Context

_SAFE_ERRORS = frozenset({
    "Unknown OpenAPI operation", "function_name is required",
    "Stale or cross-spec operation registration",
    "Invalid or unsafe path parameters", "Operation not authorized",
    "OpenAPI operation no longer authorized", "Upstream request failed",
    "Upstream redirect refused", "OPENAPI_SPEC_URL is not configured",
    "OpenAPI specification unavailable or invalid", "Prompt not found",
    "Resource not found", "name parameter required", "uri parameter required",
})


def _failure(message="Tool request failed"):
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], is_error=True)


def _error(message):
    raise MCPError(code=types.INVALID_PARAMS, message=message)


def install_mcpserver_guards(server):
    """Use SDK2 registration hooks, retaining context, MRTR and native metadata."""
    core = server._lowlevel_server

    def context(ctx, params):
        return Context(request_context=ctx, mcp_server=server, input_params=params,
                       subscriptions=server._subscriptions)

    async def call_tool(ctx, params):
        tool = {t.name: t for t in server._tool_manager.list_tools()}.get(params.name)
        if tool is None:
            return _failure("Unknown tool")
        try:
            # Same SDK model/pre-parser; extra accepted fields and JSON object
            # arguments remain accepted. No validation text enters SDK logging.
            tool.fn_metadata.validate_arguments(params.arguments or {})
        except Exception:
            return _failure("Invalid tool arguments")
        try:
            return await server.call_tool(params.name, params.arguments or {},
                                          context(ctx, params))
        except Exception as error:
            message = str(error)
            prefix = f"Error executing tool {params.name}: "
            if message.startswith(prefix):
                message = message[len(prefix):]
            return _failure(message if message in _SAFE_ERRORS else "Tool request failed")

    async def read_resource(ctx, params):
        uri = str(params.uri)
        known = {str(item.uri) for item in server._resource_manager.list_resources()}
        templates = server._resource_manager.list_templates()
        if uri not in known and not any(item.matches(uri) is not None for item in templates):
            _error("Resource not found")
        try:
            # SDK2.0's outer read_resource wrapper logs exception chains. Use
            # the same native manager/resource path inside our failure boundary.
            resource = await server._resource_manager.get_resource(
                params.uri, context(ctx, params))
            if isinstance(resource, types.InputRequiredResult):
                return resource
            content = await resource.read()
            if not isinstance(content, (str, bytes)):
                raise TypeError("Invalid resource content")
            if isinstance(content, bytes):
                contents = [types.BlobResourceContents(
                    uri=params.uri, blob=base64.b64encode(content).decode(),
                    mime_type=resource.mime_type or "application/octet-stream",
                    _meta=resource.meta)]
            else:
                contents = [types.TextResourceContents(
                    uri=params.uri, text=content,
                    mime_type=resource.mime_type or "text/plain",
                    _meta=resource.meta)]
            return types.ReadResourceResult(contents=contents)
        except Exception:
            _error("Resource operation failed")

    async def get_prompt(ctx, params):
        prompt = {item.name: item for item in server._prompt_manager.list_prompts()}.get(params.name)
        if prompt is None:
            _error("Prompt not found")
        try:
            # Native render preserves validation, context injection, media and
            # MRTR. Avoid SDK2.0's get_prompt wrapper, which logs private errors.
            rendered = await prompt.render(params.arguments, context(ctx, params))
            if isinstance(rendered, types.InputRequiredResult):
                return rendered
            return types.GetPromptResult(
                description=prompt.description,
                messages=pydantic_core.to_jsonable_python(rendered))
        except Exception:
            _error("Prompt operation failed")

    core.add_request_handler("tools/call", types.CallToolRequestParams, call_tool)
    core.add_request_handler("resources/read", types.ReadResourceRequestParams, read_resource)
    core.add_request_handler("prompts/get", types.GetPromptRequestParams, get_prompt)
