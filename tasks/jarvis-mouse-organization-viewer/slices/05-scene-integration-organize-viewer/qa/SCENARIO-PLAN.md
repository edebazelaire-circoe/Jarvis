# Independent S05 live acceptance preparation

Status: harness prepared; S05 implementation/review verdict pending integration.

The harness starts the existing isolated `JobCore` fixture (real SQLite and
Core HTTP, controlled blocking worker) and the actual Control Center app on
ephemeral ports. Production Scene/Work/Mission/Session transports are used.
No call starts the user's Jarvis or a real CLI/model. The disposable Chrome
profile uses canonical profile-scoped cleanup; no taskkill tree operation.

Only QA-owned `/qa/*` routes seed external canonical facts, expose a snapshot,
complete Work State or restart this isolated Core. Production mutations go
through the actual page→Control Center→Core routes and transaction. CDP
Network events independently record path/method/body/status; there is no
mutation fetch double. Python's event loop stays alive while Node drives UI.

Seeds: three placed/pinned native note windows; registered text Artifact with
real `/api/artifacts/{id}` metadata; registered finalized PNG Artifact with
real payload bytes; public mission and live parent/child Work State; one real
running Core job using controlled blocking worker; actual explains relation.
No provider traces/private reasoning supplied or inferred.

Prepared executable scenarios:

1. Multi-select three notes with real Ctrl-clicks; right-click selected member
   preserves group; context Organize→Row results in exactly one Core revision
   and one layout_selection command. Enter opens compatible selection;
   layout/close preserves boxes and selection. Ctrl+Z restores geometry in
   exactly one revision with expected_geometry on all targets.
2. A later external Core geometry edit makes undo stale: no overwrite, no
   scene revision from refused undo, visible recovery feedback.
3. Double-click real registered PNG, then agent: mission/activity/status,
   disabled individual CLI Stop. Related real text Artifact opens, Back
   returns; canonical WorkState completion refreshes; isolated restart keeps
   durable mission but status becomes unknown.
4. Ask preserves an already typed main-chat draft and target identity;
   no automatic chat turn or Voice toggle. Stop on real running Core job uses
   only /api/jobs/cancel and actual JobService reaches cancelled, with feedback
   inside native top-layer dialog.

Initial infrastructure preflight (before S05 implementation): 1 passed,
real app rendered7 seeded scene nodes; no browser
exceptions and no page scene mutation. `live-preflight.json` is evidence for
infrastructure only, not acceptance of unintegrated S05 code.

One separate opt-in real-model request was attempted through an isolated Core
job and the production public agent-detail reader. Claude reported
`claude-sonnet-5-5` but refused at the account's weekly quota, with cost$0.
Actual Work State changed running→failed; no successful model response is
claimed. See `trace-analysis.md` and `real-execution.json`. The deterministic
browser harness itself still makes no model calls.

Broader deterministic action matrix, mixed nonresizable dimensions,
custom-grid numeric3×8, orbit-enabled placement, focus/editable shortcut
boundaries and failure-path review remain final integration checks once code
lands. No full suite here; S06 owns that.
