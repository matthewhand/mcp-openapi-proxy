"""Regression (issue #52): YAML specs with unquoted datetime example values
must not produce non-JSON-serializable datetime objects."""
import datetime
import json
import os

import yaml


def test_yaml_load_safe_keeps_timestamp_as_string():
    from mcp_openapi_proxy.utils import yaml_load_safe
    data = yaml_load_safe("when: 2015-02-22T20:00:45.000Z\n")
    assert isinstance(data["when"], str)
    # plain SafeLoader would have produced a datetime — prove the difference
    assert isinstance(yaml.safe_load("when: 2015-02-22T20:00:45.000Z\n")["when"],
                      datetime.datetime)


def test_fetch_yaml_spec_with_datetime_is_json_serializable(tmp_path, monkeypatch):
    from mcp_openapi_proxy.utils import fetch_openapi_spec
    spec = (
        "openapi: 3.0.0\n"
        "info: {title: dt, version: 1.0.0}\n"
        "paths:\n"
        "  /x:\n"
        "    get:\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n"
        "          content:\n"
        "            application/json:\n"
        "              example: {created: 2015-02-22T20:00:45.000Z}\n"
    )
    f = tmp_path / "spec.yaml"
    f.write_text(spec)
    monkeypatch.setenv("OPENAPI_SPEC_FORMAT", "yaml")
    monkeypatch.setenv("OPENAPI_SPEC_CACHE_TTL_SECONDS", "0")
    parsed = fetch_openapi_spec(f"file://{f}")
    assert parsed is not None
    # the whole spec must be JSON-serializable (this is what crashed before)
    json.dumps(parsed)
    assert parsed["paths"]["/x"]["get"]["responses"]["200"]["content"]["application/json"]["example"]["created"] == "2015-02-22T20:00:45.000Z"


def test_spec_cache_store_handles_remaining_nonstring(tmp_path, monkeypatch):
    """default=str safety net: caching never crashes even on odd scalars."""
    from mcp_openapi_proxy import utils
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAPI_SPEC_CACHE_TTL_SECONDS", "3600")
    url = "http://example.invalid/s.json"
    utils._spec_cache_store(url, {"d": datetime.datetime(2020, 1, 1)})  # must not raise
    assert utils._spec_cache_load(url) is not None
