# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in mcp-openapi-proxy, please report it privately.

- **Do not** open public issues for security problems.
- Email the maintainer at: matthew.hand.dev@gmail.com
- Include a detailed description and, if possible, steps to reproduce.

We will investigate and respond promptly. Responsible disclosure is appreciated.

## Security Best Practices

- All OpenAPI spec URLs are validated before use to prevent SSRF and related attacks.
- Example configs are checked for unreachable or malicious URLs in CI.
- Sensitive environment variables (API keys, tokens) should **never** be committed to the repository.
- Use `.env` files or CI secrets for sensitive data.

## Maintainer Contact
- Matthew Hand
- Email: matthew.hand.dev@gmail.com
