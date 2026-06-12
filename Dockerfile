# Dockerfile for mcp-openapi-proxy (https://github.com/matthewhand/mcp-openapi-proxy)
# Used by the Glama MCP directory to build and host the server.
#
# Build:
#   docker build -t mcp-openapi-proxy .
# Run (stdio MCP server; OPENAPI_SPEC_URL is required):
#   docker run -i --rm -e OPENAPI_SPEC_URL=https://example.com/openapi.json mcp-openapi-proxy

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copy project metadata and sources, then install the package.
COPY pyproject.toml README.md LICENSE ./
COPY mcp_openapi_proxy ./mcp_openapi_proxy

RUN pip install --no-cache-dir .

# Required: URL (or file:// path) of the OpenAPI specification to expose.
# See README.md for the full list of optional variables
# (API_KEY, TOOL_WHITELIST, SERVER_URL_OVERRIDE, EXTRA_HEADERS, DEBUG, ...).
ENV OPENAPI_SPEC_URL=""

ENTRYPOINT ["mcp-openapi-proxy"]
