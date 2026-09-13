# Task15 — prompt registry, inspector and editor evidence

Accepted 2026-09-13.

## Result

Task15 adds 24 stable prompt-layer descriptors and 14 deterministic programs
covering the current OpenAI Realtime, Gemini, Front Brain/Luna, GPT-Live and
Claude/Codex paths. Programs keep instructions, tools, structured messages,
schemas, CLI system arguments and stdin turns in their actual channels and
composition order. The resolver returns source provenance, effective/default
revisions, conflicts, static fingerprints and render fingerprints.

Safe overrides are versioned, bounded and atomic. Only the shared persona and
dedicated user-addition layers are editable. Dynamic data, schemas, tools,
response delimiters and runtime invariants remain read-only. Stale-base and
concurrent edits fail without a write; reset removes one override; inactive,
unknown and unrelated settings survive.

Production send sites consume registry resolutions. Realtime startup records an
acknowledged instruction revision after the matching session update; response,
Live, Gemini, Luna and CLI writes record sent fingerprints. Claude resume carries
an explicit resumed marker because a retained provider session may still use its
older system snapshot. Diagnostics contain IDs and fingerprints only.

`GET /api/prompts` returns the programs relevant to the saved architecture and
backend. `POST /api/prompts/{id}` performs one edit/reset through the atomic
settings writer. The Settings Prompts tab renders ordered layers, provenance,
read-only/editable state and channel-specific effective previews with empty
runtime data. It explicitly states that provider-internal prompts are
unavailable and that saving is not runtime application.

## Verification

- Task15A registry/override review: **51 passed**.
- Task15A broadened compatibility gate: **333 passed**.
- Task15B/C prompt, adapter, HTTP and browser gates: **380 passed**, then
  **59 passed** for the final Settings/API review.
- First release run found five regressions: two Luna dynamic payloads were
  rejected by a registry character bound tighter than the adapter's existing
  byte bound, and three legacy endpoint doubles rejected the new evidence
  keyword. Both causes were repaired; their direct gate passed **29 tests**.
- Final release: **3054 passed, 5 skipped in 348.03 s**; all release checks
  passed. `git diff --check` clean.

The three provider integration tests remain opt-in and were skipped. No provider,
billable session or audio hardware was used; this evidence proves request
composition and state reporting, not model obedience or acoustic quality.
