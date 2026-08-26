# Security Hardening Guide

This document describes the security features and best practices for deploying mcp-openapi-proxy in production environments.

## Security Features

### 1. SSRF (Server-Side Request Forgery) Prevention

The proxy validates all URLs before fetching OpenAPI specifications to prevent SSRF attacks.

**Protected Against:**
- Private IP ranges (RFC1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- Loopback addresses (127.0.0.0/8, ::1)
- Link-local addresses (169.254.0.0/16)
- Cloud metadata endpoints (169.254.169.254, metadata.google.internal)
- Non-HTTP(S) protocols (ftp, file, gopher, etc.)

**Configuration:**

```bash
# Production mode (default): all protections active
ENVIRONMENT=production

# Development mode: allows relaxing restrictions
ENVIRONMENT=development
ALLOW_LOCAL_URLS=true  # Only in development!
```

**Never use `ALLOW_LOCAL_URLS=true` in production.**

### 2. Resource Consumption Limits

Limits prevent denial-of-service attacks via excessive resource consumption.

**Configuration:**

```bash
# Maximum OpenAPI spec size (default: 10 MB)
MAX_SPEC_SIZE_MB=10

# Maximum number of registered tools (default: 1000)
MAX_TOOLS_COUNT=1000

# Maximum API response size (default: 5 MB)
MAX_RESPONSE_SIZE_MB=5
```

**Recommendations:**
- Set `MAX_SPEC_SIZE_MB` based on your largest legitimate spec
- Use `TOOL_WHITELIST` to reduce tool count for large APIs
- Adjust `MAX_RESPONSE_SIZE_MB` based on expected payload sizes

### 3. SSL/TLS Verification

SSL certificate verification is enforced in production mode.

**Configuration:**

```bash
# For spec downloads
IGNORE_SSL_SPEC=false  # Default

# For API calls
IGNORE_SSL_TOOLS=false  # Default

# Environment detection
ENVIRONMENT=production  # Enforces SSL verification
```

**In production mode**, `IGNORE_SSL_SPEC=true` is automatically overridden to `false` to prevent man-in-the-middle attacks.

**Development mode only:**
```bash
ENVIRONMENT=development
IGNORE_SSL_SPEC=true  # Only for local testing
```

### 4. Credential Protection

API keys and secrets are protected from exposure.

**Best Practices:**

1. **Never log credentials**
   - The proxy no longer logs API key prefixes
   - Error messages are sanitized to prevent leakage

2. **Use environment variables**
   ```bash
   # Good: credentials from environment
   API_KEY="${YOUR_API_KEY}"
   
   # Bad: credentials in config files (committed to git)
   API_KEY="sk-1234567890abcdef"
   ```

3. **Restrict process visibility**
   ```bash
   # Run proxy as non-root user
   sudo -u mcp-proxy uvx mcp-openapi-proxy
   ```

4. **Rotate credentials regularly**
   - Set up credential rotation schedules
   - Use time-limited tokens when available

### 5. Input Validation

Tool arguments are validated to prevent abuse.

**Protections:**
- Maximum nesting depth (default: 10 levels)
- Maximum string length (default: 10,000 characters)
- Maximum array size (default: 1,000 elements)
- Maximum key length (default: 256 characters)

**Automatically enforced** - no configuration required.

### 6. Header Injection Prevention

HTTP headers are sanitized to prevent injection attacks.

**Protections:**
- Control characters stripped (including \r, \n, \x00)
- Whitespace normalized
- Length limited (max 2,048 characters per header value)

**Example:**
```bash
# This malicious header value is sanitized automatically
EXTRA_HEADERS='["X-Custom: safe\r\nX-Injected: malicious"]'
# Result: X-Custom: safe X-Injected: malicious (newlines removed)
```

## Deployment Checklist

### Required for Production

- [ ] Set `ENVIRONMENT=production`
- [ ] Never use `ALLOW_LOCAL_URLS=true`
- [ ] Never use `IGNORE_SSL_SPEC=true` or `IGNORE_SSL_TOOLS=true`
- [ ] Configure resource limits based on expected load
- [ ] Use `TOOL_WHITELIST` to minimize attack surface
- [ ] Store credentials securely (use secrets management)
- [ ] Run as non-root user with minimal permissions
- [ ] Enable audit logging (recommended)
- [ ] Set up monitoring and alerting

### Recommended Security Measures

1. **Network Isolation**
   ```bash
   # Run proxy in isolated network segment
   # Only allow outbound HTTPS to known API domains
   # Block all inbound connections except from MCP clients
   ```

2. **Firewall Rules**
   ```bash
   # Block access to private IP ranges at firewall level
   iptables -A OUTPUT -d 10.0.0.0/8 -j REJECT
   iptables -A OUTPUT -d 172.16.0.0/12 -j REJECT
   iptables -A OUTPUT -d 192.168.0.0/16 -j REJECT
   iptables -A OUTPUT -d 169.254.0.0/16 -j REJECT
   ```

3. **Least Privilege**
   ```bash
   # Create dedicated user
   sudo useradd -r -s /bin/false mcp-proxy
   
   # Run as that user
   sudo -u mcp-proxy uvx mcp-openapi-proxy
   ```

4. **Resource Limits (systemd)**
   ```ini
   [Service]
   # Limit memory
   MemoryMax=512M
   MemoryHigh=384M
   
   # Limit file descriptors
   LimitNOFILE=1024
   
   # Limit CPU
   CPUQuota=50%
   ```

5. **Cache Security**
   ```bash
   # Secure cache directory permissions
   mkdir -p ~/.cache/mcp-openapi-proxy
   chmod 700 ~/.cache/mcp-openapi-proxy
   ```

## Security Monitoring

### Key Metrics to Monitor

1. **Unusual API usage patterns**
   - Sudden spike in tool calls
   - Calls to tools not typically used
   - Failed authentication attempts

2. **Resource consumption**
   - Memory usage trending upward
   - CPU usage spikes
   - Excessive network traffic

3. **Security events**
   - URL validation failures (potential SSRF attempts)
   - Size limit violations (potential DoS attempts)
   - Header sanitization triggers (potential injection attempts)

### Logging Configuration

```bash
# Enable debug logging for security events
DEBUG=true

# Redirect logs to secure location
uvx mcp-openapi-proxy 2>&1 | tee -a /var/log/mcp-proxy/security.log

# Protect log files
chmod 600 /var/log/mcp-proxy/security.log
```

**Review logs regularly for:**
- `URL validation failed` - potential SSRF attempts
- `exceeds limit` - potential DoS attempts  
- `sanitized` or `stripped` - potential injection attempts

## Incident Response

### If You Suspect a Security Breach

1. **Immediate Actions**
   ```bash
   # Stop the proxy
   systemctl stop mcp-openapi-proxy
   
   # Rotate all API keys
   # (specific to each API)
   
   # Review logs for indicators of compromise
   grep -i "validation failed\|exceeds limit\|error" /var/log/mcp-proxy/*.log
   ```

2. **Investigation**
   - Identify which tools were called and when
   - Check for unusual API response patterns
   - Review firewall logs for unexpected connections
   - Check for unauthorized changes to configuration

3. **Recovery**
   - Update to latest version
   - Review and tighten security configuration
   - Re-deploy with enhanced monitoring
   - Document lessons learned

## Reporting Security Issues

**Do not report security vulnerabilities in public GitHub issues.**

To report a security vulnerability:
1. Email the maintainer privately (see README for contact)
2. Include detailed steps to reproduce
3. Provide suggested fixes if possible
4. Allow reasonable time for fix before public disclosure

## Security Limitations

### Known Limitations

1. **No built-in rate limiting**
   - Implement at reverse proxy or API gateway level
   - Recommendation: nginx with `limit_req_zone`

2. **No authentication between client and proxy**
   - The proxy trusts all MCP clients
   - Secure the stdio/pipe connection appropriately

3. **No audit trail**
   - Tool calls are logged but not in a structured format
   - Consider external audit logging solution

4. **Response content not validated**
   - API responses are passed through without schema validation
   - Malformed responses from APIs could confuse clients

### Defense in Depth

The proxy's security features are one layer. For production:

```
[MCP Client] 
    ↓ (authenticated connection)
[Reverse Proxy] (rate limiting, WAF)
    ↓ (network isolation)
[mcp-openapi-proxy] (SSRF prevention, input validation)
    ↓ (firewall rules, egress filtering)
[External API] (OAuth, API keys)
```

Each layer provides defense against different attack vectors.

## Security Updates

Stay informed about security updates:
- Watch the GitHub repository for security advisories
- Subscribe to release notifications
- Review CHANGELOG.md for security fixes
- Apply updates promptly

**Current Version:** 0.3.3  
**Last Security Review:** 2026-08-27

---

*This security guide is maintained as part of the skeptical review process and will be updated as new threats are identified and mitigated.*
