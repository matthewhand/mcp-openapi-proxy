"""
Security utilities for mcp-openapi-proxy.

This module provides security hardening for URL fetching, input validation,
and resource limiting to prevent common vulnerabilities.
"""

import os
import re
import ipaddress
from typing import Optional, Tuple
from urllib.parse import urlparse
from .logging_setup import logger


# Configuration constants
DEFAULT_MAX_SPEC_SIZE_MB = 10
DEFAULT_MAX_TOOLS_COUNT = 1000
DEFAULT_MAX_RESPONSE_SIZE_MB = 5

# Cloud metadata endpoints that should be blocked (SSRF prevention)
CLOUD_METADATA_ENDPOINTS = [
    "169.254.169.254",  # AWS, Azure, GCP
    "metadata.google.internal",  # GCP
    "169.254.169.253",  # Azure backup endpoint
    "fd00:ec2::254",  # AWS IPv6
]


class SecurityError(Exception):
    """Raised when a security constraint is violated."""
    pass


def validate_url_safe(url: str, allow_local: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Validate that a URL is safe to fetch (SSRF prevention).
    
    Returns: (is_valid, error_message)
    
    Blocks:
    - Non-http(s) schemes
    - Private IP ranges (RFC1918)
    - Loopback addresses
    - Link-local addresses
    - Cloud metadata endpoints
    - IPv6 private ranges
    
    Args:
        url: URL to validate
        allow_local: If True, allow localhost/private IPs (for development only)
    """
    try:
        parsed = urlparse(url)
        
        # Check scheme
        if parsed.scheme not in ["http", "https"]:
            return False, f"URL scheme '{parsed.scheme}' not allowed. Only http/https permitted."
        
        # Allow file:// URLs to pass through (handled separately)
        if parsed.scheme == "file":
            return True, None
            
        # Extract hostname
        hostname = parsed.hostname
        if not hostname:
            return False, "URL has no hostname"
        
        # Check for cloud metadata endpoints
        if hostname in CLOUD_METADATA_ENDPOINTS:
            return False, f"Access to cloud metadata endpoint '{hostname}' is blocked (SSRF protection)"
        
        # For development, allow localhost if explicitly enabled
        if allow_local:
            logger.warning(f"URL validation: allow_local=True, permitting potentially unsafe URL: {url}")
            return True, None
        
        # Try to resolve to IP address
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            # Not a direct IP, might be hostname. Try to parse anyway for known patterns
            # Block obvious localhost patterns
            if hostname in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                return False, f"Access to localhost/loopback '{hostname}' is blocked (SSRF protection)"
            
            # Block localhost subdomains
            if ".localhost" in hostname or hostname.endswith(".local"):
                return False, f"Access to local domain '{hostname}' is blocked (SSRF protection)"
            
            # If we can't resolve it to an IP, we'll allow it (DNS will fail naturally)
            # But we've blocked the obvious dangerous cases above
            return True, None
        
        # Check IP address ranges
        if ip.is_loopback:
            return False, f"Access to loopback address '{hostname}' is blocked (SSRF protection)"
        
        if ip.is_private:
            return False, f"Access to private IP address '{hostname}' is blocked (SSRF protection)"
        
        if ip.is_link_local:
            return False, f"Access to link-local address '{hostname}' is blocked (SSRF protection)"
        
        if ip.is_reserved:
            return False, f"Access to reserved IP address '{hostname}' is blocked (SSRF protection)"
        
        # Passed all checks
        return True, None
        
    except Exception as e:
        logger.error(f"Error validating URL safety: {e}", exc_info=True)
        return False, f"URL validation error: {str(e)}"


def check_spec_size_limit(content_length: Optional[int], content: Optional[str] = None) -> None:
    """
    Check if spec size is within limits.
    
    Raises SecurityError if size exceeds limit.
    """
    max_size_mb = int(os.getenv("MAX_SPEC_SIZE_MB", str(DEFAULT_MAX_SPEC_SIZE_MB)))
    max_size_bytes = max_size_mb * 1024 * 1024
    
    if content_length is not None:
        if content_length > max_size_bytes:
            raise SecurityError(
                f"OpenAPI spec size ({content_length / 1024 / 1024:.2f} MB) exceeds "
                f"limit of {max_size_mb} MB. Set MAX_SPEC_SIZE_MB to increase."
            )
    
    if content is not None:
        actual_size = len(content.encode('utf-8'))
        if actual_size > max_size_bytes:
            raise SecurityError(
                f"OpenAPI spec size ({actual_size / 1024 / 1024:.2f} MB) exceeds "
                f"limit of {max_size_mb} MB. Set MAX_SPEC_SIZE_MB to increase."
            )


def check_tools_count_limit(count: int) -> None:
    """
    Check if number of registered tools is within limits.
    
    Raises SecurityError if count exceeds limit.
    """
    max_tools = int(os.getenv("MAX_TOOLS_COUNT", str(DEFAULT_MAX_TOOLS_COUNT)))
    
    if count > max_tools:
        raise SecurityError(
            f"Tool count ({count}) exceeds limit of {max_tools}. "
            f"Use TOOL_WHITELIST to reduce scope, or set MAX_TOOLS_COUNT to increase."
        )


def check_response_size_limit(content_length: Optional[int] = None, content: Optional[str] = None) -> None:
    """
    Check if API response size is within limits.
    
    Raises SecurityError if size exceeds limit.
    """
    max_size_mb = int(os.getenv("MAX_RESPONSE_SIZE_MB", str(DEFAULT_MAX_RESPONSE_SIZE_MB)))
    max_size_bytes = max_size_mb * 1024 * 1024
    
    if content_length is not None:
        if content_length > max_size_bytes:
            raise SecurityError(
                f"API response size ({content_length / 1024 / 1024:.2f} MB) exceeds "
                f"limit of {max_size_mb} MB. Set MAX_RESPONSE_SIZE_MB to increase."
            )
    
    if content is not None:
        actual_size = len(content.encode('utf-8'))
        if actual_size > max_size_bytes:
            raise SecurityError(
                f"API response size ({actual_size / 1024 / 1024:.2f} MB) exceeds "
                f"limit of {max_size_mb} MB. Set MAX_RESPONSE_SIZE_MB to increase."
            )


def sanitize_header_value(value: str) -> str:
    """
    Sanitize a header value to prevent injection attacks.
    
    Strips dangerous characters and normalizes whitespace.
    """
    # Remove control characters (newlines, carriage returns, etc)
    sanitized = re.sub(r'[\r\n\x00-\x1f\x7f]', '', value)
    
    # Normalize whitespace
    sanitized = ' '.join(sanitized.split())
    
    # Truncate to reasonable length
    max_length = 2048
    if len(sanitized) > max_length:
        logger.warning(f"Header value truncated from {len(sanitized)} to {max_length} chars")
        sanitized = sanitized[:max_length]
    
    return sanitized


def validate_tool_arguments(arguments: dict, max_depth: int = 10, max_string_length: int = 10000) -> None:
    """
    Validate tool arguments to prevent abuse.
    
    Checks for:
    - Excessive nesting depth (DoS via deeply nested JSON)
    - Excessively long strings (memory exhaustion)
    - Suspicious patterns
    
    Raises SecurityError if validation fails.
    """
    def check_depth(obj, current_depth=0):
        if current_depth > max_depth:
            raise SecurityError(f"Tool arguments exceed maximum nesting depth of {max_depth}")
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Check key length
                if len(str(key)) > 256:
                    raise SecurityError(f"Tool argument key too long: {len(str(key))} chars")
                check_depth(value, current_depth + 1)
        elif isinstance(obj, list):
            if len(obj) > 1000:
                raise SecurityError(f"Tool argument array too large: {len(obj)} elements")
            for item in obj:
                check_depth(item, current_depth + 1)
        elif isinstance(obj, str):
            if len(obj) > max_string_length:
                raise SecurityError(f"Tool argument string too long: {len(obj)} chars")
    
    check_depth(arguments)


def is_development_mode() -> bool:
    """
    Check if running in development mode.
    
    In development mode, some security restrictions are relaxed.
    """
    return os.getenv("ENVIRONMENT", "production").lower() in ["development", "dev", "local"]


def should_allow_local_urls() -> bool:
    """
    Check if local URLs should be allowed.
    
    Only in development mode AND if explicitly enabled.
    """
    return (
        is_development_mode() and
        os.getenv("ALLOW_LOCAL_URLS", "false").lower() in ["true", "1", "yes"]
    )
