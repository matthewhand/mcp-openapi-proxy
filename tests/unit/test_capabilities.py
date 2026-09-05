import pytest


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.delenv("OPENAPI_SPEC_URL", raising=False)
    monkeypatch.setenv("OPENAPI_SPEC_URL", "http://dummy.com")


def test_initialization_options_advertise_enabled_features(mock_env):
    """create_initialization_options reflects ENABLE_* / CAPABILITIES_* flags."""
    from mcp_openapi_proxy.server_lowlevel import (
        _initialization_options,
        PACKAGE_VERSION,
        build_capabilities,
    )

    caps = build_capabilities()
    assert caps.tools is not None
    opts = _initialization_options()
    assert opts.server_version == PACKAGE_VERSION
    assert opts.capabilities.tools is not None
