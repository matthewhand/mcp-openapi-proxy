# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Automated OpenAPI spec URL validation script (`scripts/validate_openapi_urls.py`)
- Deep diagnostics script for example configs (`scripts/diagnose_examples.py`)
- CI workflows for validation and diagnostics
- Comprehensive README with CI badges, onboarding, and troubleshooting
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, SUPPORT.md, FAQ.md, PULL_REQUEST_TEMPLATE.md
- requirements.txt with core, dev, and test dependencies
- .gitignore for secrets, env, and editor files
- Black formatting and flake8 linting enforced
- Integration and unit tests for validation, diagnostics, and runtime logic

### Changed
- All code formatted with Black and checked with flake8

### Fixed
- None yet (project is fully validated and tested)

## [0.1.0] - 2025-04-20
### Added
- Initial release with OpenAPI proxy core functionality
