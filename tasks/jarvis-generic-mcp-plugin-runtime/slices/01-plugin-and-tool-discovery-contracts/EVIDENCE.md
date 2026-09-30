# Slice 01 — Evidence

Docs-only Slice. Commits: `f306819` (contract), `c4d612e` (ARCH §16 E1–E9
rework), and the QA rework commit that adds this file. Diff scope: `docs/mcp/plugins.md`,
`docs/mcp/tool-contract.md`, this task folder (`LOG.md`, ARCH §16, this file);
no `.py`/`.js`/test file.

`tests/unit/test_mcp_catalog.py`: collection error
`ImportError: cannot import name 'READY_SETTLE_S' from 'jarvis.runtime.claude_local'`
(pre-existing D0 breakage, READINESS; no code touched by this Slice).

## ARCH §14 contradictions → doc section

| Item | Carried by |
| --- | --- |
| C1 Core and the Control Center are two processes; Core owns registry/vault/connections/OAuth/execution, the CC relays | plugins.md §1 (topology table, diagram) |
| C2 ranking + budget run in the gateway process, `call_tool` a thin proxy | plugins.md §1 (rules), §6.2 |
| C3 Core layering; one new `CORE_ADAPTER_IMPORT_EXCEPTIONS` entry (`tests/unit/test_v2_architecture.py:35`, E1) | plugins.md §1 (rules) |
| C4 `/v1/tools/call` exists; plugin routes under `/v1/mcp/*` | plugins.md §1 (rules), §8.1 |
| C5 `test_mcp_catalog.py:188-195` and §5.3 amended deliberately; `/api/mcp` 405/404 wording | tool-contract.md §5.3 (plugin amendment), §8 (plugin amendment, E8); plugins.md §9 |
| C6 OAuth callback at `/api/mcp/oauth/callback`, outside the guarded prefix | tool-contract.md §8 (route table); plugins.md §3.3 step 3, §9 |
| C7 Board wiring lost in Core (pre-existing) | not a contract item: baseline / D0, READINESS |
| C8 operator servers (`jarvis-drive`) excluded from `list_tools` | plugins.md §6.2 step 1, §11 |
| C9 SDK gaps: RFC 9207 `iss`, expiry restore, non-interactive mode | plugins.md §3.3, §3.4 |
| C10 Codex amendment C1 false for `jarvis-tools` only | tool-contract.md §4.3 (Codex exception); plugins.md §10 |
| C11 barehands 16 tools, not 5 | tool-contract.md §1 table, §3 table, §6 (`jarvis-barehands` paragraph) |
| C12 `Registration` gains `managed`; `list_view` must not call `server_meta()` for plugins | tool-contract.md §1 (plugin note), §2 (external descriptor); plugins.md §5.2 |

## ARCH §16 errata → doc section

| Item | Carried by |
| --- | --- |
| E1 exceptions list location | plugins.md §1 |
| E2 `_configure_agent` wiring | tool-contract.md §1; plugins.md §10 (wiring bullet) |
| E3 over-16 KiB entry never recommended, `detail: "too_large"` | plugins.md §6.3 |
| E4 `mcp_endpoint_invalid` (syntax) vs `mcp_endpoint_forbidden` (address) | plugins.md §4.1, §4.2 |
| E5 / E11 plugin `advertised` = enabled ∧ connected | tool-contract.md §4.3; plugins.md §5.2 |
| E6 string `catalog_revision` model-facing and cursor `r`; integer on `/v1/mcp/*` | plugins.md §6.3, §8.1 |
| E7 suffix inside the 4 096 B description bound | plugins.md §5.1 |
| E8 unknown `/api/mcp/plugins*` paths | tool-contract.md §8; plugins.md §9 |
| E9 `codex_local.py:253-273` | plugins.md §10 |
| E10 best-effort RFC 7009 revocation on disconnect | plugins.md §2.2 |

## Slice 00 acceptance → evidence

| Acceptance bullet | Evidence |
| --- | --- |
| §5.3 no longer forbids model-facing discovery; exactly two catalog tools, both on `jarvis-tools` | tool-contract.md §5.3 first bullet; §10.2 step 3 "no meta-tool except `jarvis-tools`"; plugins.md §6.1 |
| Every C1–C12 reflected | table above |
| Numeric bounds identical to ARCH: 24 576 B response, ≤ 5 recommended, 16 KiB recommended part, 16 KiB schema, 4 096 B description, 200 tools/plugin, 64 KiB args, 32 KiB result, 60/120 s timeouts, 4 MiB response cap | plugins.md §6.3 (24 576 B, ≤ 5, 16 KiB), §5.1 (16 KiB schema, 4 096 B, 200 tools, 512 KiB), §7 (64 KiB, 32 KiB, 60/120 s), §4.2 (4 MiB); also 2 500 B / 1 200 B budgets §6.1 |
| Error-code table identical to ARCH §9 | plugins.md §8.2 (26 codes, same statuses, redaction rule) |
| Restricted profiles and `job_result` keep no gateway | plugins.md §10 table (rows `job_result`, `speculative_analysis`, `presentation_preparation`) |
| No secret, token, real Drive id or credential path in any doc example | plugins.md examples use `example-mail` and env-var names only; tool-contract.md amendments carry no value; grep reviewed |

## Anchors verified against the code (QA rework)

tool-contract.md: `claude_local.py:287-289` (qualified names), `display_mcp.py:2237-2246`
(strict `additionalProperties: false`), `test_display_mcp.py:483`, `settings_mcp.py:937-946`
(`_describe_line`), `display_mcp.py:158,165` (`MAX_INSPECT_BYTES`, `MAX_GET_BYTES`),
`display_mcp.py:2036` (`OBJECT_ROW_LEGEND`), `ARCHITECTURE.md:2510` (QA live run note),
`claude_local.py:398-400` (`--resume` keeps the prompt), `drive_mcp.py:103`
(`drive_update` idempotency key), `test_mcp_catalog.py:188-195`, `mcp_catalog.py:137,160`;
§1 table anchors refreshed in `f306819`. plugins.md: `codex_local.py:253-273`.
