"""
Tests for security hardening features.
"""

import pytest
from mcp_openapi_proxy.security import (
    validate_url_safe,
    check_spec_size_limit,
    check_tools_count_limit,
    check_response_size_limit,
    sanitize_header_value,
    validate_tool_arguments,
    SecurityError,
)


class TestURLValidation:
    """Test SSRF prevention via URL validation."""
    
    def test_https_url_allowed(self):
        """Public HTTPS URLs should be allowed."""
        is_safe, error = validate_url_safe("https://api.example.com/spec.json")
        assert is_safe is True
        assert error is None
    
    def test_http_url_allowed(self):
        """Public HTTP URLs should be allowed (though not recommended)."""
        is_safe, error = validate_url_safe("http://api.example.com/spec.json")
        assert is_safe is True
        assert error is None
    
    def test_localhost_blocked(self):
        """Localhost URLs should be blocked by default."""
        is_safe, error = validate_url_safe("http://localhost:8080/spec.json")
        assert is_safe is False
        assert "localhost" in error.lower()
    
    def test_127_0_0_1_blocked(self):
        """Loopback IP should be blocked."""
        is_safe, error = validate_url_safe("http://127.0.0.1:8080/spec.json")
        assert is_safe is False
        assert "loopback" in error.lower()
    
    def test_private_ip_blocked(self):
        """Private IP ranges should be blocked."""
        test_cases = [
            "http://192.168.1.1/spec.json",
            "http://10.0.0.1/spec.json",
            "http://172.16.0.1/spec.json",
        ]
        for url in test_cases:
            is_safe, error = validate_url_safe(url)
            assert is_safe is False, f"Expected {url} to be blocked"
            assert "private" in error.lower()
    
    def test_aws_metadata_blocked(self):
        """AWS metadata endpoint should be blocked."""
        is_safe, error = validate_url_safe("http://169.254.169.254/latest/meta-data/")
        assert is_safe is False
        assert "metadata" in error.lower()
    
    def test_link_local_blocked(self):
        """Link-local addresses should be blocked."""
        is_safe, error = validate_url_safe("http://169.254.1.1/spec.json")
        assert is_safe is False
        assert "link-local" in error.lower() or "reserved" in error.lower()
    
    def test_localhost_allowed_in_dev_mode(self):
        """Localhost should be allowed when explicitly permitted."""
        is_safe, error = validate_url_safe("http://localhost:8080/spec.json", allow_local=True)
        assert is_safe is True
        assert error is None
    
    def test_ftp_blocked(self):
        """Non-HTTP schemes should be blocked."""
        is_safe, error = validate_url_safe("ftp://example.com/spec.json")
        assert is_safe is False
        assert "scheme" in error.lower()
    
    def test_no_hostname(self):
        """URLs without hostname should be rejected."""
        is_safe, error = validate_url_safe("http:///spec.json")
        assert is_safe is False
        assert "hostname" in error.lower()


class TestSizeLimits:
    """Test resource consumption limits."""
    
    def test_spec_size_within_limit(self):
        """Spec within size limit should pass."""
        small_content = "x" * 1000  # 1KB
        check_spec_size_limit(content=small_content)  # Should not raise
    
    def test_spec_size_exceeds_limit(self, monkeypatch):
        """Spec exceeding size limit should raise SecurityError."""
        monkeypatch.setenv("MAX_SPEC_SIZE_MB", "1")
        large_content = "x" * (2 * 1024 * 1024)  # 2MB
        with pytest.raises(SecurityError) as exc_info:
            check_spec_size_limit(content=large_content)
        assert "exceeds limit" in str(exc_info.value)
    
    def test_spec_size_content_length_check(self, monkeypatch):
        """Content-Length header should be checked."""
        monkeypatch.setenv("MAX_SPEC_SIZE_MB", "1")
        content_length = 2 * 1024 * 1024  # 2MB
        with pytest.raises(SecurityError):
            check_spec_size_limit(content_length=content_length)
    
    def test_tools_count_within_limit(self):
        """Tool count within limit should pass."""
        check_tools_count_limit(100)  # Should not raise
    
    def test_tools_count_exceeds_limit(self, monkeypatch):
        """Tool count exceeding limit should raise SecurityError."""
        monkeypatch.setenv("MAX_TOOLS_COUNT", "10")
        with pytest.raises(SecurityError) as exc_info:
            check_tools_count_limit(100)
        assert "exceeds limit" in str(exc_info.value)
    
    def test_response_size_within_limit(self):
        """Response within size limit should pass."""
        small_content = "x" * 1000
        check_response_size_limit(content=small_content)  # Should not raise
    
    def test_response_size_exceeds_limit(self, monkeypatch):
        """Response exceeding size limit should raise SecurityError."""
        monkeypatch.setenv("MAX_RESPONSE_SIZE_MB", "1")
        large_content = "x" * (2 * 1024 * 1024)
        with pytest.raises(SecurityError):
            check_response_size_limit(content=large_content)


class TestHeaderSanitization:
    """Test header value sanitization."""
    
    def test_clean_header_unchanged(self):
        """Clean header values should pass through."""
        value = "application/json; charset=utf-8"
        assert sanitize_header_value(value) == value
    
    def test_newline_stripped(self):
        """Newlines should be stripped (prevents header injection)."""
        value = "safe\r\nmalicious: injected"
        sanitized = sanitize_header_value(value)
        assert "\r" not in sanitized
        assert "\n" not in sanitized
    
    def test_control_characters_stripped(self):
        """Control characters should be stripped."""
        value = "value\x00with\x1fcontrol\x7fchars"
        sanitized = sanitize_header_value(value)
        assert "\x00" not in sanitized
        assert "\x1f" not in sanitized
        assert "\x7f" not in sanitized
    
    def test_whitespace_normalized(self):
        """Multiple spaces should be normalized."""
        value = "value    with     spaces"
        sanitized = sanitize_header_value(value)
        assert "    " not in sanitized
    
    def test_long_value_truncated(self):
        """Very long values should be truncated."""
        value = "x" * 5000
        sanitized = sanitize_header_value(value)
        assert len(sanitized) <= 2048


class TestToolArgumentValidation:
    """Test tool argument validation."""
    
    def test_simple_arguments_valid(self):
        """Simple arguments should pass."""
        args = {"name": "test", "count": 42, "enabled": True}
        validate_tool_arguments(args)  # Should not raise
    
    def test_nested_arguments_valid(self):
        """Reasonably nested arguments should pass."""
        args = {
            "user": {
                "name": "test",
                "profile": {
                    "age": 30,
                    "city": "NYC"
                }
            }
        }
        validate_tool_arguments(args)  # Should not raise
    
    def test_excessive_nesting_rejected(self):
        """Deeply nested arguments should be rejected."""
        # Create deeply nested structure
        args = {"a": {}}
        current = args["a"]
        for i in range(20):
            current["b"] = {}
            current = current["b"]
        
        with pytest.raises(SecurityError) as exc_info:
            validate_tool_arguments(args, max_depth=10)
        assert "nesting depth" in str(exc_info.value)
    
    def test_long_string_rejected(self):
        """Excessively long strings should be rejected."""
        args = {"payload": "x" * 20000}
        with pytest.raises(SecurityError) as exc_info:
            validate_tool_arguments(args, max_string_length=10000)
        assert "string too long" in str(exc_info.value)
    
    def test_large_array_rejected(self):
        """Excessively large arrays should be rejected."""
        args = {"items": list(range(2000))}
        with pytest.raises(SecurityError) as exc_info:
            validate_tool_arguments(args)
        assert "array too large" in str(exc_info.value)
    
    def test_long_key_rejected(self):
        """Excessively long keys should be rejected."""
        args = {"x" * 500: "value"}
        with pytest.raises(SecurityError) as exc_info:
            validate_tool_arguments(args)
        assert "key too long" in str(exc_info.value)
    
    def test_array_of_objects_valid(self):
        """Arrays of objects within limits should pass."""
        args = {
            "users": [
                {"name": "alice", "age": 30},
                {"name": "bob", "age": 25}
            ]
        }
        validate_tool_arguments(args)  # Should not raise
