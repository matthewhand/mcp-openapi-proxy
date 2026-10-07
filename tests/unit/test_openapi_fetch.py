"""
Unit tests for fetch_openapi_spec in mcp_openapi_proxy.openapi, focusing on curl validation logic.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from mcp_openapi_proxy.openapi import fetch_openapi_spec


@pytest.fixture
def mock_requests_get():
    with patch("requests.get") as mock_get:
        yield mock_get


@pytest.fixture
def mock_curl_success():
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "HTTP/2 200 OK\r\n"
        mock_run.return_value = mock_proc
        yield mock_run


@pytest.fixture
def mock_curl_fail():
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "HTTP/2 404 Not Found\r\n"
        mock_run.return_value = mock_proc
        yield mock_run


def test_fetch_openapi_spec_curl_success(mock_requests_get, mock_curl_success):
    # Simulate a successful curl validation and fetch
    mock_response = MagicMock()
    mock_response.text = '{"openapi": "3.0.0", "info": {"title": "Test"}}'
    mock_response.raise_for_status = MagicMock()
    mock_requests_get.return_value = mock_response
    spec = fetch_openapi_spec("https://example.com/openapi.json")
    assert spec is not None
    assert spec["openapi"] == "3.0.0"
    assert spec["info"]["title"] == "Test"


def test_fetch_openapi_spec_curl_fail(mock_requests_get, mock_curl_fail):
    # Simulate a failed curl validation (non-200)
    spec = fetch_openapi_spec("https://example.com/openapi.json")
    assert spec is None
    # requests.get should not be called if curl fails
    assert not mock_requests_get.called


def test_fetch_openapi_spec_file_url(tmp_path):
    # Should not call curl for file:// URLs
    file = tmp_path / "spec.json"
    file.write_text('{"openapi": "3.0.0", "info": {"title": "FileTest"}}')
    with patch("subprocess.run") as mock_run:
        spec = fetch_openapi_spec(f"file://{file}")
        assert spec is not None
        assert spec["info"]["title"] == "FileTest"
        assert not mock_run.called
