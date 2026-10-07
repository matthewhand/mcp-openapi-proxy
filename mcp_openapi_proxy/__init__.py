"""
Main entry point for the mcp_openapi_proxy package when imported or run as script.

Chooses between Low-Level Server (dynamic tools from OpenAPI spec) and
FastMCP Server (static tools) based on OPENAPI_SIMPLE_MODE env var.
"""

import os
import sys
from dotenv import load_dotenv
from mcp_openapi_proxy.logging_setup import setup_logging

# Load environment variables from .env if present
load_dotenv()


def main():
    """
    Main entry point for mcp_openapi_proxy.

    Selects and runs either:
    - Low-Level Server (default, dynamic tools from OpenAPI spec)
    - FastMCP Server (OPENAPI_SIMPLE_MODE=true, static tools)
    """
    DEBUG = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
    logger = setup_logging(debug=DEBUG)

    logger.debug("Starting mcp_openapi_proxy package entry point.")

    OPENAPI_SIMPLE_MODE = os.getenv("OPENAPI_SIMPLE_MODE", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    if OPENAPI_SIMPLE_MODE:
        logger.debug("OPENAPI_SIMPLE_MODE is enabled. Launching FastMCP Server.")
        from mcp_openapi_proxy.server_fastmcp import run_simple_server

        selected_server = run_simple_server
    else:
        logger.debug("OPENAPI_SIMPLE_MODE is disabled. Launching Low-Level Server.")
        from mcp_openapi_proxy.server_lowlevel import run_server

        selected_server = run_server

    try:
        selected_server()
    except Exception as e:
        logger.critical(
            "Unhandled exception occurred while running the server.", exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
