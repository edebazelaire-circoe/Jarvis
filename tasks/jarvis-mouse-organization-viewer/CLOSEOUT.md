# Mouse, organization and viewer — closeout in progress

Status: S01-S04 accepted; S05 reopened for observed fullscreen/viewer coordination defect F2. All20 S06 shards finished; corrective validation and baseline comparisons remain. Human acceptance is pending.

The work lives in `C:/Projects/jarvis/mov`, branch `task/jarvis-mouse-organization-viewer`, based on refreshed `origin/main c0858a8000e2ca23b57231edb8f46c643080ad07`. The daily checkout and live Jarvis were not changed or restarted. The supplied Drive folder is verified in `current`; no main merge, archive move, branch deletion or handoff deletion has happened.

## Implemented behavior and commits

| Slice | Machine status | Main integration commits |
|---|---|---|
| S00 readiness | READY; lifecycle fallback and canonical ownership documented | `5571fb07` and subsequent S0 contract/audit amendments |
| S01 atomic layout | Accepted: explicit compared targets, authority, atomic persistence and stale refusal | `8425144f`, independent adversarial QA `cf181656`, acceptance `1d43b3a3` |
| S02 mouse/selection | Accepted: eight resize sides, Shift rebasing, stable selection/context and viewer intent | `ee515a77`, independent acceptance `5218ba88` |
| S03 viewer shell | Accepted: native full-viewport dialog, layouts, image pan/zoom, history and safe provider lifecycle | `c3b9ea7d`, `39f05040`, independent UI `6e488d34`, boundary QA `e22b9b79`, rank docs `375546a7` |
| S04 public agent projection | Accepted: real Work State, durable mission, actual children/artifacts and truthful actions | `1fc8a55b`, independent acceptance `ee6acbec` |
| S05 integration | Reopened for F2 coordination; prior acceptance: organization/undo, atomic group drop, real content/agents, Stop and fresh draft Ask | `5feebb58`, freshness rework `3bf96f89`, independent actual-Core evidence `c88f7b6f`, rework verification `4cb4724f` |
| S06 final convergence | In progress: 20/20 shards complete; corrective verification pending | `97d56f11`, static verifier evidence `7bdd5fa9`; preview helper `1b7b5a60` |

Each organization or group drag uses one atomic scene command with at most one revision. Undo is bounded, local and compare-protected; another actor's geometry cannot be overwritten by stale history. Opening or rearranging the viewer does not write scene geometry. Ask preserves the current Board's draft and never sends automatically.

## Existing evidence

- S01: independent33 protocol/domain checks, critical adversarial7 checks plus32 restored unit checks, six targeted mutants killed. S03 Escape boundary: five unmutated checks and four targeted mutants killed on copied JavaScript only.
- S02: independent17 mouse/keyboard/math/provider checks, including actual Chrome edges/corners, Shift rebasing, right-click/menu paths and original focus.
- S03: independent15 shell/bridge/Chrome checks, both themes, native focus/inert/restore, document history/scroll, pan/zoom, reduced motion and 200%-equivalent viewport; detector clear and screenshots inspected.
- S04: independent23 checks, including actual isolated Core/SQLite/HTTP → production JS running/terminal/restart-unknown projection and durable mission preservation.
- S05: eight distinct real Core/SQLite/Control Center/Chromium scenarios. Actual three-object group drag changed from baseline three writes/revisions20→23 to one compared command/revision20→21. Fixed/orbit organization+undo is20→21→22; stale undo refuses. Registered PNG and native text, agent artifacts/Back/completion/restart, actual job cancellation and retained Ask draft verified. Native text wheel scroll280→280 retains the same DOM across layout with no scene write. Freshness rework/affected Stop–Ask independently3 passed in37.62s.
- S06 narrow convergence: source/layer/group/pure checks31 passed15.76s, expanded source guard/served-page10 passed6.07s, selected-layout Chromium1 passed9.17s. PM inspected desktop/narrow screenshots. Canonical static `scripts/verify_release.py` passed. Complete canonical gate: 25,378 passed,43 failed,162 skipped across1,062 modules at97d56f11. Raw global gate remains red; dispositions and corrective checks are retained separately. Coexistence probe2 passed/1 failed reveals F2 below.

The exact commands, execution history (including corrected harness failures), JUnit, mutation results, JSON observations and screenshots live under each Slice's `qa/`/`evidence/`. No preparatory failure was silently relabeled as a success. S06 uses the existing canonical release runner and explicit dated known-failure registry; it does not introduce a parallel test policy.

## Canonical implementations and documentation

Reuse: Scene command/reducer/resolver/writer/service transaction and batch report; shared hold/resize/geometry transforms; pending mutation owner; Artifact registry and ID-derived payload routes; PrefabHost/shim/protocol; native dialog modality; Work State and Mission History; canonical `/api/jobs/cancel`; unified chat state/draft ownership. No second gesture engine, scene store, agent status owner, renderer, fullscreen state machine or message bus.

Updated canonical references: `docs/ARCHITECTURE.md`, `docs/scene-model.md`, `docs/scene-selection-batch.md`, `docs/object-viewer.md`, `docs/agent-detail-viewer.md`, `docs/prefabs.md`, `docs/control-center-shell.md`, `docs/chat.md`. Task READINESS, per-Slice contracts/reports, Issues and execution log preserve amendments and the corrected group-drag audit.

## Limits and remaining judgement

- PDF uses an explicit unavailable-provider fallback and canonical Open PDF link; this task adds no PDF engine. Native text/image state is retained; canonical PrefabHost pause may recreate an opaque iframe and reset its internal state.
- There is no canonical individual CLI-child Stop. Its disabled explanation is intentional; Stop is active for cancellable live Core jobs. No public future plan or progress percentage is invented when absent.
- The actual configured CLI provider reported its weekly quota exhausted. Running→failed public state was observed, but **successful model inference was not verified**. No retry, model substitution or fabricated success. See S05 `qa/real-execution.json` and `qa/trace-analysis.md`.
- Physical screen reader, camera/Bare Hands hardware, macOS Cmd and multi-monitor permission interaction were not tested on this Windows workstation. Automated keyboard/Bare Hands/presentation neighbors belong to the final suite; their actual outcomes will be recorded below.
- Human review should judge interaction comfort, resize affordances, organization menu clarity and comparison readability during a representative mouse/keyboard Board session. Launch, persistence, stale state and action correctness are machine QA responsibilities already exercised, not delegated to the reviewer.

Final machine verdict, residual baseline failures, preview URL/expiry and acceptance request: pending completion of S06.
