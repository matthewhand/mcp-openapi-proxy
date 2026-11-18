"""Unit mocks replace the new transport boundary; artifact tests use real workers."""
import pytest
@pytest.fixture(autouse=True)
def unit_dispatch_transport(monkeypatch):
    from mcp_openapi_proxy import server_lowlevel,server_fastmcp,handlers
    from mcp_openapi_proxy.request_security import request_no_redirect
    def sync(**kwargs):
        kwargs.pop("_cancel",None)
        return request_no_redirect(**kwargs)
    async def asynchronous(**kwargs):
        return request_no_redirect(**kwargs)
    monkeypatch.setattr(server_fastmcp,"bounded_request",sync)
    monkeypatch.setattr(server_lowlevel,"bounded_request_async",asynchronous)
    monkeypatch.setattr(handlers,"bounded_request_async",asynchronous)
