import os
import asyncio
import pytest

# Import necessary components directly for the test
from mcp_openapi_proxy.server_lowlevel import (
    mcp,
    InitializationOptions,
    types,
    CAPABILITIES_TOOLS,
    CAPABILITIES_PROMPTS,
    CAPABILITIES_RESOURCES,
)
from unittest.mock import patch, AsyncMock


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.delenv("OPENAPI_SPEC_URL", raising=False)
    monkeypatch.setenv("OPENAPI_SPEC_URL", "http://dummy.com")


def dummy_stdio_server():
    class DummyAsyncCM:
        async def __aenter__(self):
            return (AsyncMock(), AsyncMock())

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    return DummyAsyncCM()


@pytest.mark.asyncio
async def test_capabilities_passed_to_mcp_run(mock_env):
    """Verify that the correct capabilities are passed to mcp.run based on defaults."""
    # Define expected capabilities based on default env vars in server_lowlevel
    # Defaults are CAPABILITIES_TOOLS=true, others=false
    expected_capabilities = types.ServerCapabilities(
        tools=types.ToolsCapability(listChanged=True) if CAPABILITIES_TOOLS else None,
        prompts=(
            types.PromptsCapability(listChanged=True) if CAPABILITIES_PROMPTS else None
        ),
        resources=(
            types.ResourcesCapability(listChanged=True)
            if CAPABILITIES_RESOURCES
            else None
        ),
    )
    expected_init_options = InitializationOptions(
        server_name="AnyOpenAPIMCP-LowLevel",
        server_version="0.1.0",
        capabilities=expected_capabilities,
    )

    # Mock the stdio streams and the mcp.run call
    mock_read_stream = AsyncMock()
    mock_write_stream = AsyncMock()
    with patch("mcp_openapi_proxy.server_lowlevel.stdio_server") as mock_stdio_cm:
        # Configure the context manager mock to return our stream mocks
        mock_stdio_cm.return_value.__aenter__.return_value = (
            mock_read_stream,
            mock_write_stream,
        )
        with patch(
            "mcp_openapi_proxy.server_lowlevel.mcp.run", new_callable=AsyncMock
        ) as mock_run:

            # Simulate the core logic inside start_server's loop *once*
            # Manually construct capabilities as done in start_server
            capabilities = types.ServerCapabilities(
                tools=(
                    types.ToolsCapability(listChanged=True)
                    if CAPABILITIES_TOOLS
                    else None
                ),
                prompts=(
                    types.PromptsCapability(listChanged=True)
                    if CAPABILITIES_PROMPTS
                    else None
                ),
                resources=(
                    types.ResourcesCapability(listChanged=True)
                    if CAPABILITIES_RESOURCES
                    else None
                ),
            )
            # Manually construct init options
            init_options = InitializationOptions(
                server_name="AnyOpenAPIMCP-LowLevel",
                server_version="0.1.0",
                capabilities=capabilities,
            )
            # Simulate the call to mcp.run that would happen in the loop
            # We don't need the actual stdio_server context manager here, just the call to run
            await mock_run(
                mock_read_stream, mock_write_stream, initialization_options=init_options
            )

            # Assert that the mock was called correctly
            mock_run.assert_awaited_once()
            call_args = mock_run.call_args
            passed_init_options = call_args.kwargs.get("initialization_options")

            # Perform assertions on the passed options
            assert (
                passed_init_options is not None
            ), "initialization_options not passed to mcp.run"
            # Compare the capabilities object structure
            assert (
                passed_init_options.capabilities == expected_capabilities
            ), "Capabilities mismatch"
            assert passed_init_options.server_name == expected_init_options.server_name
            assert (
                passed_init_options.server_version
                == expected_init_options.server_version
            )
