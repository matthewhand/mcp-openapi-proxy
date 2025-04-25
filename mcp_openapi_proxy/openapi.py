"""
OpenAPI specification handling for mcp-openapi-proxy.
"""

import os
import json
import re # Import the re module
import requests
import yaml
from typing import Dict, Optional, List, Union
from urllib.parse import unquote, quote
from mcp import types
from mcp_openapi_proxy.utils import normalize_tool_name
from .logging_setup import logger

# Define the required tool name pattern
TOOL_NAME_REGEX = r"^[a-zA-Z0-9_-]{1,64}$"

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
        except FileNotFoundError as e:
             logger.error(f"Failed to open local file spec {url}: {e}")
             return None
        except Exception as e:
             attempt += 1
             logger.warning(f"Unexpected error during fetch attempt {attempt}/{retries}: {e}")
             if attempt == retries:
                 logger.error(f"Failed to process spec from {url} after {retries} attempts due to unexpected error: {e}")
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
         # Ensure servers is a list and has items before accessing index 0
         if isinstance(spec["servers"], list) and len(spec["servers"]) > 0 and isinstance(spec["servers"][0], dict):
              server_url = spec["servers"][0].get("url")
              if server_url:
                  logger.debug(f"Using first server URL from spec: {server_url}")
                  return server_url
              else:
                  logger.warning("First server entry in spec missing 'url' key.")
         else:
              logger.warning("Spec 'servers' key is not a non-empty list of dictionaries.")

    # Fallback for OpenAPI v2 (Swagger)
    if "host" in spec and "schemes" in spec:
         scheme = spec["schemes"][0] if spec.get("schemes") else "https"
         base_path = spec.get("basePath", "")
         host = spec.get("host")
         if host:
             v2_url = f"{scheme}://{host}{base_path}"
             logger.debug(f"Using OpenAPI v2 host/schemes/basePath: {v2_url}")
             return v2_url
         else:
             logger.warning("OpenAPI v2 spec missing 'host'.")

    logger.error("Could not determine base URL from spec (servers/host/schemes) or SERVER_URL_OVERRIDE.")
    return None

def handle_auth(operation: Dict) -> Dict[str, str]:
    """Handle authentication based on environment variables and operation security."""
    headers = {}
    api_key = os.getenv("API_KEY")
    auth_type = os.getenv("API_AUTH_TYPE", "Bearer").lower()
    if api_key:
        if auth_type == "bearer":
            logger.debug(f"Using API_KEY as Bearer token.") # Avoid logging key prefix
            headers["Authorization"] = f"Bearer {api_key}"
        elif auth_type == "basic":
            logger.warning("API_AUTH_TYPE is Basic, but Basic Auth is not fully implemented yet.")
            # Potentially add basic auth implementation here if needed
        elif auth_type == "api-key":
            key_name = os.getenv("API_AUTH_HEADER", "Authorization")
            headers[key_name] = api_key
            logger.debug(f"Using API_KEY as API-Key in header '{key_name}'.") # Avoid logging key prefix
        else:
             logger.warning(f"Unsupported API_AUTH_TYPE: {auth_type}")
    # TODO: Add logic to check operation['security'] and spec['components']['securitySchemes']
    #       to potentially override or supplement env var based auth.
    return headers

def register_functions(spec: Dict) -> List[types.Tool]:
    """Register tools from OpenAPI spec."""
    from .utils import is_tool_whitelisted # Keep import here to avoid circular dependency if utils imports openapi

    tools_list: List[types.Tool] = [] # Use a local list for registration
    logger.debug("Starting tool registration from OpenAPI spec.")
    if not spec:
        logger.error("OpenAPI spec is None or empty during registration.")
        return tools_list
    if 'paths' not in spec:
        logger.error("No 'paths' key in OpenAPI spec during registration.")
        return tools_list

    logger.debug(f"Available paths in spec: {list(spec['paths'].keys())}")
    # Filter paths based on whitelist *before* iterating
    # Note: is_tool_whitelisted expects the path string
    filtered_paths = {
        path: item
        for path, item in spec['paths'].items()
        if is_tool_whitelisted(path)
    }
    logger.debug(f"Paths after whitelist filtering: {list(filtered_paths.keys())}")

    if not filtered_paths:
        logger.warning("No whitelisted paths found in OpenAPI spec after filtering. No tools will be registered.")
        return tools_list

    registered_names = set() # Keep track of names to detect duplicates

    for path, path_item in filtered_paths.items():
        if not path_item or not isinstance(path_item, dict):
            logger.debug(f"Skipping empty or invalid path item for {path}")
            continue
        for method, operation in path_item.items():
            # Check if method is a valid HTTP verb and operation is a dictionary
            if method.lower() not in ['get', 'post', 'put', 'delete', 'patch', 'options', 'head', 'trace'] or not isinstance(operation, dict):
                # logger.debug(f"Skipping non-operation entry or unsupported method '{method}' for path '{path}'")
                continue
            try:
                raw_name = f"{method.upper()} {path}"
                function_name = normalize_tool_name(raw_name)

                # --- Add Regex Validation Step ---
                if not re.match(TOOL_NAME_REGEX, function_name):
                    logger.error(
                        f"Skipping registration for '{raw_name}': "
                        f"Generated name '{function_name}' does not match required pattern '{TOOL_NAME_REGEX}'."
                    )
                    continue # Skip this tool

                # --- Check for duplicate names ---
                if function_name in registered_names:
                    logger.warning(
                        f"Skipping registration for '{raw_name}': "
                        f"Duplicate tool name '{function_name}' detected."
                    )
                    continue # Skip this tool

                description = operation.get('summary', operation.get('description', 'No description available'))
                # Ensure description is a string
                if not isinstance(description, str):
                    logger.warning(f"Description for {function_name} is not a string, using default.")
                    description = "No description available"

                # --- Build Input Schema ---
                input_schema = {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False # Explicitly set additionalProperties to False
                }
                # Process parameters defined directly under the operation
                op_params = operation.get('parameters', [])
                # Process parameters defined at the path level (common parameters)
                path_params = path_item.get('parameters', [])
                # Combine parameters, giving operation-level precedence if names clash (though unlikely per spec)
                all_params = {p.get('name'): p for p in path_params if isinstance(p, dict) and p.get('name')}
                all_params.update({p.get('name'): p for p in op_params if isinstance(p, dict) and p.get('name')})

                for param_name, param_details in all_params.items():
                    if not param_name or not isinstance(param_details, dict):
                        continue # Skip invalid parameter definitions

                    param_in = param_details.get('in')
                    # We primarily care about 'path' and 'query' for simple input schema generation
                    # Body parameters are handled differently (often implicitly the whole input)
                    if param_in in ['path', 'query']:
                        param_schema = param_details.get('schema', {})
                        prop_type = param_schema.get('type', 'string')
                        # Basic type mapping, default to string
                        schema_type = prop_type if prop_type in ['string', 'integer', 'boolean', 'number', 'array'] else 'string'

                        input_schema['properties'][param_name] = {
                            "type": schema_type,
                            "description": param_details.get('description', f"{param_in} parameter {param_name}")
                        }
                        # Add format if available
                        if param_schema.get('format'):
                             input_schema['properties'][param_name]['format'] = param_schema.get('format')
                        # Add enum if available
                        if param_schema.get('enum'):
                             input_schema['properties'][param_name]['enum'] = param_schema.get('enum')

                        if param_details.get('required', False):
                            # Only add to required if not already present (e.g., from path template)
                            if param_name not in input_schema['required']:
                                input_schema['required'].append(param_name)

                # Add path parameters derived from the path template itself (e.g., /users/{id})
                # These are always required and typically strings
                template_params = re.findall(r"\{([^}]+)\}", path)
                for tp_name in template_params:
                     if tp_name not in input_schema['properties']:
                          input_schema['properties'][tp_name] = {
                               "type": "string", # Path params are usually strings
                               "description": f"Path parameter '{tp_name}'"
                          }
                     if tp_name not in input_schema['required']:
                          input_schema['required'].append(tp_name)


                # Handle request body (for POST, PUT, PATCH)
                request_body = operation.get('requestBody')
                if request_body and isinstance(request_body, dict):
                     content = request_body.get('content')
                     if content and isinstance(content, dict):
                          # Prefer application/json if available
                          json_content = content.get('application/json')
                          if json_content and isinstance(json_content, dict) and 'schema' in json_content:
                               body_schema = json_content['schema']
                               # If body schema is object with properties, merge them
                               if body_schema.get('type') == 'object' and 'properties' in body_schema:
                                    input_schema['properties'].update(body_schema['properties'])
                                    if 'required' in body_schema and isinstance(body_schema['required'], list):
                                         # Add required body properties, avoiding duplicates
                                         for req_prop in body_schema['required']:
                                              if req_prop not in input_schema['required']:
                                                   input_schema['required'].append(req_prop)
                               # If body schema is not an object or has no properties,
                               # maybe represent it as a single 'body' parameter? Needs decision.
                               # else:
                               #    input_schema['properties']['body'] = body_schema
                               #    if request_body.get('required', False):
                               #         input_schema['required'].append('body')


                # Create and register the tool
                tool = types.Tool(
                    name=function_name,
                    description=description,
                    inputSchema=input_schema,
                )
                tools_list.append(tool)
                registered_names.add(function_name)
                logger.debug(f"Registered tool: {function_name} from {raw_name}") # Simplified log

            except Exception as e:
                logger.error(f"Error registering function for {method.upper()} {path}: {e}", exc_info=True)

    logger.info(f"Successfully registered {len(tools_list)} tools from OpenAPI spec.")

    # Update the global/shared tools list if necessary (depends on server implementation)
    # Example for lowlevel server:
    from . import server_lowlevel
    if hasattr(server_lowlevel, 'tools'):
         logger.debug("Updating server_lowlevel.tools list.")
         server_lowlevel.tools.clear()
         server_lowlevel.tools.extend(tools_list)
    # Add similar logic if needed for fastmcp server or remove if registration happens differently there

    return tools_list # Return the list of registered tools

def lookup_operation_details(function_name: str, spec: Dict) -> Union[Dict, None]:
    """Look up operation details from OpenAPI spec by function name."""
    if not spec or 'paths' not in spec:
        logger.warning("Spec is missing or has no 'paths' key in lookup_operation_details.")
        return None

    # Pre-compile regex for faster matching if called frequently (though likely not needed here)
    # TOOL_NAME_REGEX_COMPILED = re.compile(TOOL_NAME_REGEX)

    for path, path_item in spec['paths'].items():
         if not isinstance(path_item, dict): continue # Skip invalid path items
         for method, operation in path_item.items():
             if method.lower() not in ['get', 'post', 'put', 'delete', 'patch', 'options', 'head', 'trace'] or not isinstance(operation, dict):
                 continue
             raw_name = f"{method.upper()} {path}"
             # Regenerate the name using the exact same logic as registration
             current_function_name = normalize_tool_name(raw_name)

             # Validate the looked-up name matches the required pattern *before* comparing
             # This ensures we don't accidentally match an invalid name during lookup
             if not re.match(TOOL_NAME_REGEX, current_function_name):
                  # Log this? It indicates an issue either in normalization or the spec itself
                  # logger.warning(f"Normalized name '{current_function_name}' for '{raw_name}' is invalid during lookup.")
                  continue # Skip potentially invalid names

             if current_function_name == function_name:
                 logger.debug(f"Found operation details for '{function_name}' at {method.upper()} {path}")
                 return {"path": path, "method": method.upper(), "operation": operation, "original_path": path}

    logger.warning(f"Could not find operation details for function name: '{function_name}'")
    return None
