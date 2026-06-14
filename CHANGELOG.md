# Changelog

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
