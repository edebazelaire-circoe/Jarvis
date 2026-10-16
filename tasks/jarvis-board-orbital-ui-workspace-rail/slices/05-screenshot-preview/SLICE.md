# Slice 05 - Non-blocking screenshot preview and quick actions

## Goal
After successful screenshots, show a temporary real preview with useful actions without blocking the Board.

## Canonical context
Read `../../README.md` and `../../docs/00-overview.md` through `05-documentation-levels.md`. Re-read the repository's canonical contracts at current HEAD; this handoff never overrides a newer canonical contract silently.

## Dependencies
- `04-capture-wheel-migration`

## Scope / implementation steps
Create a transient preview component driven by the successful capture/artifact identity. Load only the supported safe payload/thumbnail route. Preview auto-dismisses after a short interval unless being interacted with.

Quick actions required by product intent: Open, Annotate, Send to Jarvis, Delete. Each button must call a real supported path. If Annotate or Send-to-Jarvis lacks a canonical path at HEAD, implement the smallest real supported flow in this Slice or explicitly revise the Slice with PM approval; never ship a dead affordance.

Preview errors are presentation errors only and must not mutate the completed screenshot artifact/capture state.

## Out of scope
- Rewriting Core capture/artifact ownership merely to simplify frontend code.
- Starting/stopping/restarting the user's live Jarvis instance without explicit permission.
- Adding speculative wheel tools or fake preview/status data.
- Broad unrelated visual refactors.

## Files likely touched
These are planning pointers only; verify at HEAD before editing:
- `capture/artifact UI relay modules discovered at HEAD`
- `new screenshot preview module`
- `attachment/chat integration only if required for Send to Jarvis`
- `artifact UI tests`

## Architecture constraints
- No optimistic duplicate state when a canonical Core/runtime owner exists.
- Preserve error/refusal semantics and make unknown/unconfirmed states explicit.
- Update the explicit Control Center layer registry when introducing/moving overlays.
- Author-provided text is rendered safely; previews use bounded/safe routes.
- Code slices run `/caveman` and `/coding-guideline`; frontend code additionally runs `/impeccable` and uses a Claude agent when supported by the host.

## Automated validation
- `qa-verification` is mandatory.
- `code-review` is mandatory.
- `runtime-validation` is mandatory.
- Run focused unit/integration tests for the exact behavior changed, plus neighboring regression tests named by current repository contracts.
- Runtime/UI validation must use an isolated Jarvis instance/worktree/data root unless the user explicitly authorizes the live instance.

## Acceptance criteria
- Successful screenshot produces a real preview; failed screenshot does not.
- Preview is non-modal and never blocks Board interaction.
- Auto-dismiss/focus behavior is predictable.
- Every visible quick action works through a canonical API.
- Preview failure never changes capture truth.

## Documentation updates
Update the canonical concept documentation and `../../docs/05-documentation-levels.md` when this Slice raises a concept's documentation level. Record exact test commands, SHA and QA findings in the implementation log.

## Handoff notes
Task Type is intentionally not invented in this handoff. Slice 00 resolves it from the current Workspace vocabulary before delegation. Human validation is separate in `human-validation.json` and happens only after automated validation is maximized.

## Slice 00 contract

Binding reference: `../../docs/06-resolved-architecture.md` §6 (D7). QA tier: **ui** + adversarial on Delete, Send and the annotation route; `agent-trace-analysis` on a real Send turn (attachment rule change).

**S05.A files.** New `jarvis/runtime/control_center_screenshot_preview.js` (preview `#screenshotPreview` rank 38, lightbox on `.overlay` 60) + script constant/injection; `control_center_capture_rail.js` (publishes `{capture, artifact}` of a successful screenshot); `control_center_chat.js` + `control_center_chat_model.js` (`JarvisChat.attachExisting`, ready chip without upload); Core `jarvis/core/upload_service.py:499` (`attachment_refusal` admits `screenshot`, `complete`, same Session); `docs/chat.md` (step 5, *Attachments*), `docs/capture.md` (§ Interface, preview), `docs/control-center-shell.md`.
**S05.B files (gated).** Core `POST /v1/artifacts/{id}/annotations` (`jarvis/protocol/capture_routes.py`, `jarvis/core/capture_api.py`), relay `POST /api/artifacts/{id}/annotations` (`capture_relay.py`), editor in `control_center_screenshot_preview.js`; `docs/artifacts.md` (relation use), `docs/capture.md`.

**Acceptance tests.** `tests/unit/test_screenshot_preview_js.py::test_shown_only_after_successful_screenshot`, `::test_auto_dismiss_paused_on_hover_focus_and_never_deletes`, `::test_payload_failure_shows_placeholder_keeps_actions`; `tests/unit/test_screenshot_preview_browser.py::test_open_lightbox_and_tab`, `::test_delete_requires_confirm_and_removes_artifact`, `::test_send_attaches_existing_artifact_to_chat_composer`, `::test_preview_never_blocks_board_pointer`; `tests/unit/test_chat_attachments_brain_context.py::test_screenshot_of_open_session_is_admitted`, `::test_screenshot_of_other_session_is_refused`, `::test_non_complete_screenshot_refused`; S05.B: `tests/unit/test_screenshot_annotation.py::test_creates_new_derived_screenshot_original_untouched`, `::test_rejects_non_png_oversize_and_dimension_mismatch`, `::test_loopback_guard`.

**Not in this slice.** No auto-send (text still required); no editing of the original artifact; Annotate button absent unless S05.B passed QA (else Issue `Issues/screenshot-annotate.md`).

**Preserved invariants.** Preview errors never change capture truth; no artifact bytes copied into browser storage; Chat keeps one upload client / one state owner; brief shows no path through chat routes.

**Test migrations here.** None expected.
