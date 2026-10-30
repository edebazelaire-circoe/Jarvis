# Mouse, organization and viewer - integration review

Status: S00-S05 machine-accepted. S06 remains open for the dense-graph click diagnosis and final affected-test verification. Human acceptance is pending; no review preview is running yet.

Worktree: `C:/Projects/jarvis/mov`, branch `task/jarvis-mouse-organization-viewer`, based on refreshed main `c0858a8000e2ca23b57231edb8f46c643080ad07`. The daily checkout and its live Jarvis were not changed or restarted. The supplied Drive folder was reverified in `current` on October30; no main merge/push, archive move, branch deletion or handoff deletion has happened.

## Delivered behavior and commits by Slice

| Slice | Result | Principal integration commits |
|---|---|---|
| S00 | READY: canonical audit, task order, lifecycle fallback and ownership | `5571fb07` and dated S0 amendments |
| S01 | Explicit atomic layout targets, all-or-none stale comparisons and geometry-only undo contract | `8425144f`; independent adversarial QA `cf181656`, acceptance `1d43b3a3` |
| S02 | Eight resize sides/corners, Shift ratio rebasing, stable group selection, context/keyboard and open intents | `ee515a77`; independent acceptance `5218ba88` |
| S03 | Native modal viewer, ten layouts/custom grid, image pan/zoom, document history and provider disposal; trusted Escape bridge | `c3b9ea7d`, `39f05040`; independent UI `6e488d34`, boundary QA `e22b9b79`, docs `375546a7` |
| S04 | Public agent detail from actual Work State/mission/artifacts, truthful unknown and canonical actions | `1fc8a55b`; independent acceptance `ee6acbec` |
| S05 | Organization/undo, one atomic group drop, real registered content/agents, Stop and fresh draft Ask; fullscreen coordination | `5feebb58`, `3bf96f89`; actual-Core QA `c88f7b6f`, `4cb4724f`; F2 rework `dc0c5036`, independent `a0c1ced2` |
| S06 | Narrow convergence, complete canonical suite, failure comparisons, conformance repairs and final review | `97d56f11`, raw full-suite proof `4d71c078`, conformance `6fb9485`, fullscreen gate `dc32268d`, readiness tests `bddc1c95`; final graph disposition pending |

One organization or group drop produces one atomic command and at most one scene revision. Undo compares the current geometry before restoring old geometry, preserves other properties and refuses stale history. Opening/rearranging the viewer never writes scene geometry. Ask preserves the current Board draft and does not send it. Shift held from the start preserves the original ratio; toggling it mid-drag rebases to the current drawn ratio without a jump.

The observed F2 defect is fixed: an armed fullscreen request refuses viewer opening with actionable French guidance, including local requests with no ID. An incoming request closes an existing viewer through its owner before the canonical prompt captures focus. It never enters/exits browser fullscreen automatically. Actual provider cancellation, Go/Cancel, focus restoration and unchanged Board state are verified.

## Validation evidence

The complete existing canonical runner finished all20 sequential shards on exact `97d56f1144cb721e7c5303f43ff71d291ed1d9bc`: **1,062 modules,25,378 passed,43 failed,162 skipped**,25,583 collected. All sessions finished; source/manifest coverage was verified, no collection/session/unseen/expired problems. The original global verdict remains **red** and its reports/logs are unchanged. Do not represent this as an all-green release suite.

Subsequent corrective checks are separate evidence:

- Four complete conformance files: **117 passed in27.8s**, canonical runner green. This repairs four old assertions that froze per-object group commits or the pre-Escape protocol, preserving stronger runtime/strict boundary assertions.
- Final canonical fullscreen controller file: **39 passed in7.0s**. Author F2 checks:64 pure/Node cases, three actual browser scenarios plus one provider AbortSignal/focus refinement. Independent actual Core/SQLite/HTTP/Chromium F2 campaign: **3 passed in28.18s**, original red proof retained separately.
- `scripts/verify_release.py` passed again after the final product rework; product/docs/tests whitespace check is clear. The imported handoff's Markdown hard breaks and historical raw JUnit formatting are retained.
- S01:33 independent protocol/domain checks, seven adversarial checks plus32 restored units; six targeted mutants killed. S03 Escape boundary: five unmutated checks and four copied-JS mutants killed.
- S02:17 independent checks, including all16 actual mouse handle cases across window/capsule, Shift toggles, group context/keyboard and restored focus.
- S03:15 independent shell/bridge/browser checks, both themes, native modality/focus, layouts/history/scroll/images, reduced motion and 200%-equivalent viewport; screenshots inspected. S04:23 independent projection/privacy/action checks, including actual Core/SQLite/HTTP to production JavaScript.
- S05: eight distinct actual Core/browser scenarios. Three-object baseline drag made three writes/revisions20-to23; the implemented path makes one compared command/revision20-to21. Fixed/orbit organization and undo produce20-to21-to22; stale undo refuses. Actual registered PNG/text, artifact/Back, completion/restart-unknown, canonical cancellation, draft retention and native wheel scroll are verified. Freshness rework had three final independent passes in37.62s.

Full-run summary and original files: [S06 evidence](slices/06-final-integration-e2e-qa/qa/evidence/). Detailed decisions: [PM failure dispositions](slices/06-final-integration-e2e-qa/qa/PM-FAILURE-DISPOSITIONS.md). Source identities, exact baseline comparisons, logs, JUnit, screenshots and diagnostic limitations are retained under each Slice's `qa/`. Preparatory/harness failures are recorded as such and never counted as passing product checks.

Current full-run classification:18 dated known failures;15 additional exact-baseline reproductions (12 source/backend cases and three recording-chip overlap cases); four corrected intentional-contract assertions; one canonical intermittent memory retry; one Chrome-bootstrap-only failure whose affected current case passed; one unchanged shutdown behavior accepted by bounded causal/source exclusion; two Settings readiness repairs awaiting their independent check; one dense-graph failure still blocking. The trace-based shutdown disposition does not claim its original failure was reproduced or its timing cause measured.

## Reuse and documentation

Existing owners remain authoritative: Scene command/reducer/resolver/writer/transaction and batch reports; shared hold/resize/geometry math and pending mutations; Artifact registry/ID-derived payload routes; PrefabHost/shim/protocol; native dialog modality; Work State and Mission History; `/api/jobs/cancel`; unified Board chat state/draft; canonical fullscreen controller. There is no second scene store, renderer, gesture engine, status owner, fullscreen state machine, message bus or model-facing tool expansion. Actual baseline/current model-visible catalogs are identical (21tools/40,015bytes); the new SceneOp is not published as a model tool.

Canonical documentation updated: `docs/ARCHITECTURE.md`, `docs/scene-model.md`, `docs/scene-selection-batch.md`, `docs/object-viewer.md`, `docs/agent-detail-viewer.md`, `docs/prefabs.md`, `docs/control-center-shell.md`, `docs/chat.md`. Task READINESS, contracts, implementation/QA reports, Issues and LOG preserve amendments, including the corrected atomic-group audit and the observed F2 return to its owner.

## Material limits

- PDF has an explicit unavailable-provider state and canonical Open PDF fallback; no new PDF engine. Native image/text state is retained; canonical PrefabHost pause can recreate an opaque iframe and reset its internal state.
- Stop applies to cancellable live Core jobs. There is no canonical individual CLI-child Stop; its disabled explanation is intentional. No future plan or progress percentage is invented when not published.
- The actual configured Claude CLI attempt was refused by its weekly quota (cost0). Public running-to-failed state was observed, but **successful model inference is unverified**. No retry, substitution or fabricated success. See S05 real-execution/trace-analysis evidence.
- Undo is local,20entries/120seconds, with Board/scene/epoch/representation/geometry freshness checks. The64KiB command limit prevails over the512-object structural maximum; there is no partial chunking.
- Physical screen reader, camera/Bare Hands hardware, macOS Cmd and multi-monitor permission interactions were not physically tested on this Windows workstation. Their automated neighbors and the new keyboard/motion/focus paths have the evidence described above. Optional paid/hardware/Remotion tests were skipped according to their existing opt-ins.

## Human review and lifecycle

After machine QA closes, a separate, clearly labeled demonstration sandbox will be started with its own data/ports and bounded two-hour lifetime. No model request or daily runtime is used. The observed URL/PID/expiry will be recorded here before asking for review.

Human judgement: complete a representative mouse/keyboard Board session: select objects; resize edges/corners with Shift; organize and undo; compare documents/layouts; inspect agent detail/Stop/Ask. Judge interaction comfort and coherence. Launch/persistence/stale-state/action correctness are machine QA responsibilities, not delegated to the reviewer.

No main integration or Drive completion is authorized yet. The handle-task skill requires explicit Human acceptance. After future integration, the user's Core/Control Center will need a normal restart to load the new Python/JavaScript; no daily restart has been performed.
