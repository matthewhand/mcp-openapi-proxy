# Using mcp-openapi-proxy with Letta

Letta is different from most MCP clients: **agents run on a Letta server**, not on your
laptop. That changes how the proxy attaches, depending on whether you use Letta Cloud or
self-host.

| | Self-hosted Letta | Letta Cloud |
| --- | --- | --- |
| stdio MCP (local subprocess) | ✅ supported | ❌ rejected (`MCP stdio servers are disabled`) |
| Remote MCP (streamable-HTTP URL) | ✅ supported | ✅ **required** |
| Exposure | none (localhost) | a public, **authenticated** HTTP endpoint |

Both paths below were verified live: a Letta agent autonomously called `get_v1_attributes`
from the credential-free [Glama](https://glama.ai/api/mcp/openapi.json) spec through the proxy.

---

## A. Self-hosted Letta — stdio MCP (recommended, no exposure)

Register the proxy as a **stdio** MCP server on your self-hosted Letta server
(`PUT /v1/tools/mcp/servers`). Letta launches the proxy as a subprocess and reads its
tools. Nothing is exposed to the network.

```bash
curl -X PUT http://127.0.0.1:8283/v1/tools/mcp/servers \
  -H 'Content-Type: application/json' \
  -d @examples/letta/selfhosted-register-mcp.json
```

`selfhosted-register-mcp.json`:

```json
{
  "server_name": "glama",
  "type": "stdio",
  "command": "uvx",
  "args": ["mcp-openapi-proxy"],
  "env": { "OPENAPI_SPEC_URL": "https://glama.ai/api/mcp/openapi.json" }
}
```

Then attach a tool to an agent and message it:

```bash
# list discovered tools
curl http://127.0.0.1:8283/v1/tools/mcp/servers/glama/tools
# create the agent with the tool, then POST a message that triggers get_v1_attributes
```

> **Note (Letta ≤ 0.11.x):** these releases ship a SQLite backend; ≥ 0.12 requires
> Postgres. Point Letta's model provider at any OpenAI-compatible endpoint via
> `OPENAI_BASE_URL` / `OPENAI_API_KEY` (e.g. a local gateway).

## B. Letta Cloud — remote MCP over authenticated HTTP

Letta Cloud cannot spawn a local process, so wrap the stdio proxy as a **streamable-HTTP**
endpoint and register its URL. **The endpoint MUST be authenticated** — it is reachable
from the public internet.

1. Wrap stdio → HTTP (e.g. [supergateway](https://github.com/supercorp-ai/supergateway)):

   ```bash
   OPENAPI_SPEC_URL=https://glama.ai/api/mcp/openapi.json \
   npx -y supergateway \
     --stdio "uvx mcp-openapi-proxy" \
     --outputTransport streamableHttp --port 8765
   ```

2. Put it behind TLS **and a bearer token** (nginx example):

   ```nginx
   location /mcp {
       if ($http_authorization != "Bearer YOUR_LONG_RANDOM_TOKEN") { return 401; }
       proxy_pass http://127.0.0.1:8765;
   }
   ```

3. Register the URL with Letta Cloud (CLI `/mcp add --transport http <url>` with the
   bearer header, or the web Tool Manager). Letta Cloud's servers then call your endpoint.

> ⚠️ **Security:** this publishes an MCP endpoint to the internet. Always require auth,
> expose only the spec(s) you intend, and **never** put credentials for unrelated services
> in the wrapped proxy's environment. If you don't need Cloud specifically, prefer the
> self-hosted stdio path (A), which exposes nothing.
