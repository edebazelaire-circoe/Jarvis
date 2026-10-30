# Independent S05 code review

Reviewed final source implementation `80607352` integrated as `5feebb58`, Slice
contract/amendment, implementation report, canonical predecessor seams and
actual runtime evidence described in `runtime-verification.md`. Reviewer did
not author S05 or modify product code. S03 was authored earlier by this reviewer
and independently accepted by PM; its internals are not self-certified here.

## Findings

**F1 — MAJOR, resolved by scoped rework: canonical chat conversation freshness.**
Initial `JarvisChat.prefill` refreshed state only if its retained model had no
conversation ID. A closed chat could retain BoardA's cid after Core switched
to BoardB; opening it starts an async state loop, while prefill can append/save
the question into A before the later rescope. The new active-Board check alone
does not prove the retained cid belongs to the current canonical binding. PM
accepted this source finding and assigned the focused correction to S2.
Reverification below covers the rework diff and closed A→B→A draft retention.

No additional blocking product defect was established by the reviewed final
code or eight distinct actual-Core browser scenarios. Preparatory QA selector,
canonical seed-kind and readiness assumptions were corrected transparently;
see JUnit history in the runtime report.

## Canonical reuse, boundaries and failure handling

- Planner is pure and deterministic, with existing spatial ordering. Page uses
  shared hold.start/to/place/finish, rather than a second orbit inverse or
  gesture engine. Core remains geometry authority. `layout_selection` compares
  every target; one atomic transaction is demonstrated for organization and
  actual group mouse drag.
- The existing pending owner holds every optimistic target; refusal rolls back
  the full set. Context/epoch changes clear the bounded local undo ring and
  prevent late results entering another Board's history. History has explicit
  TTL/size, visibility/representation/context/geometry guards; Core compare
  remains final. Pin preservation for geometry-only undo is documented.
- Forward and reverse byte budgets include UTF-8 and conservative canonical
  Python float overhead, retaining the64KiB policy. No chunked mutation or
  unsendable undo entry is introduced.
- S03 owns native dialog, layout/history/image state and provider lifecycle.
  S05 maps actual Artifact metadata to ID-derived payload URLs, native safe
  markdown/text rendering or canonical PrefabHost slots. No direct srcdoc,
  arbitrary iframe message bridge, new PDF engine or fullscreen owner.
- S04 public reader owns status/mission/steps/artifact provenance. S05 displays
  honest unavailable/unknown states, bounded polling and optional fields; no
  private prompt/trace/thinking enters its model. Provider pause/dispose hooks
  use canonical lifecycle; opaque iframe internals are not promised preserved.
- Stop uses canonical `/api/jobs/cancel`, actual stopOutcome and bounded
  request/terminal confirmation; CLI Stop stays explained/disabled. Async
  loading/failure/action feedback stays inside the native top layer. Ask is a
  draft adapter, without a new communication bus/send/Voice toggle.

## Documentation/tests and residual limits

Final IMPLEMENTATION/API/docs match the inspected modules and stable DOM
hooks. Scoped pure/browser tests exist for every planner action, custom grid,
wire budget, stale/history limits, hold release and canonical provider Escape;
their author-reported results are not substituted for independent actual-Core
evidence. Our focused runtime covers the actual integration and real mutation
protocol; no full suite was run here.

Selected optional public token/tool counters are projected but not rendered;
PM classifies this as polish rather than required hierarchy. Conditional PDF
fallback remains truthfully documented. Native text preserves DOM/scroll;
PrefabHost pause can tear down opaque iframe internals. The optional real-model
probe is quota blocked, not a successful inference. These limits are stated,
not silently replaced by mocked success.

## F1 rework verification

Integrated PM commit `3bf96f89` (source
`ba2f3b92f851c21fceaa342f56d6346a70112d4e`) into QA at `8a1156ad`.
Read the exact chat module/test/docs diff. `prefill` now settles any in-flight
state read, requires a fresh canonical channel response, and validates returned
Board/cid/current model identity before appending. Coalescing keeps one state
read in flight; a concurrent fresh request may share the newly started fresh
read. Cancelled signal results cannot mutate the draft or apply their response
as new channel state. Existing rescope/draft ownership remains canonical.

Independently ran both `test_chat_prefill_browser.py` regressions plus the
actual-Core Stop/Ask scenario: **3 passed in37.62s**. The closed-chat test
explicitly demonstrates stale retained A identity, delayed read cancellation
without an append, correct B draft/question, and A return with both saved drafts
preserved. The other test retains existing text through append/overflow/abort
without turn/Voice writes. Actual Core confirms the production Ask/Stop route
still works after coalescing. JUnit is
`chat-freshness-reverification-junit.xml`; refreshed actual-Core evidence remains
`live-stop-ask.json`. Only the rework/affected path was repeated.

No unresolved blocking finding remains in this scoped independent review.
Recommend S05 acceptance based on this code review and eight actual-Core
scenarios, with the stated PDF/provider/model limits and S06/Human gates still
applying. PM decides the Slice transition and later Human acceptance/release.
