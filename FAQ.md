# Frequently Asked Questions (FAQ)

> For full project context, see the [README](README.md) and [CONTRIBUTING](CONTRIBUTING.md) guides.

## 1. Why do my PRs fail with unreachable OpenAPI spec URLs?

All example configs must reference reachable, valid OpenAPI spec URLs. The CI and validation scripts will block merges if any URL returns a non-200 status. Use `python3 scripts/validate_openapi_urls.py` to check locally before submitting.

## 2. How do I interpret the diagnostics markdown output?

- **HTTP Status**: Should be `Success` for all production configs.
- **Spec Valid**: Should be `✅` (valid OpenAPI/Swagger) for production configs.
- **Missing Env Vars**: Set all required secrets in your local `.env` or CI environment for full integration tests.
- **Errors**: If you see errors like `No mcpServers found`, ensure your config follows the standard structure.

## 3. What if my config is for a demo or intentionally unreachable URL?

- Clearly document this in the README (see the Jellyfin demo example).
- These configs should not block CI or production validation.

## 4. How do I add a new example config?

- Follow the structure of existing configs in `examples/`.
- Use unique and reachable OpenAPI spec URLs.
- Document any demo or intentionally failing configs in the README.

## 5. What environment variables do I need to set?

- The diagnostics script will list any missing required environment variables for each config.
- Set these in your `.env` file or CI environment as needed.

## 6. What are the security best practices and how do I report a vulnerability?

- See the [SECURITY.md](SECURITY.md) policy for how to report vulnerabilities.
- Never commit secrets, API keys, or sensitive data to the repository. Use `.env` files or CI secrets.
- All OpenAPI spec URLs are validated before use to prevent SSRF and related attacks.

## 7. What are the community expectations and code of conduct?

- Participation in this project is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). All contributors and users are expected to uphold these standards.

## 8. Where can I get help?

- Open an issue or start a discussion on GitHub if you have questions about diagnostics, validation, or contributing.
