"""
Utility functions for mcp_openapi_proxy, including logging setup,
OpenAPI fetching, name normalization, whitelist filtering, auth handling,
parameter stripping, and response type detection.
"""

import os
import sys
import logging
import requests
import re
import json
import yaml
from urllib.parse import urlparse
from dotenv import load_dotenv
from mcp import types

load_dotenv()

OPENAPI_SPEC_URL = os.getenv("OPENAPI_SPEC_URL")

def setup_logging(debug: bool = False) -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    if debug:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s")
        stderr_handler.setFormatter(formatter)
        logger.addHandler(stderr_handler)
        logger.debug("Logging initialized, all output to stderr")
    else:
        logger.addHandler(logging.NullHandler())
    return logger

DEBUG = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
logger = setup_logging(debug=DEBUG)

logger.debug(f"OpenAPI Spec URL: {OPENAPI_SPEC_URL}")
logger.debug("utils.py initialized")

def redact_api_key(key: str) -> str:
    if not key or len(key) <= 4:
        return "<not set>"
    return f"{key[:2]}{'*' * (len(key) - 4)}{key[-2:]}"

def normalize_tool_name(name: str) -> str:
    if not name or not isinstance(name, str):
        logger.warning(f"Invalid tool name input: {name}. Defaulting to 'unknown_tool'.")
        return "unknown_tool"
    parts = name.strip().split(" ", 1)
    if len(parts) != 2:
        if "." in name:
            parts = name.split(".", 1)
            method, path = parts[0].lower(), parts[1].replace(".", "_")
        else:
            logger.warning(f"Malformed tool name '{name}', expected 'METHOD /path'. Defaulting to 'unknown_tool'.")
            return "unknown_tool"
    else:
        method, path = parts
        method = method.lower()
    path_parts = [p for p in path.split("/") if p and p not in ("api", "v2")]
    if not path_parts:
        logger.warning(f"No valid path segments in '{path}'. Using '{method}_unknown'.")
        return f"{method}_unknown"
    func_name = method
    for part in path_parts:
        if "{" in part and "}" in part:
            continue
        func_name += f"_{part.replace('.', '_')}"
    func_name = re.sub(r"[^a-zA-Z0-9_-]", "_", func_name)
    func_name = re.sub(r"_+", "_", func_name).strip("_").lower()
    if len(func_name) > 64:
        func_name = func_name[:64]
    logger.debug(f"Normalized tool name from '{name}' to '{func_name}'")
    return func_name or "unknown_tool"

def get_tool_prefix() -> str:
    prefix = os.getenv("TOOL_NAME_PREFIX", "")
    if prefix and not prefix.endswith("_"):
        prefix += "_"
    return prefix

def is_tool_whitelisted(endpoint: str) -> bool:
    whitelist = os.getenv("TOOL_WHITELIST", "")
    logger.debug(f"Checking whitelist - endpoint: {endpoint}, TOOL_WHITELIST: {whitelist}")
    if not whitelist:
        logger.debug("No TOOL_WHITELIST set, allowing all endpoints.")
        return True
    whitelist_items = [item.strip() for item in whitelist.split(",") if item.strip()]
    if not whitelist_items:
        logger.debug("TOOL_WHITELIST is empty after splitting, allowing all endpoints.")
        return True
    endpoint_parts = [p for p in endpoint.split("/") if p]
    for item in whitelist_items:
        if endpoint == item:
            logger.debug(f"Exact match found for {endpoint} in whitelist")
            return True
        if '{' not in item and endpoint.startswith(item):
            logger.debug(f"Prefix match found: {item} starts {endpoint}")
            return True
        item_parts = [p for p in item.split("/") if p]
        if len(item_parts) <= len(endpoint_parts):
            match = True
            for i, item_part in enumerate(item_parts):
                if i >= len(endpoint_parts):
                    match = False
                    break
                endpoint_part = endpoint_parts[i]
                if "{" in item_part and "}" in item_part:
                    continue
                elif item_part != endpoint_part:
                    match = False
                    break
            if match:
                logger.debug(f"Partial path match found for {endpoint} using {item}")
                return True
    logger.debug(f"No whitelist match found for {endpoint}")
    return False

def fetch_openapi_spec(spec_url: str) -> dict:
    try:
        if spec_url.startswith("file://"):
            spec_path = spec_url.replace("file://", "")
            with open(spec_path, 'r') as f:
                content = f.read()
            logger.debug(f"Read local OpenAPI spec from {spec_path}")
        else:
            response = requests.get(spec_url, timeout=10)
            if response.status_code in [401, 403]:
                logger.debug(f"Spec {spec_url} requires auth (status {response.status_code})—skipping")
                return None
            response.raise_for_status()
            content = response.text
            logger.debug(f"Fetched OpenAPI spec from {spec_url}")
        if spec_url.endswith(('.yaml', '.yml')):
            spec = yaml.safe_load(content)
            logger.debug(f"Parsed YAML OpenAPI spec from {spec_url}")
        else:
            spec = json.loads(content)
            logger.debug(f"Parsed JSON OpenAPI spec from {spec_url} (no suffix assumed JSON)")
        return spec
    except (requests.exceptions.RequestException, FileNotFoundError) as e:
        logger.error(f"Error fetching OpenAPI spec from {spec_url}: {e}")
        return None
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        logger.error(f"Error parsing OpenAPI spec from {spec_url}: {e}")
        return None

def handle_auth(operation: dict) -> dict:
    """
    Handles authentication for API requests.
    - API_KEY: Sets Bearer header.
    Returns: headers
    """
    api_key = os.getenv("API_KEY")
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        logger.debug(f"Using API_KEY as Bearer: {redact_api_key(api_key)}")
    logger.debug(f"Headers after auth: {headers}")
    return headers

def strip_parameters(parameters: dict = None) -> dict:
    """
    Strips specified parameter from parameters if STRIP_PARAM is set.
    Returns: updated_parameters
    """
    if parameters is None:
        parameters = {}
    logger.debug(f"Raw parameters before stripping: {parameters}")
    strip_param = os.getenv("STRIP_PARAM")
    if strip_param and isinstance(parameters, dict) and strip_param in parameters:
        del parameters[strip_param]
        logger.debug(f"Stripped param '{strip_param}' from parameters")
    logger.debug(f"Parameters after stripping: {parameters}")
    return parameters

def map_schema_to_tools(schema: dict) -> list:
    tools = []
    classes = schema.get("classes", [])
    for entry in classes:
        cls = entry.get("class", "")
        if not cls:
            continue
        tool_name = normalize_tool_name(cls)
        prefix = get_tool_prefix()
        if prefix:
            tool_name = prefix + tool_name
        description = f"Tool for class {cls}: " + json.dumps(entry)
        tool = types.Tool(name=tool_name, description=description, inputSchema={"type": "object"})
        tools.append(tool)
    return tools

def detect_response_type(response_text: str) -> tuple[types.TextContent, str]:
    try:
        json_data = json.loads(response_text)
        structured_text = {"text": response_text}
        content = types.TextContent(type="text", text=json.dumps(structured_text))
        log_message = "Detected JSON response, wrapped in structured text format"
    except json.JSONDecodeError:
        content = types.TextContent(type="text", text=response_text)
        log_message = "Detected non-JSON response, falling back to text"
    return content, log_message

def build_base_url(spec: dict) -> str:
    override = os.getenv("SERVER_URL_OVERRIDE", "").strip()
    if override:
        urls = override.split()
        for url in urls:
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                logger.debug(f"SERVER_URL_OVERRIDE set, using first valid URL: {url}")
                return url.rstrip('/')
        logger.error(f"No valid URLs found in SERVER_URL_OVERRIDE: {override}")
    if 'servers' in spec and spec['servers']:
        default_server = spec['servers'][0].get('url', '').rstrip('/')
        if "{tenant}" in default_server or "your-domain" in default_server:
            logger.warning(f"Placeholder detected in spec server URL: {default_server}. Consider setting SERVER_URL_OVERRIDE.")
            return default_server
        logger.debug(f"Using OpenAPI 3.0 servers base URL: {default_server}")
        return default_server
    if 'host' in spec:
        scheme = spec.get('schemes', ['https'])[0]
        host = spec['host'].strip()
        base_url = f"{scheme}://{host}"
        base_path = spec.get('basePath', '').strip('/')
        if base_path:
            base_url += f"/{base_path}"
        logger.debug(f"Using Swagger 2.0 host/basePath base URL: {base_url}")
        return base_url.rstrip('/')
    logger.critical("No servers or host defined in OpenAPI spec, and no SERVER_URL_OVERRIDE set.")
    return ""

def get_additional_headers():
    """
    Reads the EXTRA_HEADERS environment variable and parses it into a dictionary.
    Each header should be on a separate line in the format:
        Header-Name: Value
    Returns:
        A dictionary of header key-value pairs.
    """
    headers_str = os.getenv("EXTRA_HEADERS")
    if not headers_str:
        return {}
    headers = {}
    for line in headers_str.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                headers[key] = value
    return headers
