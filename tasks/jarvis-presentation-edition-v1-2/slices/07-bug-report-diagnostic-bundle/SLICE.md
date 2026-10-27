# Slice 07 — Report a problem and diagnostic bundle

## Goal
Give a user one practical button that captures enough local Jarvis context for the developer/support team to diagnose a prototype failure without asking the user to manually hunt logs and AppData files.

## Context
The user explicitly wants the error, an AI diagnostic summary and the Jarvis AppData context zipped and sent for analysis. Jarvis may hold sensitive credentials and large runtime/media files, so the implementation must preserve diagnostic value without transmitting secrets blindly.

## Canonical Concepts
- parent V1 installed data-root/AppData contract;
- RuntimeJournal/error logs/health diagnostics;
- credential vault/secrets storage;
- Board memory/SQLite/artifacts paths;
- CIRCOE Mail/approved support connector if used for sending.

## Scope
### In Scope
- add a user-facing “Signaler un problème / Report a problem” action;
- collect a diagnostic snapshot from Jarvis-owned AppData/config roots only;
- include build/version/platform, recent health state, error/trace context, relevant state DBs, Board memory/project docs and sanitized settings as available;
- have an AI diagnostic step generate `report.md` from the collected evidence: symptom, recent error, likely area, reproduction/context, relevant ids/timestamps, uncertainty; no invented root cause;
- create a ZIP plus a machine-readable manifest of included/excluded files and sizes;
- hard-exclude credential vault data, raw tokens/API keys/OAuth secrets and private keys; redact secrets in text/config/logs;
- omit or separately flag huge private runtimes/caches and optionally very large media when they would make the bundle impractical; record omissions in manifest;
- require explicit user confirmation before sending;
- automatic send uses configured support destination/channel only; if unavailable/failing, preserve the ZIP and offer manual save/share;
- store generated support bundles in a bounded diagnostics/support folder with explicit retention/cleanup policy.

### Out of Scope
- silent automatic telemetry/upload;
- hard-coding a guessed developer email;
- uploading secrets because the user asked for “all AppData”;
- full ticketing platform/CRM integration.

## Dependencies
- `01-presentation-product-brain-scope`;
- use the resolved installed data-root contract from the parent V1 work after Slice 00 reconciliation.

## Implementation Steps
1. Define a `DiagnosticBundleService`/equivalent with explicit logical include/exclude categories, size budgets and redaction rules.
2. Snapshot consistent SQLite/state files safely (use database backup/read strategy rather than copying hot WAL state blindly where required).
3. Collect recent runtime logs/errors and build/health/platform manifest.
4. Build a sanitized evidence set for the AI diagnostic report; the model must distinguish observed facts from hypotheses.
5. Write `report.md`, `manifest.json` and snapshot files into a staging directory, then ZIP atomically.
6. Add UI preview: approximate size, categories included, categories excluded/redacted, active Board/project context, consent checkbox/action.
7. Implement configured send path (for example approved mail/support connector) and manual-save fallback. Sending failure must not delete the bundle.
8. Add retention/cleanup and diagnostics for bundle creation/send failures.

## Files Likely Touched
Diagnostics/log/health modules, data-root/path service, credential redaction helpers, Control Center Settings/Help UI, connector integration, tests/docs.

## Architecture Constraints
- collection cannot escape Jarvis-owned roots;
- credentials/secrets never enter the ZIP or AI prompt;
- the AI report is secondary evidence, never the only raw diagnostic material;
- no upload without explicit user action.

## Automated Validation
- ZIP contents test with seeded Board/DB/log context;
- secret canary tests: known API key/OAuth token/private key must not appear anywhere in ZIP/report;
- active SQLite snapshot consistency/recovery tests;
- path traversal/symlink/junction refusal;
- large-file omission/manifest tests;
- send success/failure tests and manual fallback;
- model report grounding tests using fixture diagnostics: no fabricated error/root-cause assertion.

## Acceptance Criteria
A user can press one button after a failure and produce a transferable diagnostic ZIP that contains useful project/runtime context, a readable AI report and no credentials/secrets; configured send failure never loses the bundle.

## Documentation Updates
Document support bundle contents, exclusions, privacy/consent, retention and how support opens/analyzes it.

## Handoff Notes
Prototype simplicity is desired, but secret exclusion is non-negotiable. If “full AppData” would exceed practical attachment limits, retain a local full safe snapshot and create a smaller send bundle with explicit manifest differences.