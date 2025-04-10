"""
Utility functions for mcp-openapi-proxy.
"""

import os
import re
import sys
import json
import requests
import yaml
from typing import Dict, Optional, Tuple
from mcp import types

# Import the configured logger
from .logging_setup import logger

def setup_logging(debug: bool = False):
    from .logging_setup import setup_logging as ls
    return ls(debug)

def normalize_tool_name(raw_name: str, max_length: Optional[int] = None) -> str:
    """Convert an HTTP method and path into a normalized tool name."""

    # Determine effective max_length, prioritizing function argument
    effective_max_length: Optional[int] = max_length
    if effective_max_length is None:
        max_length_env = os.getenv("TOOL_NAME_MAX_LENGTH")
        if max_length_env:
            try:
                effective_max_length = int(max_length_env)
            except ValueError:
                logger.warning(f"Invalid TOOL_NAME_MAX_LENGTH env var: {max_length_env}. Ignoring.")

    try:
        method, path = raw_name.split(" ", 1)

        # remove common uninformative url prefixes
        path = re.sub(r"/(api|rest|public)/?", "/", path)

        url_template_pattern = re.compile(r"\{([^}]+)\}")
        normalized_parts = []
        for part in path.split("/"):
            if url_template_pattern.search(part):
                # Replace path parameters with "by_param" format
                params = url_template_pattern.findall(part)
                base = url_template_pattern.sub("", part)
                part = f"{base}_by_{'_'.join(params)}"

            # Clean up part and add to list
            part = part.replace(".", "_").replace("-", "_")
            normalized_parts.append(part)

        # Combine and clean final result
        tool_name = f"{method.lower()}_{'_'.join(normalized_parts)}"
        # Remove repeated underscores
        tool_name = re.sub(r"_+", "_", tool_name)

        if effective_max_length is not None and effective_max_length > 0:
            tool_name = tool_name[:max_length]

        return tool_name
    except Exception:
        return "unknown_tool"

def is_tool_whitelist_set() -> bool:
    """Check if TOOL_WHITELIST environment variable is set."""
    return bool(os.getenv("TOOL_WHITELIST"))

def is_tool_whitelisted(endpoint: str) -> bool:
    """Check if an endpoint is allowed based on TOOL_WHITELIST."""
    whitelist = os.getenv("TOOL_WHITELIST")
    logger.debug(f"Checking whitelist - endpoint: {endpoint}, TOOL_WHITELIST: {whitelist}")
    if not whitelist:
        logger.debug("No TOOL_WHITELIST set, allowing all endpoints.")
        return True
    import re
    whitelist_entries = [entry.strip() for entry in whitelist.split(",")]
    for entry in whitelist_entries:
        if "{" in entry:
            # Build a regex pattern from the whitelist entry by replacing placeholders with a non-empty segment match ([^/]+)
            pattern = re.escape(entry)
            pattern = re.sub(r"\\\{[^\\\}]+\\\}", r"([^/]+)", pattern)
            pattern = "^" + pattern + "($|/.*)$"
            if re.match(pattern, endpoint):
                logger.debug(f"Endpoint {endpoint} matches whitelist entry {entry} using regex {pattern}")
                return True
        else:
            if endpoint.startswith(entry):
                logger.debug(f"Endpoint {endpoint} matches whitelist entry {entry}")
                return True
    logger.debug(f"Endpoint {endpoint} not in whitelist - skipping.")
    return False

def fetch_openapi_spec(url: str, retries: int = 3) -> Optional[Dict]:
    """Fetch and parse an OpenAPI specification from a URL with retries."""
    logger.debug(f"Fetching OpenAPI spec from URL: {url}")
    attempt = 0
    while attempt < retries:
        try:
            if url.startswith("file://"):
                with open(url[7:], "r") as f:
                    content = f.read()
                spec_format = os.getenv("OPENAPI_SPEC_FORMAT", "json").lower()
                logger.debug(f"Using {spec_format.upper()} parser based on OPENAPI_SPEC_FORMAT env var")
                if spec_format == "yaml":
                    try:
                        spec = yaml.safe_load(content)
                        logger.debug(f"Parsed as YAML from {url}")
                    except yaml.YAMLError as ye:
                        logger.error(f"YAML parsing failed: {ye}. Raw content: {content[:500]}...")
                        return None
                else:
                    try:
                        spec = json.loads(content)
                        logger.debug(f"Parsed as JSON from {url}")
                    except json.JSONDecodeError as je:
                        logger.error(f"JSON parsing failed: {je}. Raw content: {content[:500]}...")
                        return None
            else:
                # Check IGNORE_SSL_SPEC env var
                ignore_ssl_spec = os.getenv("IGNORE_SSL_SPEC", "false").lower() in ("true", "1", "yes")
                verify_ssl_spec = not ignore_ssl_spec
                logger.debug(f"Fetching spec with SSL verification: {verify_ssl_spec} (IGNORE_SSL_SPEC={ignore_ssl_spec})")
                headers = handle_auth({"method": "GET"})
                response = requests.get(url, headers=headers, timeout=10, verify=verify_ssl_spec)
                response.raise_for_status()
                content = response.text
                logger.debug(f"Fetched content length: {len(content)} bytes")
                try:
                    spec = json.loads(content)
                    logger.debug(f"Parsed as JSON from {url}")
                except json.JSONDecodeError:
                    try:
                        spec = yaml.safe_load(content)
                        logger.debug(f"Parsed as YAML from {url}")
                    except yaml.YAMLError as ye:
                        logger.error(f"YAML parsing failed: {ye}. Raw content: {content[:500]}...")
                        return None
            return spec
        except requests.RequestException as e:
            attempt += 1
            logger.warning(f"Fetch attempt {attempt}/{retries} failed: {e}")
            if attempt == retries:
                logger.error(f"Failed to fetch spec from {url} after {retries} attempts: {e}")
                return None
    return None

def build_base_url(spec: Dict) -> Optional[str]:
    """Construct the base URL from the OpenAPI spec or override."""
    override = os.getenv("SERVER_URL_OVERRIDE")
    if override:
        urls = [url.strip() for url in override.split(",")]
        for url in urls:
            if url.startswith("http://") or url.startswith("https://"):
                logger.debug(f"SERVER_URL_OVERRIDE set, using first valid URL: {url}")
                return url
        logger.error(f"No valid URLs found in SERVER_URL_OVERRIDE: {override}")
        return None
    if "servers" in spec and spec["servers"]:
        return spec["servers"][0]["url"]
    elif "host" in spec and "schemes" in spec:
        scheme = spec["schemes"][0] if spec["schemes"] else "https"
        return f"{scheme}://{spec['host']}{spec.get('basePath', '')}"
    logger.error("No servers or host/schemes defined in spec and no SERVER_URL_OVERRIDE.")
    return None


def handle_auth(operation: Dict) -> Dict[str, str]:
    """Handle authentication based on environment variables and operation security."""
    headers = {}
    api_key = os.getenv("API_KEY")
    auth_type = os.getenv("API_AUTH_TYPE", "Bearer").lower()
    if api_key:
        if auth_type == "bearer":
            logger.debug(f"Using API_KEY as Bearer: {api_key[:5]}...")
            headers["Authorization"] = f"Bearer {api_key}"
        elif auth_type == "basic":
            logger.debug("API_AUTH_TYPE is Basic, but Basic Auth not implemented yet.")
        elif auth_type == "api-key":
            key_name = os.getenv("API_AUTH_HEADER", "Authorization")
            headers[key_name] = api_key
            logger.debug(f"Using API_KEY as API-Key in header {key_name}: {api_key[:5]}...")
    return headers

def strip_parameters(parameters: Dict) -> Dict:
    """Strip specified parameters from the input based on STRIP_PARAM."""
    strip_param = os.getenv("STRIP_PARAM")
    if not strip_param or not isinstance(parameters, dict):
        return parameters
    logger.debug(f"Raw parameters before stripping: {parameters}")
    result = parameters.copy()
    if strip_param in result:
        del result[strip_param]
    logger.debug(f"Parameters after stripping: {result}")
    return result

def detect_response_type(response_text: str) -> Tuple[types.TextContent, str]:
    """Determine response type based on JSON validity.
    If response_text is valid JSON, return a wrapped JSON string;
    otherwise, return the plain text.
    """
    try:
        json.loads(response_text)
        wrapped_text = json.dumps({"text": response_text})
        # Remove id=None as it's not a valid parameter for mcp.types.TextContent
        return types.TextContent(type="text", text=wrapped_text), "JSON response"
    except json.JSONDecodeError:
         # Remove id=None as it's not a valid parameter for mcp.types.TextContent
        return types.TextContent(type="text", text=response_text.strip()), "non-JSON text"

def get_additional_headers() -> Dict[str, str]:
    """Parse additional headers from EXTRA_HEADERS environment variable."""
    headers = {}
    extra_headers = os.getenv("EXTRA_HEADERS")
    if extra_headers:
        for line in extra_headers.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()
    return headers
