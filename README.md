# mcp-openapi-proxy

[![smithery badge](https://smithery.ai/badge/@matthewhand/mcp-openapi-proxy)](https://smithery.ai/server/@matthewhand/mcp-openapi-proxy)

**mcp-openapi-proxy** is a Python package implementing a Model Context Protocol (MCP) server that dynamically exposes REST APIs defined by OpenAPI specifications as MCP tools. This allows you to easily integrate any OpenAPI-described API into MCP-based workflows.

## Overview

The package supports two operation modes:

- **Low-Level Mode (Default):** Dynamically registers tools for all API endpoints defined in an OpenAPI specification eg. /chat/completions becomes chat_completions().
- **FastMCP Mode (Simple Mode):** Provides a simplified mode for exposing specific pre-configured API endpoints as tools ie. list_functions() and call_functions().

## Features

- **Dynamic Tool Generation:** Automatically creates MCP tools from OpenAPI endpoint definitions.
- **Simple Mode Option:** Offers a static configuration option with FastMCP mode.
- **OpenAPI Specification Support:** Works with OpenAPI v3 specifications, and potentially v2.
- **Flexible Filtering:** Supports filtering endpoints by tags, paths, methods, etc. (if implemented)
- **MCP Integration:** Integrates seamlessly with MCP ecosystems to invoke REST APIs as tools.

## Installation

### Installing via Smithery

To install OpenAPI Proxy for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@matthewhand/mcp-openapi-proxy):

```bash
npx -y @smithery/cli install @matthewhand/mcp-openapi-proxy --client claude
```

### MCP Ecosystem Integration

Add **mcp-openapi-proxy** to your MCP ecosystem by configuring your `mcpServers`. Generic example:

```json
{
    "mcpServers": {
        "mcp-openapi-proxy": {
            "command": "uvx",
            "args": [
                "--from",
                "git+https://github.com/matthewhand/mcp-openapi-proxy",
                "mcp-openapi-proxy"
            ],
            "env": {
                "OPENAPI_SPEC_URL": "${OPENAPI_SPEC_URL}",
                "API_AUTH_BEARER": "",
                "TOOL_WHITELIST": "",
                "TOOL_NAME_PREFIX": ""
            }
        }
    }
}
```

For examples of real world APIs like GetZep, Open-Webui, Netlify, Vercel, etc refer to [examples](./examples).


## Modes of Operation

### FastMCP Mode (Simple Mode)

- **Enabled by:** Setting `OPENAPI_SIMPLE_MODE=true`
- **Description:** Exposes a pre-defined set of tools based on specific OpenAPI endpoints defined in code.
- **Configuration:** Requires environment variables for tool definitions.

### Low-Level Mode (Default)

- **Description:** Dynamically registers all valid API endpoints from the provided OpenAPI specification as separate tools.
- **Tool Naming:** Tools are named based on normalized OpenAPI path and method.
- **Behavior:** Descriptions are generated from the OpenAPI operation summaries and descriptions.

## Environment Variables

- `OPENAPI_SPEC_URL`: URL to the OpenAPI specification JSON file (required).
- `OPENAPI_LOGFILE_PATH`: (Optional) Path for the log file.
- `OPENAPI_SIMPLE_MODE`: (Optional) Set to `true` for FastMCP mode.
- `TOOL_WHITELIST`: (Optional) A prefix filter to select only certain tools.
- `TOOL_NAME_PREFIX`: (Optional) A string to prepend to all tool names when mapping.

## Examples

### OpenWebUI Example

**1. Confirming the OpenAPI Endpoint**

Run the following command to retrieve the OpenAPI specification:
 
```bash
curl http://localhost:3000/openapi.json
```
 
If the output is a valid OpenAPI JSON document, it confirms that the endpoint is working correctly.

**2. Configuring mcp-openapi-proxy**

In your MCP ecosystem configuration file, set the `OPENAPI_SPEC_URL` to the above endpoint. For example:
 
```json
{
    "mcpServers": {
        "mcp-openapi-proxy": {
            "command": "uvx",
            "args": [
                "--from",
                "git+https://github.com/matthewhand/mcp-openapi-proxy",
                "mcp-openapi-proxy"
            ],
            "env": {
                "OPENAPI_SPEC_URL": "http://localhost:3000/openapi.json",
                "SERVER_URL_OVERRIDE": "http://localhost:3000/v1",
                "TOOL_WHITELIST": "/models,/chat/completion",
                "API_AUTH_BEARER": "your_openwebui_token_here"
            }
        }
    }
}
```
 
- **OPENAPI_SPEC_URL**: The URL to the OpenAPI specification.
- **SERVER_URL_OVERRIDE**: Should the spec not include servers, or you wish to use a different URL.
- **TOOL_WHITELIST**: A comma-separated list of endpoint paths to expose as tools. In this example, only the `/api/models` and `/api/chat/completions` endpoints are allowed.
- **API_AUTH_BEARER**: The bearer token for endpoints requiring authentication.  Alternatively use ${OPENWEBUI_API_KEY} if configured as an environment variable or stored securely in a `.env` file.

**3. Resulting Tools**

With this configuration, the MCP server will dynamically generate tools for the whitelisted endpoints. For example:

```json
[
    {
        "name": "api_models",
        "description": "Fetches available models from /api/models"
    },
    {
        "name": "api_chat_completions",
        "description": "Generates chat completions via /api/chat/completions"
    }
]
```
 
**4. Visual Verification**
 
You can verify the registration of these tools by inspecting the MCP server logs or using your MCP client.

 
## Fly.io Example

**1. Verify the OpenAPI Endpoint**

Run the following command to retrieve the Fly.io OpenAPI JSON specification:

```bash
curl https://raw.githubusercontent.com/abhiaagarwal/peristera/refs/heads/main/fly-machines-gen/fixed_spec.json
```

Ensure the response is a valid OpenAPI JSON document containing an "openapi" field (e.g., "openapi": "3.0.0") and defined API paths.

**2. Configure mcp-openapi-proxy for Fly.io**

Update your MCP ecosystem configuration to point to the Fly.io endpoint. For example:

```json
{
    "mcpServers": {
        "mcp-openapi-proxy": {
            "command": "uvx",
            "args": [
                "--from",
                "git+https://github.com/matthewhand/mcp-openapi-proxy",
                "mcp-openapi-proxy"
            ],
            "env": {
                "OPENAPI_SPEC_URL": "https://raw.githubusercontent.com/abhiaagarwal/peristera/refs/heads/main/fly-machines-gen/fixed_spec.json",
                "SERVER_URL_OVERRIDE": "https://api.machines.dev",
                "TOOL_WHITELIST": "/machines/list,/machines/start,/machines/status",
                "API_AUTH_BEARER": "${FLY_API_TOKEN}"
            }
        }
    }
}
```

**3. Resulting Tools**

With this configuration, the MCP server will dynamically generate tools for the whitelisted endpoints. For example:
 
```json
[
    {
        "name": "machines_list",
        "description": "Fetches machine listing from /machines/list"
    },
    {
        "name": "machines_start",
        "description": "Initiates machine start via /machines/start"
    },
    {
        "name": "machines_status",
        "description": "Retrieves machine status from /machines/status"
    }
]
```

## Troubleshooting

- **Missing OPENAPI_SPEC_URL:** Verify that the `OPENAPI_SPEC_URL` environment variable is set and points to a valid OpenAPI JSON file.
- **Invalid OpenAPI Spec:** Ensure the JSON specification complies with the OpenAPI standard.
- **Filtering Issues:** Check that `TOOL_WHITELIST` is correctly defined to filter the desired classes.
- **Logging:** Consult the logs (as defined by `MCP_OPENAPI_LOGFILE_PATH`) for debugging information.
- **Verify `uvx`** Run the server directly from the GitHub repository using `uvx`:

```bash
uvx --from git+https://github.com/matthewhand/mcp-openapi-proxy mcp-openapi-proxy
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
