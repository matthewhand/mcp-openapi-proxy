# Changelog

## 0.3.4

### Fixed
- **Pin `mcp` to 1.x** (`mcp[cli]>=1.2.0,<2`). The previous unbounded
  `mcp>=1.2.0` constraint let a fresh `pip install mcp-openapi-proxy` resolve
  to the mcp 2.x SDK, a breaking rewrite that crashed **both server modes at
  import time**: FastMCP mode with `ModuleNotFoundError: No module named
  'mcp.server.fastmcp'` (renamed to `MCPServer` in 2.x), and low-level mode
  with a pydantic `ValidationError` constructing `types.Resource`
  (`uri` field type change). Regression tests added
  (`tests/unit/test_mcp_version_pin.py`) that fail closed on mcp 2.x and
  guard the declared constraint so 2.x cannot be silently selected again.
- `render` example: point `sample_mcpServers.json` at Render's live OpenAPI spec
  (`https://api-docs.render.com/openapi/render-public-api-1.json`). The previous
  id-based URL 302-redirects to `/404`, so the example registered **zero tools**.
  Now matches the URL already used in `README.md` and
  `examples/render-claude_desktop_config.json`.

## 0.3.3

### Fixed
- Strip path parameters from **non-GET** request bodies (was GET-only). Substituted
  `{path}` placeholders were left in `parameters` for POST/PUT/PATCH/DELETE and leaked
  into the JSON body, so strict APIs returned 400 — e.g. Home Assistant
  `POST /api/services/{domain}/{service}` rejected the body carrying `domain`/`service`.
  Now stripped for all methods. Regression test added.

### Added
- Home Assistant example (`examples/homeassistant.openapi.json` +
  `examples/homeassistant-claude_desktop_config.json`): generic REST slice
  (get_config, list_states, get_state, list_services, call_service, get_history) with
  named `call_service` body args. Auth via `EXTRA_HEADERS="Authorization: Bearer ${HA_TOKEN}"`
  and `SERVER_URL_OVERRIDE`. Requires this release's fix for `call_service`.

## 0.3.2

### Fixed
- **FastMCP / simple mode** (`OPENAPI_SIMPLE_MODE=true`) advertised the prompts and
  resources capabilities but served **empty lists**. It now serves native MCP prompts
  (`summarize_spec`, `whimsical_blog`) and the `spec_file` resource — at parity with the
  low-level server. (Tools, prompts, resources all work in both modes now.)
- FastMCP spec-serialization paths now use `default=str`, so specs with YAML datetime
  example values (e.g. the apis.guru directory spec) no longer crash `resources/read`
  with "Object of type datetime is not JSON serializable".

### Tests
- TDD: added simple-mode prompts/resources **serve** tests (not just advertise) and a
  datetime-serialization regression test. Verified with a full permutation sweep —
  both modes × {tools, prompts, resources} × {list, invoke} — all green.

## 0.3.1

### Docs
- **Client matrix re-verified against the published 0.3.0 release** (no flags, default-on
  advertising), driving every available real client binary. Filled the previously
  "unknown" cells with evidence:
  - **opencode** surfaces tools + prompts + resources — the only client that does all three.
  - **Codex** surfaces tools + resources (`read_mcp_resource`); no prompt mechanism.
  - **Kilocode** tools + resources; **Qwen** tools + prompts (slash); **Gemini** tools
    (prompts/resources interactive-only); **Vibe** tools-only.
  - **Letta** marked unknown — not testable headless (needs a running server + model).
- No code changes; README is the PyPI long-description, so the corrected matrix ships to devs.

## 0.3.0

### Changed
- **Prompts and resources are now advertised by default.** `ENABLE_PROMPTS` and
  `ENABLE_RESOURCES` default to `true`. Previously they defaulted to `false`, which —
  per the MCP spec (a client won't call `prompts/list`/`resources/list` unless the
  capability is advertised in `initialize`) — made prompts and resources **invisible to
  every client at once**, despite being implemented and served correctly. Opt out with
  `ENABLE_PROMPTS=false` / `ENABLE_RESOURCES=false`.

### Added
- Regression test asserting the **default** handshake (no env flags) advertises prompts
  and resources, not just tools.

### Docs
- Corrected the client matrix in `README.md` and `docs/verification-case-study.md`.
  Re-verified the real client binaries with advertising enabled: **Qwen** surfaces
  prompts (slash commands), **Kilocode** surfaces resources (`access_mcp_resource`),
  Gemini exposes prompts interactively only, Vibe is tools-only. **All pre-fix
  prompt/resource findings are voided** (they were measured while advertising defaulted
  off); Codex, opencode, and Letta are marked **unknown** pending re-test. Tool-call
  results were unaffected and stand.

## 0.2.1

- See the [verification case study](docs/verification-case-study.md) for the 0.2.0/0.2.1
  multi-client, multi-API verification sweep and the defects fixed.
