# Pull Request Checklist

Thank you for contributing to mcp-openapi-proxy! Please ensure you have completed the following before submitting your PR:

- [ ] **Validated all OpenAPI spec URLs:**
  - Ran `python3 scripts/validate_openapi_urls.py` and confirmed all URLs are reachable.
- [ ] **Ran advanced diagnostics:**
  - Ran `python3 scripts/diagnose_examples.py` and reviewed the markdown output for HTTP errors, invalid specs, and missing env vars.
- [ ] **Addressed all diagnostics issues:**
  - Fixed any errors or missing environment variables highlighted by diagnostics.
- [ ] **All CI checks pass:**
  - Confirmed that both validation and diagnostics workflows (see README badges) are passing in CI.
- [ ] **Documented any demo or failing configs:**
  - Clearly noted in the README if any example configs intentionally reference unreachable/demo URLs.

## Description

<!-- Please describe your changes and motivation. -->

## Related Issues

<!-- List any related issues, feature requests, or discussions. -->

## Additional Notes

<!-- Add any extra context or instructions for reviewers. -->
