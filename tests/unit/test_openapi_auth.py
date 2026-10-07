import os
import pytest
from mcp_openapi_proxy.openapi import handle_auth

def test_handle_auth_no_env(monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_KEY_HEADER", raising=False)
    op = {"security": []}
    headers = handle_auth(op)
    assert headers == {}

def test_handle_auth_with_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setenv("API_AUTH_TYPE", "api-key")
    monkeypatch.setenv("API_AUTH_HEADER", "X-API-KEY")
    op = {"security": [{"api_key": []}]}
    headers = handle_auth(op)
    assert headers == {"X-API-KEY": "secret"}
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("API_AUTH_TYPE", raising=False)
    monkeypatch.delenv("API_AUTH_HEADER", raising=False)

def test_handle_auth_with_default_header(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.delenv("API_AUTH_TYPE", raising=False)
    monkeypatch.delenv("API_AUTH_HEADER", raising=False)
    op = {"security": [{"api_key": []}]}
    headers = handle_auth(op)
    assert headers == {"Authorization": "Bearer secret"}
    monkeypatch.delenv("API_KEY", raising=False)

def test_handle_auth_no_security(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.delenv("API_AUTH_TYPE", raising=False)
    monkeypatch.delenv("API_AUTH_HEADER", raising=False)
    op = {}
    headers = handle_auth(op)
    assert headers == {"Authorization": "Bearer secret"}
    monkeypatch.delenv("API_KEY", raising=False)
