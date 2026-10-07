# Contributing to mcp-openapi-proxy

Thank you for your interest in contributing! This project enforces rigorous validation and diagnostics for OpenAPI spec URLs and example configs. Please follow these guidelines to ensure a smooth review and integration process.

## Before You Submit a PR

### 1. Validate All OpenAPI Spec URLs
- Run the fast validation script to ensure all referenced OpenAPI spec URLs are reachable:
  ```bash
  python3 scripts/validate_openapi_urls.py
  ```
- The CI will also run this script on every push and pull request.

### 2. Run Advanced Diagnostics
- For deeper checks (missing env vars, spec validity, etc.), run:
  ```bash
  python3 scripts/diagnose_examples.py
  ```
- Review the markdown output for:
  - HTTP errors or unreachable specs
  - Invalid or unparsable specs
  - Missing required environment variables
- Address any issues before submitting your PR.

### 3. Interpreting Diagnostics Output
- **HTTP Status**: Should be `Success` for all production configs.
- **Spec Valid**: Should be `✅` (valid OpenAPI/Swagger) for production configs.
- **Missing Env Vars**: Set all required secrets in your local `.env` or CI environment for full integration tests.
- **Errors**: If you see errors like `No mcpServers found`, ensure your config follows the standard structure.

### 4. CI/CD
- All checks must pass before your PR can be merged.
- CI badges in the README provide live status of both fast and deep validation workflows.

## Adding New Example Configs
- Follow the structure of existing configs in `examples/`.
- Use unique and reachable OpenAPI spec URLs.
- Document any demo or intentionally failing configs clearly in the README.

## Code of Conduct

- Participation in this project is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). All contributors and community members are expected to uphold these standards.

## Security

- See the [SECURITY.md](SECURITY.md) policy for how to report vulnerabilities and best practices for contributors and users.
- Never commit secrets, API keys, or sensitive data to the repository. Use `.env` files or CI secrets.

## Questions?
- See the [FAQ](FAQ.md) for troubleshooting diagnostics, validation errors, and common contributor questions.
- Open an issue or start a discussion if you have further questions about diagnostics, validation, or contributing.
