import os
import json
import tempfile
import pytest
from mcp_openapi_proxy.utils import fetch_openapi_spec


def test_fetch_spec_json():
    # Create a temporary JSON file with a simple OpenAPI spec
    spec_content = '{"openapi": "3.0.0", "paths": {"/test": {}}}'
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write(spec_content)
        tmp.flush()
        file_url = "file://" + tmp.name
    result = fetch_openapi_spec(file_url)
    os.unlink(tmp.name)
    assert result is not None, "Failed to parse JSON spec"
    assert (
        "openapi" in result or "swagger" in result
    ), "Parsed spec does not contain version key"


def test_fetch_spec_yaml():
    # Set envvar to force YAML parsing
    os.environ["OPENAPI_SPEC_FORMAT"] = "yaml"
    spec_content = "openapi: 3.0.0\npaths:\n  /test: {}\n"
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write(spec_content)
        tmp.flush()
        file_url = "file://" + tmp.name
    result = fetch_openapi_spec(file_url)
    os.unlink(tmp.name)
    # Clean up the environment variable after test
    os.environ.pop("OPENAPI_SPEC_FORMAT", None)
    assert result is not None, "Failed to parse YAML spec"
    assert (
        "openapi" in result or "swagger" in result
    ), "Parsed spec does not contain version key"
