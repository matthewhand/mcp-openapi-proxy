"""Public operation semantics must survive simple-mode catalog construction."""
import json
import pytest
from mcp_openapi_proxy import server_fastmcp as fast, openapi


@pytest.mark.parametrize("method,path,operation,expected", [
    ("get", "/read", {"summary":"Friendly inventory title", "operationId":"opRead1"},
     {"title":"Friendly inventory title", "readOnlyHint":True, "idempotentHint":True}),
    ("post", "/search", {"summary":"Search inventory", "operationId":"op123"},
     {"title":"Search inventory", "readOnlyHint":True, "idempotentHint":True}),
    ("post", "/submit", {"summary":"Create a new record", "operationId":"searchRecords"},
     {"title":"Create a new record", "destructiveHint":True}),
])
def test_original_operation_controls_catalog_hints(monkeypatch,method,path,operation,expected):
    document={"openapi":"3.0.3","info":{"title":"Fixture","version":"1"},
              "paths":{path:{method:operation}}}
    monkeypatch.setenv("OPENAPI_SPEC_URL","file:///fictional-only.json")
    monkeypatch.setattr(fast,"fetch_openapi_spec",lambda _:document)
    catalog=json.loads(fast.list_functions())
    item=next(row for row in catalog if row["path"]==path)
    assert item["annotations"]==expected
    lowlevel_tools=openapi.register_functions(document)
    assert len(lowlevel_tools)==1
    assert lowlevel_tools[0].annotations.model_dump(by_alias=True,exclude_none=True)==expected
    assert item["handle"]==item["name"]
    helpers=[row for row in catalog if row["path"] is None]
    assert len(helpers)==4
    assert all(row["annotations"]["readOnlyHint"] is True for row in helpers)
    assert all(row["annotations"]["idempotentHint"] is True for row in helpers)


@pytest.mark.asyncio
async def test_additional_resource_failure_hides_configured_path(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from mcp import types
    from mcp_openapi_proxy import server_lowlevel as low
    private_path=tmp_path/"SYNTHETIC_PRIVATE_RESOURCE_LOCATION"/"missing.md"
    monkeypatch.setattr(low,"ADDITIONAL_RESOURCES",{"guide":str(private_path)})
    monkeypatch.setattr(low,"resources",[types.Resource(name="guide",uri="file:///guide")])
    result=await low.read_resource(None,SimpleNamespace(uri="file:///guide"))
    assert result.contents[0].text=="Resource unavailable"
    assert "SYNTHETIC_PRIVATE_RESOURCE_LOCATION" not in str(result)
