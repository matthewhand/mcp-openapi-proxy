# mcp-openapi-proxy

**mcp-openapi-proxy** is a Python package that implements a Model Context Protocol (MCP) server, designed to dynamically expose REST APIs—defined by OpenAPI specifications—as MCP tools. This facilitates seamless integration of OpenAPI-described APIs into MCP-based workflows.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
  - [MCP Ecosystem Integration](#mcp-ecosystem-integration)
- [Modes of Operation](#modes-of-operation)
  - [FastMCP Mode (Simple Mode)](#fastmcp-mode-simple-mode)
  - [Low-Level Mode (Default)](#low-level-mode-default)
- [Environment Variables](#environment-variables)
- [Verified Clients & Live Results (2026-06-12)](#verified-clients--live-results-2026-06-12)
  - [Tips](#tips)
- [Examples](#examples) — Glama, Fly.io, Render, Slack, GetZep, Virustotal, Notion, Asana, APIs.guru, NetBox, Box, WolframAlpha (collapsed)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Overview

The package offers two operational modes:

- **Low-Level Mode (Default):** Dynamically registers tools corresponding to all valid API endpoints specified in an OpenAPI document (e.g. `/chat/completions` becomes `chat_completions()`).
- **FastMCP Mode (Simple Mode):** Provides a streamlined approach by exposing a predefined set of tools (e.g. `list_functions()` and `call_function()`) based on static configurations.

## Features

- **Dynamic Tool Generation:** Automatically creates MCP tools from OpenAPI endpoint definitions.
- **Simple Mode Option:** Offers a static configuration alternative via FastMCP mode.
- **OpenAPI Specification Support:** Compatible with OpenAPI v3 with potential support for v2.
- **Flexible Filtering:** Allows endpoint filtering through whitelisting by paths or other criteria.
- **Payload Authentication:** Supports custom authentication via JMESPath expressions (e.g. for APIs like Slack that expect tokens in the payload not the HTTP header).
- **Header Authentication:** Uses `Bearer` by default for `API_KEY` in the Authorization header, customizable for APIs like Fly.io requiring `Api-Key`.
- **MCP Integration:** Seamlessly integrates with MCP ecosystems for invoking REST APIs as tools.

## Installation

Install the package directly from PyPI using the following command:

```bash
uvx mcp-openapi-proxy
```

### MCP Ecosystem Integration

To incorporate **mcp-openapi-proxy** into your MCP ecosystem configure it within your `mcpServers` settings. Below is a generic example:

```json
{
    "mcpServers": {
        "mcp-openapi-proxy": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "${OPENAPI_SPEC_URL}",
                "API_KEY": "${API_OPENAPI_KEY}"
            }
        }
    }
}
```

Refer to the **Examples** section below for practical configurations tailored to specific APIs.

## Modes of Operation

### FastMCP Mode (Simple Mode)

- **Enabled by:** Setting the environment variable `OPENAPI_SIMPLE_MODE=true`.
- **Description:** Exposes a fixed set of tools derived from specific OpenAPI endpoints as defined in the code.
- **Configuration:** Relies on environment variables to specify tool behavior.

### Low-Level Mode (Default)

- **Description:** Automatically registers all valid API endpoints from the provided OpenAPI specification as individual tools.
- **Tool Naming:** Derives tool names from normalized OpenAPI paths and methods.
- **Behavior:** Generates tool descriptions from OpenAPI operation summaries and descriptions.

## Environment Variables

- `OPENAPI_SPEC_URL`: (Required) The URL to the OpenAPI specification JSON file (e.g. `https://example.com/spec.json` or `file:///path/to/local/spec.json`).
- `OPENAPI_LOGFILE_PATH`: (Optional) Specifies the log file path.
- `OPENAPI_SIMPLE_MODE`: (Optional) Set to `true` to enable FastMCP mode.
- `TOOL_WHITELIST`: (Optional) A comma-separated list of endpoint paths to expose as tools.
- `ADDITIONAL_RESOURCES`: (Optional) Comma-separated `name=/path/to/file` entries served as extra MCP resources (use-case docs such as naming policies or layout conventions; see `examples/resources/`).
- `TOOL_NAME_PREFIX`: (Optional) A prefix to prepend to all tool names.
- `API_KEY`: (Optional) Authentication token for the API sent as `Bearer <API_KEY>` in the Authorization header by default.
- `API_AUTH_TYPE`: (Optional) Overrides the default `Bearer` Authorization scheme. `api-key` sends the key in the header named by `API_AUTH_HEADER`; any other value is used as a custom scheme prefix (e.g. `Token` for NetBox → `Authorization: Token <key>`).
- `STRIP_PARAM`: (Optional) JMESPath expression to strip unwanted parameters (e.g. `token` for Slack).
- `DEBUG`: (Optional) Enables verbose debug logging when set to "true", "1", or "yes".
- `EXTRA_HEADERS`: (Optional) Additional HTTP headers in "Header: Value" format (one per line) to attach to outgoing API requests.
- `SERVER_URL_OVERRIDE`: (Optional) Overrides the base URL from the OpenAPI specification when set, useful for custom deployments.
- `TOOL_NAME_MAX_LENGTH`: (Optional) Truncates tool names to a max length.
- Additional Variable: `OPENAPI_SPEC_URL_<hash>` – a variant for unique per-test configurations (falls back to `OPENAPI_SPEC_URL`).
- `IGNORE_SSL_SPEC`: (Optional) Set to `true` to disable SSL certificate verification when fetching the OpenAPI spec.
- `IGNORE_SSL_TOOLS`: (Optional) Set to `true` to disable SSL certificate verification for API requests made by tools.

## Verified Clients & Live Results (2026-06-12)

The example configurations below were exercised against the live APIs, and the proxy was attached to a range of agent CLIs over stdio MCP. Results from that verification run:

### API example results

| API example | Tools | Sample call proven | Extra env needed |
|---|---|---|---|
| glama | 6 | `get_v1_attributes` | none |
| apis.guru | 7 | `get_metrics_json` | none |
| wolframalpha | 2 | `get_v1_llm_api` | `API_KEY` |
| virustotal | 4 | IP report | `API_KEY` + `API_AUTH_TYPE=api-key` + `API_AUTH_HEADER=x-apikey` |
| asana | 73 (whitelist `/workspaces,/projects,/tasks`) | created project + 11 tasks | `SERVER_URL_OVERRIDE` + `API_KEY` |
| render | 52 | `get_services` | `API_KEY` (NEW spec URL `render-public-api-1.json`) |
| notion | 4–5 (whitelist `/v1/users,/v1/search` or `/v1/pages`) | page create + title read-back | `SERVER_URL_OVERRIDE` + `EXTRA_HEADERS` (`Notion-Version`) + `API_KEY` |
| elevenlabs | 19 | TTS mp3 generated | `SERVER_URL_OVERRIDE` + `API_AUTH_TYPE=api-key` + `API_AUTH_HEADER=xi-api-key` |
| flyio | 34–35 | apps + machine health | `API_KEY` |
| slack | 7 (exact dot-path whitelist until #27 fix) | `auth.test` + `postMessage` | `API_KEY` |
| netbox | 9 (whitelist `/ipam/ip-addresses`) | IPAM write + read | `API_KEY` + `API_AUTH_TYPE=Token` |

### Client matrix

| Agent CLI | Model used (live test) | MCP attach mechanism | Tool calls | Prompts/Resources surfaced to model? |
|---|---|---|---|---|
| Codex | `gpt-5-codex` (OpenAI API) | `codex exec -c mcp_servers.*` | ✅ native | ❌ (used raw stdio) |
| Gemini | Google OAuth free tier (CLI default model) | project `.gemini/settings.json` `mcpServers` | ✅ native | ❌ interactive slash-commands only |
| Qwen | `agent` group via local LiteLLM gateway | project `.qwen/settings.json` | ✅ native | ❌ NO_PROMPT_ACCESS |
| Kilocode | `kilo-auto/free` | global `settings/mcp_settings.json`, clean workspace | ✅ native | ❌ |
| opencode | `orchestration` group via local LiteLLM gateway | `~/.config/opencode/opencode.json` `mcp` | ✅ native | ❌ |
| Vibe | `mistral-medium-3.5` | `~/.vibe/config.toml` `[[mcp_servers]]` | ✅ discovery + reads (writes flaky) | ❌ |
| agy | — | — | ❌ headless cannot enable MCP | — |
| letta cloud | Letta Cloud default | streamable-HTTP MCP URL (`/mcp add --transport http` + bearer) | ✅ remote (stdio rejected) | — |
| letta (self-hosted ≤0.11.x) | `agent` group via local LiteLLM gateway | stdio via `PUT /v1/tools/mcp/servers` | ✅ native | — |

Minimal sanitized configs per client (the no-auth Glama spec is used as the smallest working example; substitute your own spec URL and `$YOUR_KEY` as needed):

<details>
<summary><b>Codex</b> — inline <code>-c mcp_servers.*</code> overrides</summary>

```bash
codex exec \
  -c 'mcp_servers.glama.command="uvx"' \
  -c 'mcp_servers.glama.args=["mcp-openapi-proxy"]' \
  -c 'mcp_servers.glama.env.OPENAPI_SPEC_URL="https://glama.ai/api/mcp/openapi.json"' \
  "list the available tools"
```

</details>

<details>
<summary><b>Gemini</b> — project <code>.gemini/settings.json</code></summary>

```json
{
  "mcpServers": {
    "glama": {
      "command": "uvx",
      "args": ["mcp-openapi-proxy"],
      "env": { "OPENAPI_SPEC_URL": "https://glama.ai/api/mcp/openapi.json" }
    }
  }
}
```

</details>

<details>
<summary><b>Qwen</b> — project <code>.qwen/settings.json</code></summary>

```json
{
  "mcpServers": {
    "glama": {
      "command": "uvx",
      "args": ["mcp-openapi-proxy"],
      "env": { "OPENAPI_SPEC_URL": "https://glama.ai/api/mcp/openapi.json" }
    }
  }
}
```

</details>

<details>
<summary><b>Kilocode</b> — global <code>settings/mcp_settings.json</code> (use a clean workspace)</summary>

```json
{
  "mcpServers": {
    "glama": {
      "command": "uvx",
      "args": ["mcp-openapi-proxy"],
      "env": { "OPENAPI_SPEC_URL": "https://glama.ai/api/mcp/openapi.json" }
    }
  }
}
```

</details>

<details>
<summary><b>opencode</b> — <code>~/.config/opencode/opencode.json</code> <code>mcp</code> block</summary>

```json
{
  "mcp": {
    "glama": {
      "type": "local",
      "command": ["uvx", "mcp-openapi-proxy"],
      "environment": { "OPENAPI_SPEC_URL": "https://glama.ai/api/mcp/openapi.json" }
    }
  }
}
```

</details>

<details>
<summary><b>Vibe</b> — <code>~/.vibe/config.toml</code> <code>[[mcp_servers]]</code></summary>

```toml
[[mcp_servers]]
name = "glama"
command = "uvx"
args = ["mcp-openapi-proxy"]

[mcp_servers.env]
OPENAPI_SPEC_URL = "https://glama.ai/api/mcp/openapi.json"
```

</details>

agy (headless) and letta cloud could not attach a stdio MCP server at all, so no config snippet applies: agy provides no way to enable MCP in headless mode, and letta cloud only accepts remote MCP servers.

### Tips

- **Big specs need `TOOL_WHITELIST`.** Large APIs (Asana, Render, Fly.io, Slack, NetBox) expose dozens of endpoints; whitelist the paths you need to keep the tool count manageable for clients.
- **Dot-style paths need exact whitelist entries for now.** Slack-style paths like `/chat.postMessage` are not matched by prefix whitelisting — list each path exactly (issue #27 / PR #32).
- **Slow remote specs can crash-loop short-timeout clients.** If a client kills the server before a large spec finishes downloading, fetch the spec once and point `OPENAPI_SPEC_URL` at a local `file://` copy (issue #28).
- **Custom auth schemes** are handled via `API_AUTH_TYPE` (PR #25), e.g. `Token` for NetBox, or `api-key` with `API_AUTH_HEADER` for Virustotal/ElevenLabs-style header keys.

## Examples

For testing you can run the uvx command as demonstrated in the examples then interact with the MCP server via JSON-RPC messages to list tools and resources. See the "JSON-RPC Testing" section below.

Each example below is collapsed — click to expand.

<details>
<summary><b>Glama Example</b> — the most minimal config: just <code>OPENAPI_SPEC_URL</code>, no auth</summary>

![image](https://github.com/user-attachments/assets/84afdaa8-7b4f-4726-835f-64255ca970b7)

Glama offers the most minimal configuration for mcp-openapi-proxy requiring only the `OPENAPI_SPEC_URL` environment variable. This simplicity makes it ideal for quick testing.

#### 1. Verify the OpenAPI Specification

Retrieve the Glama OpenAPI specification:

```bash
curl https://glama.ai/api/mcp/openapi.json
```

Ensure the response is a valid OpenAPI JSON document.

#### 2. Configure mcp-openapi-proxy for Glama

Add the following configuration to your MCP ecosystem settings:

```json
{
    "mcpServers": {
        "glama": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "https://glama.ai/api/mcp/openapi.json"
            }
        }
    }
}
```

#### 3. Testing

Start the service with:

```bash
OPENAPI_SPEC_URL="https://glama.ai/api/mcp/openapi.json" uvx mcp-openapi-proxy
```

Then refer to the [JSON-RPC Testing](#json-rpc-testing) section for instructions on listing resources and tools.

</details>

<details>
<summary><b>Fly.io Example</b> — machines API with an API token</summary>

![image](https://github.com/user-attachments/assets/80abd7fa-ccca-4e35-b0dd-36ef82a236c5)

Fly.io provides a simple API for managing machines making it an ideal starting point. Obtain an API token from [Fly.io documentation](https://fly.io/docs/hands-on/install-flyctl/).

#### 1. Verify the OpenAPI Specification

Retrieve the Fly.io OpenAPI specification:

```bash
curl https://raw.githubusercontent.com/abhiaagarwal/peristera/refs/heads/main/fly-machines-gen/fixed_spec.json
```

Ensure the response is a valid OpenAPI JSON document.

#### 2. Configure mcp-openapi-proxy for Fly.io

Update your MCP ecosystem configuration:

```json
{
    "mcpServers": {
        "flyio": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/abhiaagarwal/peristera/refs/heads/main/fly-machines-gen/fixed_spec.json",
                "API_KEY": "<your_flyio_token_here>"
            }
        }
    }
}
```

- **OPENAPI_SPEC_URL**: Points to the Fly.io OpenAPI specification.
- **API_KEY**: Your Fly.io API token (replace `<your_flyio_token_here>`).
- **API_AUTH_TYPE**: Set to `Api-Key` for Fly.io’s header-based authentication (overrides default `Bearer`).

#### 3. Testing

After starting the service refer to the [JSON-RPC Testing](#json-rpc-testing) section for instructions on listing resources and tools.

</details>

<details>
<summary><b>Render Example</b> — manage hosted services with a tool whitelist</summary>

![image](https://github.com/user-attachments/assets/f1dee1bf-e330-41f1-a700-6386edd8895e)

Render offers infrastructure hosting that can be managed via an API. The provided configuration file `examples/render-claude_desktop_config.json` demonstrates how to set up your MCP ecosystem quickly with minimal settings.

#### 1. Verify the OpenAPI Specification

Retrieve the Render OpenAPI specification:

```bash
curl https://api-docs.render.com/openapi/render-public-api-1.json
```

Ensure the response is a valid OpenAPI document.

#### 2. Configure mcp-openapi-proxy for Render

Add the following configuration to your MCP ecosystem settings:

```json
{
    "mcpServers": {
        "render": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "https://api-docs.render.com/openapi/render-public-api-1.json",
                "TOOL_WHITELIST": "/services,/maintenance",
                "API_KEY": "your_render_token_here"
            }
        }
    }
}
```

#### 3. Testing

Launch the proxy with your Render configuration:

```bash
OPENAPI_SPEC_URL="https://api-docs.render.com/openapi/render-public-api-1.json" TOOL_WHITELIST="/services,/maintenance" API_KEY="your_render_token_here" uvx mcp-openapi-proxy
```

Then refer to the [JSON-RPC Testing](#json-rpc-testing) section for instructions on listing resources and tools.

</details>

<details>
<summary><b>Slack Example</b> — payload token stripping via JMESPath (<code>STRIP_PARAM</code>)</summary>

![image](https://github.com/user-attachments/assets/706adad5-3f1c-4f32-aef5-6a1af794aef3)

Slack’s API showcases stripping unnecessary token payload using JMESPath. Obtain a bot token from [Slack API documentation](https://api.slack.com/authentication/token-types#bot).

#### 1. Verify the OpenAPI Specification

Retrieve the Slack OpenAPI specification:

```bash
curl https://raw.githubusercontent.com/slackapi/slack-api-specs/master/web-api/slack_web_openapi_v2.json
```

Ensure it’s a valid OpenAPI JSON document.

#### 2. Configure mcp-openapi-proxy for Slack

Update your configuration:

```json
{
    "mcpServers": {
        "slack": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/slackapi/slack-api-specs/master/web-api/slack_web_openapi_v2.json",
                "TOOL_WHITELIST": "/chat,/bots,/conversations,/reminders,/files,/users",
                "API_KEY": "<your_slack_bot_token, starts with xoxb>",
                "STRIP_PARAM": "token",
                "TOOL_NAME_PREFIX": "slack_"
            }
        }
    }
}
```

- **OPENAPI_SPEC_URL**: Slack’s OpenAPI spec URL.
- **TOOL_WHITELIST**: Limits tools to useful endpoint groups (e.g. chat, conversations, users).
- **API_KEY**: Your Slack bot token (e.g. `xoxb-...`, replace `<your_slack_bot_token>`).
- **STRIP_PARAM**: Removes the token field from the request payload.
- **TOOL_NAME_PREFIX**: Prepends `slack_` to tool names.

#### 3. Testing

After starting the service refer to the [JSON-RPC Testing](#json-rpc-testing) section for instructions on listing resources and tools.

</details>

<details>
<summary><b>GetZep Example</b> — project-generated spec with <code>Api-Key</code> auth</summary>

> **Note (2026):** GetZep's hosted endpoint (`api.getzep.com`) returns **401** for previously-working keys — the hosted free tier no longer accepts API keys. The example now targets a **self-hosted Zep CE**: see `examples/zep-ce/docker-compose.yml` (zep built from source tag v1.0.2 + `pgvector/pgvector:pg17`; the delisted `zepai/zep` image must be rebuilt via the official `Dockerfile.ce`). Auth quirk: Zep's scheme is literally `Api-Key`, which collides with the proxy's special `api-key` mode — use `API_AUTH_TYPE=api-key` with `API_KEY="Api-Key <your-secret>"`. Live-verified: 8 tools via `TOOL_WHITELIST=/sessions`; session create + read-back through the bridge.


![image](https://github.com/user-attachments/assets/9a4fdabb-fa3d-4626-a50f-438147eadc9f)

GetZep offers a free cloud API for memory management with detailed endpoints. Since GetZep did not provide an official OpenAPI specification, this project includes a generated spec hosted on GitHub for convenience. Users can similarly generate OpenAPI specs for any REST API and reference them locally (e.g. `file:///path/to/spec.json`). Obtain an API key from [GetZep's documentation](https://docs.getzep.com/).

#### 1. Verify the OpenAPI Specification

Retrieve the project-provided GetZep OpenAPI specification:

```bash
curl https://raw.githubusercontent.com/matthewhand/mcp-openapi-proxy/refs/heads/main/examples/getzep.swagger.json
```

Ensure it’s a valid OpenAPI JSON document. Alternatively, generate your own spec and use a `file://` URL to reference a local file.

#### 2. Configure mcp-openapi-proxy for GetZep

Update your configuration:

```json
{
    "mcpServers": {
        "getzep": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/matthewhand/mcp-openapi-proxy/refs/heads/main/examples/getzep.swagger.json",
                "TOOL_WHITELIST": "/sessions",
                "API_KEY": "<your_getzep_api_key>",
                "API_AUTH_TYPE": "Api-Key",
                "TOOL_NAME_PREFIX": "zep_"
            }
        }
    }
}
```

- **OPENAPI_SPEC_URL**: Points to the project-provided GetZep Swagger spec (or use `file:///path/to/your/spec.json` for a local file).
- **TOOL_WHITELIST**: Limits to `/sessions` endpoints.
- **API_KEY**: Your GetZep API key.
- **API_AUTH_TYPE**: Uses `Api-Key` for header-based authentication.
- **TOOL_NAME_PREFIX**: Prepends `zep_` to tool names.

#### 3. Testing

After starting the service refer to the [JSON-RPC Testing](#json-rpc-testing) section for instructions on listing resources and tools.

</details>

<details>
<summary><b>Virustotal Example</b> — YAML spec + custom <code>x-apikey</code> auth header</summary>

![image](https://github.com/user-attachments/assets/d1760e58-a299-4004-9593-6dbaf3b685a1)

This example demonstrates:
- Using a YAML OpenAPI specification file
- Using custom HTTP auth header, "x-apikey"

#### 1. Verify the OpenAPI Specification

Retrieve the Virustotal OpenAPI specification:

```bash
curl https://raw.githubusercontent.com/matthewhand/mcp-openapi-proxy/refs/heads/main/examples/virustotal.openapi.yml
```

Ensure that the response is a valid OpenAPI YAML document.

#### 2. Configure mcp-openapi-proxy for Virustotal

Add the following configuration to your MCP ecosystem settings:

```json
{
    "mcpServers": {
        "virustotal": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/matthewhand/mcp-openapi-proxy/refs/heads/main/examples/virustotal.openapi.yml",
                "EXTRA_HEADERS": "x-apikey: ${VIRUSTOTAL_API_KEY}",
                "OPENAPI_SPEC_FORMAT": "yaml"
            }
        }
    }
}
```

Key configuration points:
- By default, the proxy expects a JSON specification and sends the API key with a Bearer prefix.
- To use a YAML OpenAPI specification, include `OPENAPI_SPEC_FORMAT="yaml"`.
- Note: VirusTotal requires a special authentication header; EXTRA_HEADERS is used to transmit the API key as "x-apikey: ${VIRUSTOTAL_API_KEY}".

#### 3. Testing

Launch the proxy with the Virustotal configuration:

```bash
OPENAPI_SPEC_URL="https://raw.githubusercontent.com/matthewhand/mcp-openapi-proxy/refs/heads/main/examples/virustotal.openapi.yml" API_KEY="your_virustotal_api_key" API_AUTH_HEADER="x-apikey" API_AUTH_TYPE="" OPENAPI_SPEC_FORMAT="yaml" uvx mcp-openapi-proxy
```

After starting the service, refer to the [JSON-RPC Testing](#json-rpc-testing) section for instructions on listing resources and tools.

</details>

<details>
<summary><b>Notion Example</b> — API version header via <code>EXTRA_HEADERS</code></summary>

![image](https://github.com/user-attachments/assets/45038bcf-9537-4337-8a90-8553ad3aa81b)

Notion’s API requires specifying a particular version via HTTP headers. This example uses the `EXTRA_HEADERS` environment variable to include the required header, and focuses on verifying the OpenAPI specification.

#### 1. Verify the OpenAPI Specification

Retrieve the Notion OpenAPI specification:

```bash
curl https://storage.googleapis.com/versori-assets/public-specs/20240214/NotionAPI.yml
```

Ensure the response is a valid YAML document.

#### 2. Configure mcp-openapi-proxy for Notion

Add the following configuration to your MCP ecosystem settings:

```json
{
  "mcpServers": {
    "notion": {
      "command": "uvx",
      "args": [
        "mcp-openapi-proxy"
      ],
      "env": {
          "API_KEY": "ntn_<your_key>",
          "OPENAPI_SPEC_URL": "https://storage.googleapis.com/versori-assets/public-specs/20240214/NotionAPI.yml",
          "SERVER_URL_OVERRIDE": "https://api.notion.com",
          "EXTRA_HEADERS": "Notion-Version: 2022-06-28"
      }
    }
  }
}
```

#### 3. Testing

Launch the proxy with the Notion configuration:

```bash
OPENAPI_SPEC_URL="https://storage.googleapis.com/versori-assets/public-specs/20240214/NotionAPI.yml" SERVER_URL_OVERRIDE="https://api.notion.com" EXTRA_HEADERS="Notion-Version: 2022-06-28" API_KEY="ntn_<your_key>" uvx mcp-openapi-proxy
```

After starting the service, refer to the [JSON-RPC Testing](#json-rpc-testing) section for instructions on listing resources and tools.

</details>

<details>
<summary><b>Asana Example</b> — workspaces/tasks/projects with a whitelist and <code>SERVER_URL_OVERRIDE</code></summary>

![image](https://github.com/user-attachments/assets/087571dd-9e06-407e-905c-92815231f618)

Asana provides a rich set of endpoints for managing workspaces, tasks, projects, and users. The integration tests demonstrate usage of endpoints such as `GET /workspaces`, `GET /tasks`, and `GET /projects`.

#### 1. Verify the OpenAPI Specification

Retrieve the Asana OpenAPI specification:

```bash
curl https://raw.githubusercontent.com/Asana/openapi/refs/heads/master/defs/asana_oas.yaml
```

Ensure the response is a valid YAML (or JSON) document.

#### 2. Configure mcp-openapi-proxy for Asana

Add the following configuration to your MCP ecosystem settings:

```json
{
  "mcpServers": {
    "asana": {
      "command": "uvx",
      "args": [
        "mcp-openapi-proxy"
      ],
      "env": {
        "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/Asana/openapi/refs/heads/master/defs/asana_oas.yaml",
        "SERVER_URL_OVERRIDE": "https://app.asana.com/api/1.0",
        "TOOL_WHITELIST": "/workspaces,/tasks,/projects,/users",
        "API_KEY": "${ASANA_API_KEY}"
      }
    }
  }
}
```

*Note: Most Asana API endpoints require authentication. Set `ASANA_API_KEY` in your environment or `.env` file with a valid token.*

#### 3. Testing

Start the service with:

```bash
ASANA_API_KEY="<your_asana_api_key>" OPENAPI_SPEC_URL="https://raw.githubusercontent.com/Asana/openapi/refs/heads/master/defs/asana_oas.yaml" SERVER_URL_OVERRIDE="https://app.asana.com/api/1.0" TOOL_WHITELIST="/workspaces,/tasks,/projects,/users" uvx mcp-openapi-proxy
```

You can then use the MCP ecosystem to list and invoke tools for endpoints like `/dcim/devices/` and `/ipam/ip-addresses/`.

</details>

<details>
<summary><b>APIs.guru Example</b> — directory of thousands of public OpenAPI definitions, no auth</summary>

APIs.guru provides a directory of OpenAPI definitions for thousands of public APIs. This example shows how to use mcp-openapi-proxy to expose the APIs.guru directory as MCP tools.

#### 1. Verify the OpenAPI Specification

Retrieve the APIs.guru OpenAPI specification:

```bash
curl https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/apis.guru/2.2.0/openapi.yaml
```

Ensure the response is a valid OpenAPI YAML document.

#### 2. Configure mcp-openapi-proxy for APIs.guru

Add the following configuration to your MCP ecosystem settings:

```json
{
    "mcpServers": {
        "apisguru": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/apis.guru/2.2.0/openapi.yaml"
            }
        }
    }
}
```

#### 3. Testing

Start the service with:

```bash
OPENAPI_SPEC_URL="https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/apis.guru/2.2.0/openapi.yaml" uvx mcp-openapi-proxy
```

You can then use the MCP ecosystem to list and invoke tools such as `listAPIs`, `getMetrics`, and `getProviders` that are defined in the APIs.guru directory.

</details>

<details>
<summary><b>NetBox Example</b> — IPAM/DCIM API with <code>Token</code> auth</summary>

NetBox is an open-source IP address management (IPAM) and data center infrastructure management (DCIM) tool. This example demonstrates how to use mcp-openapi-proxy to expose the NetBox API as MCP tools.

#### 1. Verify the OpenAPI Specification

Retrieve the NetBox OpenAPI specification:

```bash
curl https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/netbox.dev/3.4/openapi.yaml
```

Ensure the response is a valid OpenAPI YAML document.

#### 2. Configure mcp-openapi-proxy for NetBox

Add the following configuration to your MCP ecosystem settings:

```json
{
    "mcpServers": {
        "netbox": {
            "command": "uvx",
            "args": ["mcp-openapi-proxy"],
            "env": {
                "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/netbox.dev/3.4/openapi.yaml",
                "API_KEY": "${NETBOX_API_KEY}"
            }
        }
    }
}
```

*Note: Most NetBox API endpoints require authentication. Set `NETBOX_API_KEY` in your environment or `.env` file with a valid token.*

#### 3. Testing

Start the service with:

```bash
OPENAPI_SPEC_URL="https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/netbox.dev/3.4/openapi.yaml" API_KEY="$NETBOX_API_KEY" uvx mcp-openapi-proxy
```

You can then use the MCP ecosystem to list and invoke tools for endpoints like `/dcim/devices/` and `/ipam/ip-addresses/`.

</details>

<details>
<summary><b>Box API Example</b> — developer-token access to Box content</summary>

You can integrate the Box Platform API using your own developer token for authenticated access to your Box account. This example demonstrates how to expose Box API endpoints as MCP tools.

#### Example config: `examples/box-claude_desktop_config.json`
```json
"env": {
  "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/box.com/2.0.0/openapi.yaml",
  "TOOL_WHITELIST": "/folders/{folder_id}/items,/files/{file_id},/search,/recent_items",
  "API_KEY": "${BOX_API_KEY}"
}
```

- Set your Box developer token as an environment variable in `.env`:
  ```
  BOX_API_KEY=your_box_developer_token
  ```

- Or run the proxy with a one-liner:
  ```bash
  OPENAPI_SPEC_URL="https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/box.com/2.0.0/openapi.yaml" API_KEY="$BOX_API_KEY" uvx mcp-openapi-proxy
  ```

You can now use the MCP ecosystem to list and invoke Box API tools. For integration tests, see `tests/integration/test_box_integration.py`.

Note: developer api keys for free tier box users are limited to 60 minutes :(.  

</details>

<details>
<summary><b>WolframAlpha API Example</b> — computation API keyed by App ID</summary>

![image](https://github.com/user-attachments/assets/6a634d63-5734-4275-8876-6bacb8beabcc)

You can integrate the WolframAlpha API using your own App ID for authenticated access. This example demonstrates how to expose WolframAlpha API endpoints as MCP tools.

#### Example config: `examples/wolframalpha-claude_desktop_config.json`
```json
{
  "mcpServers": {
    "wolframalpha": {
      "command": "uvx",
      "args": [
        "mcp-openapi-proxy"
      ],
      "env": {
        "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/wolframalpha.com/v0.1/openapi.yaml",
        "API_KEY": "${WOLFRAM_LLM_APP_ID}"
      }
    }
  }
}
```

- Set your WolframAlpha App ID as an environment variable in `.env`:
  ```
  WOLFRAM_LLM_APP_ID=your_wolfram_app_id
  ```

- Or run the proxy with a one-liner:
  ```bash
  OPENAPI_SPEC_URL="https://raw.githubusercontent.com/APIs-guru/openapi-directory/refs/heads/main/APIs/wolframalpha.com/v0.1/openapi.yaml" API_KEY="$WOLFRAM_LLM_APP_ID" uvx mcp-openapi-proxy
  ```

You can now use the MCP ecosystem to list and invoke WolframAlpha API tools. For integration tests, see `tests/integration/test_wolframalpha_integration.py`.

</details>

## Troubleshooting

### JSON-RPC Testing

For alternative testing, you can interact with the MCP server via JSON-RPC. After starting the server, paste the following initialization message:
```json
{"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"claude-ai","version":"0.1.0"}},"jsonrpc":"2.0","id":0}
```

Expected response:
```json
{"jsonrpc":"2.0","id":0,"result":{"protocolVersion":"2024-11-05","capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false},"tools":{"listChanged":false}},"serverInfo":{"name":"sqlite","version":"0.1.0"}}}
```

Then paste these follow-up messages:
```json
{"method":"notifications/initialized","jsonrpc":"2.0"}
{"method":"resources/list","params":{},"jsonrpc":"2.0","id":1}
{"method":"tools/list","params":{},"jsonrpc":"2.0","id":2}
```

- **Missing OPENAPI_SPEC_URL:** Ensure it’s set to a valid OpenAPI JSON URL or local file path.
- **Invalid Specification:** Verify the OpenAPI document is standard-compliant.
- **Tool Filtering Issues:** Check `TOOL_WHITELIST` matches desired endpoints.
- **Authentication Errors:** Confirm `API_KEY` and `API_AUTH_TYPE` are correct.
- **Logging:** Set `DEBUG=true` for detailed output to stderr.
- **Test Server:** Run directly:

```bash
uvx mcp-openapi-proxy
```

## License

[MIT License](LICENSE)
