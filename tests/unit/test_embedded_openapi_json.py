import json
from mcp_openapi_proxy.utils import build_base_url
import pytest


def test_embedded_openapi_json_valid():
    # Embedded sample valid OpenAPI spec
    sample_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Sample API", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "summary": "List all pets",
                    "responses": {
                        "200": {
                            "description": "An array of pets",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    # Simulate retrieval by converting to JSON and parsing it back
    spec_json = json.dumps(sample_spec)
    parsed_spec = json.loads(spec_json)
    # Assert that the spec has either an "openapi" or "swagger" key and non-empty "paths"
    assert (
        "openapi" in parsed_spec or "swagger" in parsed_spec
    ), "Spec must contain 'openapi' or 'swagger' key"
    assert (
        "paths" in parsed_spec and parsed_spec["paths"]
    ), "Spec must contain non-empty 'paths' object"


def test_build_base_url_with_placeholder(monkeypatch):
    monkeypatch.delenv("SERVER_URL_OVERRIDE", raising=False)
    # Test that build_base_url handles placeholders gracefully
    spec_with_placeholder = {
        "openapi": "3.0.0",
        "servers": [{"url": "https://api.{tenant}.com"}],
        "paths": {"/test": {"get": {"summary": "Test endpoint"}}},
    }
    url = build_base_url(spec_with_placeholder)
    assert (
        url == "https://api.{tenant}.com"
    ), "build_base_url should return the spec URL with placeholder intact"
