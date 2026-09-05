# Migrating to 0.4.0 (MCP 2026-07-28)

0.4.0 ports this proxy from MCP Python SDK 1.x (stateful initialize /
`Mcp-Session-Id`) to SDK 2.x, which speaks the **2026-07-28** spec. The
server is dual-stack: modern clients send one self-contained POST; legacy
stdio clients may still `initialize`.

Issue: [#65](https://github.com/matthewhand/mcp-openapi-proxy/issues/65).

## What you should do

| You | Action |
|---|---|
| `uvx mcp-openapi-proxy` / `pip install mcp-openapi-proxy` | Install `>=0.4.0`. Do **not** keep `mcp<2` alongside it. |
| mcp-gateway / supergateway wrappers | Prefer native `MCP_TRANSPORT=streamable-http` (stateless). Drop `--stateful` and session affinity. See below. |
| Custom monkeypatches of `dispatcher_handler` | Wrap the function **before** `run_server()`; the Server is rebuilt at start so the wrap is bound into `on_call_tool`. Signature is `(ctx, params)` and still accepts a request-like object with `.params`. |
| Stay on SDK 1.x | Pin `mcp-openapi-proxy~=0.3.4` and `mcp>=1.2.0,<2`. |

## Protocol (2026-07-28)

Every Streamable HTTP POST is self-contained:

```http
POST /mcp HTTP/1.1
Content-Type: application/json
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: get_ping

{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"get_ping","arguments":{},
           "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                    "io.modelcontextprotocol/clientInfo":{"name":"app","version":"1.0"},
                    "io.modelcontextprotocol/clientCapabilities":{}}}}
```

- **No** `initialize` / `notifications/initialized` required.
- **No** `Mcp-Session-Id` read or written. Do not configure sticky sessions.
- Gateways route on `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name`.
- Header/body mismatch is rejected (`-32020`).
- `tools/list` (and other list/read results) include `ttlMs` and `cacheScope`.

Stdio remains dual-stack: the SDK still answers `initialize` so Codex / Gemini /
Qwen keep working, and it also answers `server/discover` + per-request `_meta`
for 2026-era clients.

## New environment variables

| Variable | Default | Meaning |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `MCP_PORT` | `8000` | HTTP bind port |
| `MCP_PATH` | `/mcp` | Streamable HTTP path |
| `GET /healthz` | — | Process-local health JSON on native Streamable HTTP only (`{"ok":true,"name","port"}`). Does not take the MCP request lock. |
| `MCP_JSON_RESPONSE` | `true` | JSON responses instead of SSE |
| `MCP_LIST_TTL_MS` | `60000` | `ttlMs` for list results |
| `MCP_READ_TTL_MS` | `5000` | `ttlMs` for `resources/read` |
| `MCP_ALLOWED_HOSTS` | `*` | Comma-separated Host allow-list; `*` disables DNS-rebinding protection (typical behind nginx) |
| `MCP_REQUEST_STATE_KEY` | unset | Shared HMAC for MRTR `requestState` across instances |

## Hidden state moved to explicit handles

Simple mode (`OPENAPI_SIMPLE_MODE=true`) used an in-memory `_FUNCTION_OPERATIONS`
map filled by `list_functions` and required by `call_function`. That is process
memory, not a protocol session, but it still broke round-robin: instance B did
not have instance A's map.

0.4.0:

- `list_functions` returns `handle` (same as `name`) on every entry.
- `call_function(handle=...)` (or `function_name=`) rebuilds the map from the
  OpenAPI spec when it is empty. A two-step flow is `list` then `call` with the
  returned handle; no transport session, no affinity.

Low-level mode already registered tools from the spec on first use; a fresh
instance that never saw `tools/list` now also rebuilds the registry on
`tools/call`.

There is no per-connection cursor or job store. Pagination, if added later,
must travel as a `cursor` argument.

## Breaking behavior changes

1. **mcp 2.x is required.** 0.3.4 was the emergency pin (`mcp<2`) because
   unpinned 0.3.3 resolved to 2.1.1 and crashed at import. 0.4.0 is the port.
2. **`FastMCP` import path is gone.** Internal: `mcp.server.mcpserver.MCPServer`.
   `OPENAPI_SIMPLE_MODE=true` still selects simple mode.
3. **Resource URIs are strings**, not pydantic `AnyUrl`. Relative URIs are legal.
4. **Python attributes are snake_case** (`input_schema`, `is_error`, `mime_type`,
   `list_changed`). JSON-RPC on the wire is still camelCase.
5. **Low-level `Server.request_handlers` dict is gone.** Handlers are `on_*`
   constructor kwargs. `run_server()` rebuilds the Server so a wrap of
   `dispatcher_handler` still works.
6. **Tool handler exceptions** that escape `dispatcher_handler` are JSON-RPC
   errors, not `isError: true` results. The dispatcher still catches and
   returns `CallToolResult` for API/request errors.
7. **Streamable HTTP is stateless.** `Mcp-Session-Id` is never required or
   emitted. A load balancer may round-robin every POST.
8. **Modern clients against 0.3.x fail.** A 2026-07-28 client that does not
   fall back to `initialize` cannot talk to a 1.x-only server. Run 0.4.0 or
   keep a dual-stack gateway.

## Gateway / remote HTTP

Replace:

```bash
npx supergateway --stdio "uvx mcp-openapi-proxy" \
  --outputTransport streamableHttp --stateful --sessionTimeout 3600000
```

with:

```bash
env MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=$PORT \
  uvx mcp-openapi-proxy
```

Keep nginx in front for TLS/OAuth. Do **not** enable session affinity.

Temporary dual-stack: leave a 0.3.4+supergateway `--stateful` listener for
legacy HTTP clients, and a 0.4.0 native listener for 2026-era clients.

## Acceptance tests

| Test | File |
|---|---|
| tools/list, no handshake | `tests/unit/test_mcp2_protocol.py`, `tests/integration/test_client_discovery.py` |
| tools/call, no `Mcp-Session-Id` | `tests/unit/test_mcp2_protocol.py` |
| two-step via explicit handle | `tests/unit/test_mcp2_protocol.py::test_fastmcp_two_step_uses_explicit_handle` |
| retries / duplicate ids | `tests/unit/test_mcp2_protocol.py::test_http_duplicate_request_ids_are_independent` |
| mixed-version (legacy initialize) | `tests/unit/test_mcp2_protocol.py::test_legacy_initialize_still_works` |
| round-robin, two processes | `tests/integration/test_mcp2_http_roundrobin.py` |
| GET /healthz body, no spec/lock | `tests/unit/test_healthz.py` |
