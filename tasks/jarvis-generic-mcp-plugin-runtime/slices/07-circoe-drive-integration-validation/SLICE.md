# Slice 07 — Circuit Toolbox and Drive integration validation

## Goal
Validate the exact generic flow live against https://circoetoolbox-server-production.up.railway.app/mcp, discovering actual auth/transport at test time. Prove onboarding, enablement, catalog ingestion, list_tools(intent) recommendation with full schema, safe read/diagnostic call, Brain and delegated-subagent access, disable/re-enable and disconnect/reconnect. Audit the special jarvis-drive and migrate only with parity and rollback.

## Dependencies
05-agent-subagent-capability-propagation, 06-control-center-plugin-manager-ui

## Quality gates
qa-verification + code-review + runtime-validation + agent-trace-analysis. Coding loads /caveman and /coding-guideline; frontend additionally loads /impeccable. Regressions caused by this slice are blocking.

## Acceptance criteria
The requested runtime/UI flow is proven end-to-end without provider-specific hacks or credential leakage, and canonical MCP behavior stays green.

## Slice 00 contract

Binding design: `docs/06-resolved-architecture.md` (ARCH) §5.3, §11, §15 Q2/Q3. Validation Slice: product code changes only to fix generic defects found live (no provider-specific code, no Circuit Toolbox literal outside tests/docs).

### Scope (files)
- Live validation against `https://circoetoolbox-server-production.up.railway.app/mcp` through the real UI and the real brains (no special casing).
- Record in `docs/mcp/plugins.md` (section "Conformance: Circuit Toolbox", dated): advertised transport, PRM, AS metadata, DCR outcome (Q2), scopes, token lifetime, refresh support, tool count, rejected tools if any.
- Drive: add to `docs/mcp/plugins.md` the classification of ARCH §11 (three paths: `jarvis-drive` stdio operator, Core voice `DriveService`, `drive-auth`), future migration criteria and rollback rule.
- Generic fixes, if any, each with a regression test on the fake server first.

### Out of scope
Migrating or deleting `jarvis-drive`; calling write/destructive Circuit Toolbox tools (read/diagnostic only, Q3); copying any token into notes; provider-specific code.

### Acceptance criteria
- [ ] Add URL -> discovery -> OAuth consent (HV-07-01) -> connected + enabled; tools appear in `/api/mcp/tools` under the plugin id.
- [ ] `list_tools(intent)` from a normal Claude brain returns a relevant Circuit Toolbox tool in `recommended` with a complete input schema; `call_tool` on a read-only/diagnostic tool succeeds.
- [ ] A delegated Claude subagent performs the same discovery + call without credentials; a Codex turn does too (if Codex is configured on the machine).
- [ ] Disable removes the tools from `list_tools` and `call_tool` answers `mcp_plugin_disabled`; re-enable restores them without re-consent.
- [ ] Disconnect prevents execution (`mcp_plugin_disconnected`) and removes the sealed credential row; reconnect requires consent again.
- [ ] Token expiry behavior observed or simulated (Core clock/`expires_at` edit on a copy): `auth_status=expired`, "Reconnecter" shown, no hang in `call_tool`.
- [ ] `jarvis-drive`: still listed and introspected in the catalog (`registration=operator`, state `known`), never in `list_tools`; its tools still usable by the brain as before (one read call trace).

### Required tests
- Any generic fix: a test in the Slice 03/04 files reproducing the live defect on `tests/fakes/fake_remote_mcp.py`.
- `tests/integration/test_live_circoe_toolbox.py`, marked `live` and skipped by default (needs `JARVIS_LIVE_CIRCOE=1` and an already-authorized plugin): connect, list, one read-only call; asserts no secret in outputs.

### Required evidence for QA
Redacted trace excerpts for brain, subagent (and Codex) runs; screenshots of plugin card states; journal excerpt with codes only; statement of which tool was called and why it is read-only; secret-sentinel/token grep over traces, journal and QA notes returning nothing; agent-trace-analysis report.

### Pre-existing red tests (not yours)
see READINESS.md §Baseline
