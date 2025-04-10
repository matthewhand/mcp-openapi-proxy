"""
OpenAPI specification handling for mcp-openapi-proxy.
"""

import os
import json
import requests
import yaml
from typing import Dict, Optional, List, Union
from urllib.parse import unquote, quote
from mcp import types
from .logging_setup import logger

def fetch_openapi_spec(url: str, retries: int = 3) -> Optional[Dict]:
    """Fetch and parse an OpenAPI specification from a URL with retries."""
    logger.debug(f"Fetching OpenAPI spec from URL: {url}")
    attempt = 0
    while attempt < retries:
        try:
            if url.startswith("file://"):
                with open(url[7:], "r") as f:
                    content = f.read()
            else:
                # Check IGNORE_SSL_SPEC env var
                ignore_ssl_spec = os.getenv("IGNORE_SSL_SPEC", "false").lower() in ("true", "1", "yes")
                verify_ssl_spec = not ignore_ssl_spec
                headers = handle_auth({"method": "GET"})
                logger.debug(f"Fetching spec with SSL verification: {verify_ssl_spec} (IGNORE_SSL_SPEC={ignore_ssl_spec})")
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

def register_functions(spec: Dict) -> List[types.Tool]:
    """Register tools from OpenAPI spec."""
    from .utils import normalize_tool_name, is_tool_whitelisted
    
    tools: List[types.Tool] = []
    logger.debug("Clearing previously registered tools to allow re-registration")
    if not spec:
        logger.error("OpenAPI spec is None or empty.")
        return tools
    if 'paths' not in spec:
        logger.error("No 'paths' key in OpenAPI spec.")
        return tools
    logger.debug(f"Spec paths available: {list(spec['paths'].keys())}")
    filtered_paths = {path: item for path, item in spec['paths'].items() if is_tool_whitelisted(path)}
    logger.debug(f"Filtered paths: {list(filtered_paths.keys())}")
    if not filtered_paths:
        logger.warning("No whitelisted paths found in OpenAPI spec after filtering.")
        return tools
    for path, path_item in filtered_paths.items():
        if not path_item:
            logger.debug(f"Empty path item for {path}")
            continue
        for method, operation in path_item.items():
            if method.lower() not in ['get', 'post', 'put', 'delete', 'patch']:
                logger.debug(f"Skipping unsupported method {method} for {path}")
                continue
            try:
                raw_name = f"{method.upper()} {path}"
                function_name = normalize_tool_name(raw_name)
                description = operation.get('summary', operation.get('description', 'No description available'))
                input_schema = {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False
                }
                parameters = operation.get('parameters', [])
                placeholder_params = [part.strip('{}') for part in path.split('/') if '{' in part and '}' in part]
                for param_name in placeholder_params:
                    input_schema['properties'][param_name] = {
                        "type": "string",
                        "description": f"Path parameter {param_name}"
                    }
                    input_schema['required'].append(param_name)
                    logger.debug(f"Added URI placeholder {param_name} to inputSchema for {function_name}")
                for param in parameters:
                    param_name = param.get('name')
                    param_in = param.get('in')
                    if param_in in ['path', 'query']:
                        param_type = param.get('schema', {}).get('type', 'string')
                        schema_type = param_type if param_type in ['string', 'integer', 'boolean', 'number'] else 'string'
                        input_schema['properties'][param_name] = {
                            "type": schema_type,
                            "description": param.get('description', f"{param_in} parameter {param_name}")
                        }
                        if param.get('required', False) and param_name not in input_schema['required']:
                            input_schema['required'].append(param_name)
                tool = types.Tool(
                    name=function_name,
                    description=description,
                    inputSchema=input_schema,
                )
                tools.append(tool)
                logger.debug(f"Registered function: {function_name} ({method.upper()} {path}) with inputSchema: {json.dumps(input_schema)}")
            except Exception as e:
                logger.error(f"Error registering function for {method.upper()} {path}: {e}", exc_info=True)
    logger.debug(f"Registered {len(tools)} functions from OpenAPI spec.")
    from . import server_lowlevel
    server_lowlevel.tools.clear()
    server_lowlevel.tools.extend(tools)
    return tools

def lookup_operation_details(function_name: str, spec: Dict) -> Union[Dict, None]:
    """Look up operation details from OpenAPI spec by function name."""
    if not spec or 'paths' not in spec:
        return None
    for path, path_item in spec['paths'].items():
        for method, operation in path_item.items():
            if method.lower() not in ['get', 'post', 'put', 'delete', 'patch']:
                continue
            raw_name = f"{method.upper()} {path}"
            current_function_name = normalize_tool_name(raw_name)
            if current_function_name == function_name:
                return {"path": path, "method": method.upper(), "operation": operation, "original_path": path}
    return None