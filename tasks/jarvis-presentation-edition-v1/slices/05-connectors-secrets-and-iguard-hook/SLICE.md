# Slice 05 — Connectors, secrets and IGuard hook

## Goal
Define and implement the allowed connector surface for Presentation Edition: CIRCOE Mail/Calendar, Google Drive, document search and a production-ready IGuard integration seam using the existing MCP/plugin/tool gateway architecture.

## Context
Jarvis already has Google Drive support and a generic remote MCP runtime with registry, credential vault, OAuth/static auth, Streamable HTTP, SSRF policy and dynamic tool discovery. IGuard's actual transport/endpoint/auth contract is not supplied in this handoff and must not be guessed.

## Canonical Concepts
- generic MCP plugins: `docs/mcp/*`, `jarvis/core/mcp_plugin_service.py`, `jarvis/adapters/remote_mcp.py`;
- tool gateway/discovery: `jarvis-tools` runtime/domain docs;
- Google Drive service/MCP;
- product capability policy from Slice 01;
- credential vault / sealed secrets.

## Scope
### In Scope
- product allow-list/availability for CIRCOE Mail, Calendar, Google Drive and IGuard;
- onboarding/status contracts for connector auth/availability;
- credential storage through existing vault/credential mechanisms, never plain config;
- validate Google Drive as a document source/explicit export connector, not canonical state;
- prepare IGuard registration/configuration path and complete it when real transport/auth details are supplied;
- ensure connector tool outputs are treated as untrusted data;
- expose stable product-facing statuses/errors without MCP implementation jargon.

### Out of Scope
- no sync of SQLite/Jarvis profile to Drive;
- no invention of IGuard endpoint/auth/tool names;
- no broad plugin marketplace UI in V1.

## Dependencies
Hard `depends_on`: `01-product-edition-and-board-lock`.
Soft `requires`: Slice 04 capability manifest for final model tool exposure.

## Implementation Steps
1. Audit current Drive, tools gateway, MCP plugin, credential-vault and CIRCOE connector paths.
2. Define Presentation product connector manifest: required/optional, auth state, tool categories, user-facing label, health/readiness semantics.
3. Ensure secrets/tokens are stored only through the credential/vault path; verify logs/status payloads do not leak them.
4. Validate Google Drive login/read/search/import/export behavior under the product profile.
5. Wire CIRCOE Mail/Calendar as allowed business capabilities with their existing action safety semantics.
6. Create an IGuard connector contract template that records: transport, endpoint, auth strategy, expected server identity, tool inventory/categories, read/write risk, health probe, onboarding and failure behavior.
7. When IGuard details are supplied, prefer the existing generic Streamable HTTP MCP runtime if compatible. If IGuard is stdio-only, explicitly choose between adding a bounded stdio adapter or deploying a local/remote HTTP bridge; do not silently overload the current remote connector.
8. Add connector-health summaries for onboarding/health UI.
9. Add agent/tool discovery tests and hostile connector-output tests proving data cannot become instructions.

## Files Likely Touched
- MCP plugin/product policy/configuration modules;
- `jarvis/core/mcp_plugin_service.py` / plugin registry only if needed;
- tool gateway/catalog/relevance modules;
- Drive runtime/service tests;
- connector settings/status UI data contracts;
- new IGuard integration doc/config when real details exist.

## Architecture Constraints
- keep one generic MCP runtime; avoid IGuard-specific transport code unless its protocol truly requires it;
- no secret values in SQLite plugin metadata, logs or prompts beyond sealed credential references;
- connector content is untrusted data;
- IGuard uncertainty must not block unrelated V1 work.

## Automated Validation
- connector manifest/status tests;
- vault/secret redaction tests;
- Drive integration tests with fakes plus available real smoke where credentials permit;
- tools gateway discovery/call policy tests;
- IGuard contract tests once endpoint/auth/tool schema is known;
- agent trace showing discovery/use of allowed connectors and no prompt-injection instruction following from connector text.

## Acceptance Criteria
- Presentation Edition exposes only intended connector families;
- Drive and CIRCOE capabilities work without exposing secrets or canonical-state sync;
- IGuard has an implementation-ready, evidence-based contract and is connected when its real details are available;
- connector failures appear as actionable product states.

## Documentation Updates
Add/extend a Presentation Edition connector contract and IGuard integration page. Link to existing generic MCP contract instead of duplicating it.

## Handoff Notes
Coding Slice: `/caveman`, `/coding-guideline`. Because tool discovery/agent behavior changes, required QA includes `agent-trace-analysis`. IGuard-specific completion may remain an explicit external-input blocker while the rest of this Slice completes.

## Slice 00 amendments (2026-10-26)
- E1 / X2: **no CIRCOE Mail connector exists** (no Gmail, IMAP, SMTP or Graph). The only calendar is `jarvis/adapters/google_calendar.py` (Google OAuth, full `calendar` scope). Calendar = this adapter on the CIRCOE account (the Human must confirm that this account is Google Workspace). Mail is a new external input: provider, protocol and auth. As with IGuard, record a contract template and do not invent; the rest of the Slice is not blocked. Prefer the minimal scopes (read-only) for Drive/Calendar/Mail in the product profile.
- E3: API keys are stored in plain text in `runtime/control-center-settings.json` and `.env` (`jarvis/runtime/credentials.py:30-90,330`). Google OAuth tokens are JSON files named by `.env`. In the product edition, move them to the existing DPAPI vault (`jarvis/adapters/dpapi_sealer.py`) or an equivalent, with redaction tests.
- E10: the `side_effect` of remote MCP tools (`jarvis/domain/mcp_plugins.py:807-812`) is checked at no call. Product policy on write/destructive tools.
- Overlap: `jarvis-connections-services-mcp-settings-ui` (to-do) owns the connection settings UI. This Slice delivers the data/status contracts and refreshes against that task before dispatch.
