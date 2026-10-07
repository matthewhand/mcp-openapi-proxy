import pytest
from types import SimpleNamespace
from mcp_openapi_proxy import handlers
from mcp import types

class DummyLogger:
    def debug(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
    def critical(self, *args, **kwargs): pass

@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    monkeypatch.setattr(handlers, "logger", DummyLogger())

def setup_openapi_spec_data():
    # Minimal valid OpenAPI spec for testing
    return {
        "paths": {
            "/test": {
                "get": {
                    "operationId": "test_operation",
                    "parameters": [],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
        "servers": [{"url": "http://localhost"}]
    }

import pytest
from types import SimpleNamespace
from mcp_openapi_proxy import handlers
from mcp import types

class DummyLogger:
    def debug(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
    def critical(self, *args, **kwargs): pass

@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    monkeypatch.setattr(handlers, "logger", DummyLogger())

def setup_openapi_spec_data():
    # Minimal valid OpenAPI spec for testing
    return {
        "paths": {
            "/test": {
                "get": {
                    "operationId": "test_operation",
                    "parameters": [],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
        "servers": [{"url": "http://localhost"}]
    }

@pytest.mark.asyncio
async def test_dispatcher_handler_unknown_function(monkeypatch):
    handlers.tools.clear()
    dummy_request = SimpleNamespace(params=SimpleNamespace(name="nonexistent", arguments={}))
    result = await handlers.dispatcher_handler(dummy_request)
    assert isinstance(result, types.CallToolResult)
    assert result.content[0].text == "Unknown function requested"
    assert not result.isError

@pytest.mark.asyncio
async def test_dispatcher_handler_no_spec(monkeypatch):
    handlers.tools.clear()
    handlers.tools.append(SimpleNamespace(name="test", __dict__={}))
    dummy_request = SimpleNamespace(params=SimpleNamespace(name="test", arguments={}))
    handlers.openapi_spec_data = None
    result = await handlers.dispatcher_handler(dummy_request)
    assert isinstance(result, types.CallToolResult)
    assert result.content[0].text == "OpenAPI spec not loaded"
    assert result.isError

@pytest.mark.asyncio
async def test_dispatcher_handler_missing_operation(monkeypatch):
    handlers.tools.clear()
    handlers.tools.append(SimpleNamespace(name="test", __dict__={}))
    dummy_request = SimpleNamespace(params=SimpleNamespace(name="test", arguments={}))
    handlers.openapi_spec_data = setup_openapi_spec_data()
    # Patch lookup_operation_details to return None
    monkeypatch.setattr(handlers, "lookup_operation_details", lambda name, spec: None)
    result = await handlers.dispatcher_handler(dummy_request)
    assert isinstance(result, types.CallToolResult)
    assert "Could not find OpenAPI operation" in result.content[0].text
    assert not result.isError

@pytest.mark.asyncio
async def test_dispatcher_handler_missing_required_path_parameters(monkeypatch):
    handlers.tools.clear()
    handlers.tools.append(SimpleNamespace(name="test", __dict__={}))
    dummy_request = SimpleNamespace(params=SimpleNamespace(name="test", arguments={}))
    handlers.openapi_spec_data = setup_openapi_spec_data()
    # Patch lookup_operation_details to return a dummy operation with a required path param
    operation_details = {
        "operation": {"parameters": [{"name": "foo", "in": "path", "required": True}]},
        "method": "GET",
        "path": "/test/{foo}",
        "original_path": "/test/{foo}",
    }
    monkeypatch.setattr(handlers, "lookup_operation_details", lambda name, spec: operation_details)
    result = await handlers.dispatcher_handler(dummy_request)
    assert isinstance(result, types.CallToolResult)
    assert "missing parameter" in result.content[0].text.lower()

@pytest.mark.asyncio
async def test_dispatcher_handler_path_format_exception(monkeypatch):
    handlers.tools.clear()
    handlers.tools.append(SimpleNamespace(name="test", __dict__={}))
    dummy_request = SimpleNamespace(params=SimpleNamespace(name="test", arguments={"foo": object()}))
    handlers.openapi_spec_data = setup_openapi_spec_data()
    operation_details = {
        "operation": {"parameters": [{"name": "foo", "in": "path", "required": True}]},
        "method": "GET",
        "path": "/test/{foo}",
        "original_path": "/test/{foo}",
    }
    monkeypatch.setattr(handlers, "lookup_operation_details", lambda name, spec: operation_details)
    result = await handlers.dispatcher_handler(dummy_request)
    assert isinstance(result, types.CallToolResult)
    assert "network fail" in result.content[0].text.lower() or "error" in result.content[0].text.lower()

@pytest.mark.asyncio
async def test_dispatcher_handler_network_error(monkeypatch):
    handlers.tools.clear()
    handlers.tools.append(SimpleNamespace(name="test", __dict__={}))
    dummy_request = SimpleNamespace(params=SimpleNamespace(name="test", arguments={"foo": "bar"}))
    handlers.openapi_spec_data = setup_openapi_spec_data()
    operation_details = {
        "operation": {"parameters": []},
        "method": "GET",
        "path": "/test",
        "original_path": "/test",
    }
    monkeypatch.setattr(handlers, "lookup_operation_details", lambda name, spec: operation_details)
    monkeypatch.setattr(handlers.requests, "request", lambda **kwargs: (_ for _ in ()).throw(Exception("Network fail")))
    result = await handlers.dispatcher_handler(dummy_request)
    assert isinstance(result, types.CallToolResult)
    assert "network fail" in result.content[0].text.lower() or "error" in result.content[0].text.lower()

@pytest.mark.asyncio
async def test_read_resource_invalid_uri():
    req = SimpleNamespace(params=SimpleNamespace(uri="file:///not_spec.json"))
    result = await handlers.read_resource(req)
    assert hasattr(result, "contents")
    # Accept either an error message or a JSON string
    text = result.contents[0].text
    assert "not found" in text.lower() or "spec unavailable" in text.lower() or text.strip().startswith("{")

@pytest.mark.asyncio
async def test_read_resource_file_error(monkeypatch, tmp_path):
    file_path = tmp_path / "badfile.json"
    file_path.write_text("{}")
    file_path.chmod(0o000)
    monkeypatch.setenv("OPENAPI_SPEC_URL", f"file://{file_path}")
    handlers.openapi_spec_data = None
    req = SimpleNamespace(params=SimpleNamespace(uri="file:///openapi_spec.json"))
    try:
        result = await handlers.read_resource(req)
        assert hasattr(result, "contents")
        assert result.contents[0].text is not None
    finally:
        file_path.chmod(0o644)

@pytest.mark.asyncio
async def test_list_prompts_empty():
    handlers.prompts.clear()
    req = SimpleNamespace(params=None)
    result = await handlers.list_prompts(req)
    assert hasattr(result, "prompts")
    assert result.prompts == []

@pytest.mark.asyncio
async def test_get_prompt_malformed():
    handlers.prompts.clear()
    handlers.prompts.append(SimpleNamespace(name=None, description=None))
    req = SimpleNamespace(params=SimpleNamespace(name=None))
    result = await handlers.get_prompt(req)
    assert hasattr(result, "messages")

@pytest.mark.asyncio
async def test_get_prompt_exception(monkeypatch):
    handlers.prompts.clear()
    handlers.prompts.append(SimpleNamespace(name="foo", description=None, messages=lambda args: (_ for _ in ()).throw(Exception("fail"))))
    req = SimpleNamespace(params=SimpleNamespace(name="foo"))
    result = await handlers.get_prompt(req)
    assert hasattr(result, "messages")
    assert any("fail" in str(m.content.text) for m in result.messages)

    handlers.tools.clear()
    handlers.tools.append(SimpleNamespace(name="test", __dict__={}))
    dummy_request = SimpleNamespace(params=SimpleNamespace(name="test", arguments={}))
    handlers.openapi_spec_data = setup_openapi_spec_data()
    # Patch lookup_operation_details to return a dummy operation with a required path param
    operation_details = {
        "operation": {"parameters": [{"name": "foo", "in": "path", "required": True}]},
        "method": "GET",
        "path": "/test/{foo}",
        "original_path": "/test/{foo}"
    }
    monkeypatch.setattr(handlers, "lookup_operation_details", lambda name, spec: operation_details)
    # Patch openapi_spec_data['paths'] to include a required path parameter
    orig_paths = handlers.openapi_spec_data["paths"]
    handlers.openapi_spec_data["paths"] = {"/test/{foo}": {"parameters": [{"name": "foo", "in": "path", "required": True}]}}
    result = await handlers.dispatcher_handler(dummy_request)
    assert isinstance(result, types.CallToolResult)
    assert (
        "Missing required path parameters" in result.content[0].text or
        "Missing parameter" in result.content[0].text
    )
    assert not result.isError
    # Restore
    handlers.openapi_spec_data["paths"] = orig_paths

@pytest.mark.asyncio
async def test_list_tools_error_handling(monkeypatch):
    from mcp_openapi_proxy import handlers
    # Patch the logger to suppress output
    monkeypatch.setattr(handlers, "logger", type("DummyLogger", (), {"debug": lambda *a, **k: None, "error": lambda *a, **k: None, "critical": lambda *a, **k: None})())
    # Patch tools to cause an error
    monkeypatch.setattr(handlers, "tools", None)
    class DummyRequest:
        pass
    try:
        await handlers.list_tools(DummyRequest())
    except Exception as e:
        assert "object of type 'NoneType' has no len" in str(e) or "NoneType" in str(e)

@pytest.mark.asyncio
async def test_dispatcher_handler_missing_base_url(monkeypatch):
    from mcp_openapi_proxy import handlers, types
    handlers.tools.clear()
    tool = types.Tool(name="test", description="desc", inputSchema={})
    handlers.tools.append(tool)
    dummy_request = type("Dummy", (), {"params": type("Params", (), {"name": "test", "arguments": {}})})()
    handlers.openapi_spec_data = {"paths": {"/test": {"get": {"operationId": "test_operation", "parameters": [], "responses": {"200": {"description": "OK"}}}}}, "servers": []}
    monkeypatch.setattr(handlers, "lookup_operation_details", lambda name, spec: {"operation": {"parameters": []}, "method": "GET", "path": "/test", "original_path": "/test"})
    monkeypatch.setattr(handlers, "handle_auth", lambda op: {})
    monkeypatch.setattr(handlers, "get_additional_headers", lambda: {})
    monkeypatch.setattr(handlers, "strip_parameters", lambda args: args.items())
    monkeypatch.setattr(handlers, "build_base_url", lambda spec: "")
    result = await handlers.dispatcher_handler(dummy_request)
    assert type(result).__name__ == "CallToolResult"
    assert "No base URL defined" in result.content[0].text

@pytest.mark.asyncio
async def test_dispatcher_handler_missing_required_path_params(monkeypatch):
    from mcp_openapi_proxy import handlers, types
    handlers.tools.clear()
    tool = types.Tool(name="test", description="desc", inputSchema={})
    handlers.tools.append(tool)
    dummy_request = type("Dummy", (), {"params": type("Params", (), {"name": "test", "arguments": {}})})()
    handlers.openapi_spec_data = {"paths": {"/test/{id}": {"get": {"operationId": "test_operation", "parameters": [{"name": "id", "in": "path", "required": True}], "responses": {"200": {"description": "OK"}}}}}, "servers": [ { "url": "http://example.com" } ]}
    monkeypatch.setattr(handlers, "lookup_operation_details", lambda name, spec: {"operation": {"parameters": [{"name": "id", "in": "path", "required": True}]}, "method": "GET", "path": "/test/{id}", "original_path": "/test/{id}"})
    monkeypatch.setattr(handlers, "handle_auth", lambda op: {})
    monkeypatch.setattr(handlers, "get_additional_headers", lambda: {})
    monkeypatch.setattr(handlers, "strip_parameters", lambda args: args.items())
    monkeypatch.setattr(handlers, "build_base_url", lambda spec: "http://example.com")
    result = await handlers.dispatcher_handler(dummy_request)
    assert type(result).__name__ == "CallToolResult"
    assert "Missing parameter" in result.content[0].text
    handlers.tools.clear()

@pytest.mark.asyncio
async def test_dispatcher_handler_request_exception(monkeypatch):
    from mcp_openapi_proxy import handlers, types
    handlers.tools.clear()
    tool = types.Tool(name="test", description="desc", inputSchema={})
    handlers.tools.append(tool)
    dummy_request = type("Dummy", (), {"params": type("Params", (), {"name": "test", "arguments": {"id": 1}})})()
    handlers.openapi_spec_data = {"paths": {"/test/{id}": {"get": {"operationId": "test_operation", "parameters": [{"name": "id", "in": "path", "required": True}], "responses": {"200": {"description": "OK"}}}}}, "servers": [ { "url": "http://example.com" } ]}
    monkeypatch.setattr(handlers, "lookup_operation_details", lambda name, spec: {"operation": {"parameters": [{"name": "id", "in": "path", "required": True}]}, "method": "GET", "path": "/test/{id}", "original_path": "/test/{id}"})
    monkeypatch.setattr(handlers, "handle_auth", lambda op: {})
    monkeypatch.setattr(handlers, "get_additional_headers", lambda: {})
    monkeypatch.setattr(handlers, "strip_parameters", lambda args: args.items())
    monkeypatch.setattr(handlers, "build_base_url", lambda spec: "http://example.com")
    class DummyRequests:
        class exceptions:
            class RequestException(Exception):
                pass
        @staticmethod
        def request(**kwargs):
            class DummyResponse:
                def raise_for_status(self):
                    raise DummyRequests.exceptions.RequestException("request failed")
                @property
                def text(self):
                    return ""
            return DummyResponse()
    monkeypatch.setattr(handlers, "requests", DummyRequests)
    result = await handlers.dispatcher_handler(dummy_request)
    assert type(result).__name__ == "CallToolResult"
    assert "request failed" in result.content[0].text

    handlers.tools.clear()
    dummy_tool = {"name": "dummy_tool", "description": "desc", "inputSchema": {}}
    handlers.tools.append(dummy_tool)
    req = SimpleNamespace(params=None)
    result = await handlers.list_tools(req)
    assert hasattr(result, "tools")
    assert any(tool.name == "dummy_tool" for tool in result.tools)
    handlers.tools.clear()

@pytest.mark.asyncio
async def test_list_resources_populates_when_empty():
    handlers.resources.clear()
    req = SimpleNamespace(params=None)
    result = await handlers.list_resources(req)
    assert hasattr(result, "resources")
    assert len(result.resources) > 0
    assert result.resources[0].name == "spec_file"

@pytest.mark.asyncio
async def test_list_resources_returns_existing():
    dummy_resource = types.Resource(name="foo", uri="file:///bar", description="desc")
    handlers.resources.clear()
    handlers.resources.append(dummy_resource)
    req = SimpleNamespace(params=None)
    result = await handlers.list_resources(req)
    assert dummy_resource in result.resources

@pytest.mark.asyncio
async def test_read_resource_with_loaded_spec(monkeypatch):
    handlers.openapi_spec_data = {"foo": "bar"}
    req = SimpleNamespace(params=SimpleNamespace(uri="file:///openapi_spec.json"))
    result = await handlers.read_resource(req)
    assert hasattr(result, "contents")
    assert "foo" in result.contents[0].text

@pytest.mark.asyncio
async def test_read_resource_no_spec_env(monkeypatch):
    handlers.openapi_spec_data = None
    monkeypatch.setenv("OPENAPI_SPEC_URL", "")
    req = SimpleNamespace(params=SimpleNamespace(uri="file:///openapi_spec.json"))
    result = await handlers.read_resource(req)
    assert "Spec unavailable" in result.contents[0].text

@pytest.mark.asyncio
async def test_read_resource_fetch_failure(monkeypatch):
    handlers.openapi_spec_data = None
    monkeypatch.setenv("OPENAPI_SPEC_URL", "dummy_url")
    monkeypatch.setattr(handlers, "fetch_openapi_spec", lambda url: None)
    req = SimpleNamespace(params=SimpleNamespace(uri="file:///openapi_spec.json"))
    result = await handlers.read_resource(req)
    assert "Spec data unavailable" in result.contents[0].text

@pytest.mark.asyncio
async def test_read_resource_exception(monkeypatch):
    monkeypatch.setattr(handlers, "openapi_spec_data", property(lambda self: (_ for _ in ()).throw(Exception("fail"))))
    req = SimpleNamespace(params=SimpleNamespace(uri="file:///openapi_spec.json"))
    result = await handlers.read_resource(req)
    assert "Resource error" in result.contents[0].text

@pytest.mark.asyncio
async def test_list_prompts():
    handlers.prompts.clear()
    dummy_prompt = types.Prompt(name="foo", description="desc")
    handlers.prompts.append(dummy_prompt)
    req = SimpleNamespace(params=None)
    result = await handlers.list_prompts(req)
    assert hasattr(result, "prompts")
    assert dummy_prompt in result.prompts

@pytest.mark.asyncio
async def test_get_prompt_found():
    handlers.prompts.clear()
    dummy_prompt = types.Prompt(name="foo", description="desc")
    handlers.prompts.append(dummy_prompt)
    req = SimpleNamespace(params=SimpleNamespace(name="foo"))
    result = await handlers.get_prompt(req)
    assert hasattr(result, "messages")
    assert "OpenAPI spec defines endpoints" in result.messages[0].content.text

@pytest.mark.asyncio
async def test_get_prompt_not_found():
    handlers.prompts.clear()
    req = SimpleNamespace(params=SimpleNamespace(name="notfound"))
    result = await handlers.get_prompt(req)
    assert hasattr(result, "messages")
    assert "Prompt not found" in result.messages[0].content.text

@pytest.mark.asyncio
async def test_get_prompt_exception(monkeypatch):
    handlers.prompts.clear()
    dummy_prompt = types.Prompt(name="foo", description="desc")
    handlers.prompts.append(dummy_prompt)
    req = SimpleNamespace(params=SimpleNamespace(name="foo"))
    orig_text_content = handlers.types.TextContent
    def raise_text_content(*a, **kw):
        monkeypatch.setattr(handlers.types, "TextContent", orig_text_content)  # restore for except block
        raise Exception("fail")
    monkeypatch.setattr(handlers.types, "TextContent", raise_text_content)
    result = await handlers.get_prompt(req)
    assert hasattr(result, "messages")
    assert "Prompt error" in result.messages[0].content.text
