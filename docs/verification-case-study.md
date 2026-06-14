# mcp-openapi-proxy in practice — a multi-client, multi-API verification sweep

**Date:** 2026-06-12 · **Release:** 0.2.0

## What mcp-openapi-proxy is

`mcp-openapi-proxy` is a Model Context Protocol (MCP) server that turns any
**OpenAPI specification** into MCP tools an agent can call — through configuration alone,
with no per-API server code. Point `OPENAPI_SPEC_URL` at a spec, optionally scope it with
`TOOL_WHITELIST`, set the auth header style, and an MCP-enabled agent can drive the API.

It runs in two modes:

| Mode | Behavior |
| --- | --- |
| **Low-Level** (default) | Registers one MCP tool per OpenAPI operation (e.g. `GET /chat/completions` → `get_chat_completions`). |
| **FastMCP** (`OPENAPI_SIMPLE_MODE=true`) | Exposes two static tools, `list_functions` / `call_function`, over the same spec. |

The value proposition: one governable component covering any product that publishes a
spec, instead of a fleet of hand-maintained connectors.

## Methodology

Eleven public APIs were exposed through the proxy and exercised by six agent CLIs plus the
Letta platform, over stdio MCP (and, for Letta Cloud, remote HTTP MCP). Every result below
is from a live call, not a dry run. Credential-free APIs (Glama, APIs.guru) needed no
secrets; the rest used standard API keys supplied via environment variables.

## Results — APIs verified through the proxy

| API | Tools | Auth / extra env | Proof call (live) |
| --- | --- | --- | --- |
| Glama | 6 | none | `get_v1_attributes` → attribute taxonomy |
| APIs.guru | 7 | none | `get_metrics_json` → 3,992 specs / 2,529 APIs |
| WolframAlpha | 2 | `API_KEY` | `get_v1_llm_api` → `2+2 = 4` |
| VirusTotal | 4 | `API_KEY` + `API_AUTH_TYPE=api-key` + `API_AUTH_HEADER=x-apikey` | IP report → clean verdict |
| Asana | 73 (whitelisted) | `SERVER_URL_OVERRIDE` + `API_KEY` | created a project + 11 tasks; read back |
| Render | 52 | `API_KEY` | `get_services` → live service list |
| Notion | 4–5 (whitelisted) | `SERVER_URL_OVERRIDE` + `EXTRA_HEADERS` (`Notion-Version`) + `API_KEY` | created a page; read its title back |
| ElevenLabs | 19 | `SERVER_URL_OVERRIDE` + `API_AUTH_TYPE=api-key` + `API_AUTH_HEADER=xi-api-key` | TTS → MP3 generated |
| Fly.io | 34–35 | `API_KEY` | `get_apps` + per-machine health |
| Slack | 7 (whitelisted) | `API_KEY` | `auth.test` + `chat.postMessage` |
| NetBox | 9 (whitelisted) | `API_KEY` + `API_AUTH_TYPE=Token` | IPAM address create + read (self-hosted) |

Large specs (Asana, NetBox, Notion, Slack) require `TOOL_WHITELIST` to stay within a
sane tool count.

## Results — agent-client compatibility

| Client | Model (live test) | MCP attach mechanism | Tool calls | Prompts/resources to model |
| --- | --- | --- | --- | --- |
| Codex | gpt-5-codex | `codex exec -c mcp_servers.*` | ✅ native | unknown ‡ |
| Gemini | Google OAuth tier | project `.gemini/settings.json` | ✅ native | prompts: interactive slash only · resources: ❌ † |
| Qwen | gateway model group | project `.qwen/settings.json` | ✅ native | prompts: ✅ (slash) · resources: ❌ † |
| Kilocode | free auto model | global `mcp_settings.json` | ✅ native | prompts: ❌ · resources: ✅ (`access_mcp_resource`) † |
| opencode | gateway model group | `opencode.json` `mcp` | ✅ native | unknown ‡ |
| Vibe | mistral-medium-3.5 | `~/.vibe/config.toml` `[[mcp_servers]]` | ✅ discovery + reads | prompts: ❌ · resources: ❌ (tools-only) † |
| agy | — | — | ❌ headless can't enable MCP | n/a |
| Letta (self-hosted) | gateway model group | stdio via `PUT /v1/tools/mcp/servers` | ✅ native | unknown ‡ |
| Letta Cloud | Letta default | remote streamable-HTTP MCP URL | ✅ (stdio rejected) | unknown ‡ |

*† re-verified 2026-06-14 with advertising on (real binary). ‡ not yet re-tested under advertising-on — prior 0.2.0 prompt/resource results are **voided** (they were measured while the server defaulted to advertising neither). Tool-call results were unaffected and stand.*

**Systemic finding:** every CLI tested could call MCP *tools* natively. Surfacing of
MCP *prompts/resources* to the model is uneven across clients — but read the correction
below before concluding it's purely a client gap.

> **† Correction (2026-06-14).** This original sweep ran against a build where the
> low-level server advertised prompts/resources **only when `ENABLE_PROMPTS`/`ENABLE_RESOURCES`
> were explicitly set — they defaulted OFF.** Per the MCP spec, a client will not call
> `prompts/list`/`resources/list` unless the capability is advertised in `initialize`, so
> a server that doesn't advertise makes prompts/resources invisible to **every** client at
> once. Part of the original "client-ecosystem gap" was therefore the proxy's own default,
> not the clients. That default is now **on** (advertising by default; opt out with
> `ENABLE_PROMPTS=false`/`ENABLE_RESOURCES=false`). Re-running the **real** client binaries
> with advertising enabled: **tools** universal; **prompts→model** on Qwen (slash commands)
> and Gemini (interactive only); **resources→model** on Kilocode (`access_mcp_resource`).
> Vibe remains tools-only (no prompt/resource client support — confirmed in source); Codex,
> opencode, and Letta were not re-run in this pass. So the residual gap is real and
> client-side, but **not universal** — and the proxy serves both correctly once it advertises.

## Prompts & resources

The low-level server exposes prompts (`summarize_spec`, `whimsical_blog`) and a `spec_file`
resource, all verified via `prompts/get` and `resources/read`. Release 0.2.0 adds
`ADDITIONAL_RESOURCES`, which serves arbitrary local documents (e.g. a NetBox naming policy
or an Asana project-layout convention) as MCP resources an agent can consult while working.

## Defects found and fixed

The sweep surfaced real defects; each was reproduced, fixed with tests, and released in
0.2.0.

| Issue | Defect | Resolution |
| --- | --- | --- |
| #23 | Strict clients saw **zero tools** — empty capabilities + a crash in resource discovery | PR #22 + stdio-handshake test harness |
| follow-up | Prompts/resources advertised **only when `ENABLE_*` set (default OFF)** → invisible to every client; the sweep mis-attributed this to a client gap | default `ENABLE_PROMPTS`/`ENABLE_RESOURCES` to **on** + regression test asserting default advertisement |
| #14 | `IGNORE_SSL_TOOLS` ignored by the low-level dispatcher | PR #21 (groundwork by @robbycochran, #15) |
| #28 | Crash-loop when a slow spec fetch outran a client's connect timeout | PR #40 — handshake-first lazy load, clean stream exit, live-first cache |
| #24 | `API_AUTH_TYPE` custom schemes (NetBox `Token`) sent **no** auth header | PR #25 — custom scheme prefix |
| #27 | `TOOL_WHITELIST` never matched dot-paths (`/users.list`) → Slack registered 0 tools | PR #32 |
| #11 | `TOOL_NAME_MAX_LENGTH` ignored; truncation collisions silently dropped tools | PR #44 |
| #16 | Array params emitted without `items` → rejected by the OpenAI API | PR #43 |
| #17 | `EXTRA_HEADERS` accepted only real newlines | PR #42 — JSON array + literal `\n` |
| #26 | Render example spec URL dead (302 → 404) | PR #31 |
| #29 | ElevenLabs example missing `servers` + wrong auth header | PR #30 |
| #13 | No `Dockerfile`/`glama.json` for the Glama listing | PR #41 |
| #38 | GetZep hosted endpoint 401s | PR #39 — documented self-hosted Zep CE |
| #33 | Resources couldn't ship use-case documents | PR #34 — `ADDITIONAL_RESOURCES` |
| #35 | README lacked a verification summary | PR #36 — collapsible examples + matrices |

## Key lessons

- **Spec-as-config scales.** Eleven heterogeneous APIs were driven with zero per-API code;
  the recurring work is auth-scheme and whitelist tuning, not integration code.
- **Auth variety is the long tail.** Bearer, `api-key` header, custom `Token` scheme, and
  vendor-specific header names (`x-apikey`, `xi-api-key`) all appeared in eleven APIs.
- **Whitelisting is mandatory for large specs**, and must understand both `/` and `.`
  path delimiters.
- **Robustness during the MCP handshake matters** more than raw throughput: a slow spec
  download must never block `initialize`, or short-timeout clients crash-loop.
- **The MCP client ecosystem is uneven** on prompts/resources, even where tool-calling is
  solid — worth knowing when designing agent UX.

## Reproducing

Install the published package and point it at any spec:

```bash
uvx mcp-openapi-proxy          # OPENAPI_SPEC_URL=... in the environment
```

Per-API example configurations are in [`examples/`](../examples); the credential-free Glama
and APIs.guru examples require no setup.
