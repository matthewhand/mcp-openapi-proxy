"""Shared MCP 2026-07-28 helpers for both server modes.

The proxy is a dual-stack server:
- 2026-07-28 clients send self-contained requests (no initialize, no session).
- Legacy 2025-era clients may still perform initialize over stdio; the SDK
  answers that handshake alongside server/discover.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Tuple

PACKAGE_VERSION = "0.4.0"
SERVER_VERSION = PACKAGE_VERSION
PROTOCOL_VERSION_MODERN = "2026-07-28"
PROTOCOL_VERSION_LEGACY = "2025-11-25"

DEFAULT_LIST_TTL_MS = 60_000
DEFAULT_READ_TTL_MS = 5_000

HEADER_PROTOCOL_VERSION = "MCP-Protocol-Version"
HEADER_METHOD = "Mcp-Method"
HEADER_NAME = "Mcp-Name"
HEADER_SESSION_ID = "Mcp-Session-Id"


def truthy(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes")


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def unpack_handler_args(ctx_or_request: Any, params: Any = None) -> Tuple[Any, Any]:
    """Accept v2 ``(ctx, params)`` or the older request-with-``.params`` object.

    Unit tests and the gateway query-auth wrapper historically called handlers
    with a single request object. Keep that working so monkeypatches and tests
    do not have to special-case the SDK era.
    """
    if params is not None:
        return ctx_or_request, params
    req = ctx_or_request
    if req is not None and hasattr(req, "params"):
        return None, req.params
    return None, req


def transport_name() -> str:
    raw = os.getenv("MCP_TRANSPORT", "stdio").strip().lower().replace("_", "-")
    if raw in ("http", "streamable-http", "streamablehttp"):
        return "streamable-http"
    return "stdio"


def advertised_server_name() -> str:
    """Identity reported in serverInfo / initialize / server/discover.

    Prefer an explicit MCP_SERVER_NAME (gateway instances set this to the
    proxied API: flyio, gpt-terminal-plus, …). Otherwise derive a stable
    slug from OPENAPI_SPEC_URL so two uvx processes are not both called
    OpenApiProxy-LowLevel.
    """
    explicit = (os.getenv("MCP_SERVER_NAME") or os.getenv("OPENAPI_SERVER_NAME") or "").strip()
    if explicit:
        return explicit
    url = (os.getenv("OPENAPI_SPEC_URL") or "").strip()
    if url.startswith("file://"):
        from pathlib import Path

        stem = Path(url[7:].split("?", 1)[0]).stem
        if stem and stem not in (".",):
            return stem
    elif "://" in url:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            return host
    return "openapi-proxy"


def advertised_server_title() -> Optional[str]:
    title = (os.getenv("MCP_SERVER_TITLE") or "").strip()
    return title or None


def advertised_server_description() -> Optional[str]:
    desc = (os.getenv("MCP_SERVER_DESCRIPTION") or "").strip()
    return desc or None


def mcp_host() -> str:
    return os.getenv("MCP_HOST", "127.0.0.1")


def mcp_port() -> int:
    return env_int("MCP_PORT", 8000)


def mcp_path() -> str:
    path = os.getenv("MCP_PATH", "/mcp").strip() or "/mcp"
    if not path.startswith("/"):
        path = "/" + path
    return path


HEALTHZ_PATH = "/healthz"


def healthz_body() -> dict:
    """Process-local health payload. Env only — no spec fetch, no MCP I/O."""
    return {
        "ok": True,
        "name": advertised_server_name(),
        "port": mcp_port(),
    }


async def healthz_endpoint(request: Any):
    """Starlette handler for GET /healthz. Does not enter the MCP request lock."""
    from starlette.responses import JSONResponse

    return JSONResponse(healthz_body())


def healthz_route():
    """Sibling Starlette Route — not mounted under StreamableHTTPSessionManager."""
    from starlette.routing import Route

    return Route(HEALTHZ_PATH, endpoint=healthz_endpoint, methods=["GET"])


def list_ttl_ms() -> int:
    return env_int("MCP_LIST_TTL_MS", DEFAULT_LIST_TTL_MS)


def read_ttl_ms() -> int:
    return env_int("MCP_READ_TTL_MS", DEFAULT_READ_TTL_MS)


def json_response() -> bool:
    return truthy("MCP_JSON_RESPONSE", True)


def transport_security():
    """DNS-rebinding settings for Streamable HTTP.

    Default is protection off so the server can sit behind nginx (the public
    Host header is not 127.0.0.1). Set MCP_ALLOWED_HOSTS to a comma-separated
    allow-list to turn protection back on.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = os.getenv("MCP_ALLOWED_HOSTS", "*").strip()
    if hosts in ("*", ""):
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[h.strip() for h in hosts.split(",") if h.strip()],
        allowed_origins=["*"],
    )


def request_state_security():
    """Optional shared HMAC key so MRTR requestState works across instances.

    Unset MCP_REQUEST_STATE_KEY keeps the SDK process-local default. A shared
    key is required for multi-instance round-robin of mid-call elicitation.
    """
    from mcp.server.request_state import RequestStateSecurity

    key = os.getenv("MCP_REQUEST_STATE_KEY")
    if not key:
        return None
    return RequestStateSecurity(keys=[key])


def cache_hints() -> Mapping[str, Any]:
    from mcp.server import CacheHint

    ttl = list_ttl_ms()
    return {
        "tools/list": CacheHint(ttl_ms=ttl, scope="public"),
        "prompts/list": CacheHint(ttl_ms=ttl, scope="public"),
        "resources/list": CacheHint(ttl_ms=ttl, scope="public"),
        "resources/templates/list": CacheHint(ttl_ms=ttl, scope="public"),
        "resources/read": CacheHint(ttl_ms=read_ttl_ms(), scope="private"),
        "server/discover": CacheHint(ttl_ms=ttl, scope="public"),
    }


def modern_request_meta(
    client_name: str = "mcp-openapi-proxy-test",
    client_version: str = "0",
) -> dict:
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION_MODERN,
        "io.modelcontextprotocol/clientInfo": {"name": client_name, "version": client_version},
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def modern_headers(method: str, name: Optional[str] = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        HEADER_PROTOCOL_VERSION: PROTOCOL_VERSION_MODERN,
        HEADER_METHOD: method,
    }
    if name:
        headers[HEADER_NAME] = name
    return headers
