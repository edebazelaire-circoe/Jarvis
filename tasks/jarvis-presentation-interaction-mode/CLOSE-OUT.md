# Close-out — `jarvis-presentation-interaction-mode`

**Status: all twelve Slices implemented, reviewed and approved by agent 0.
Awaiting Human acceptance. Nothing has been merged, no branch deleted, no Drive folder moved.**

| | |
| --- | --- |
| Branch | `task/jarvis-presentation-interaction-mode` |
| Branch point | `ddcdb71` — exactly `task.json.source_snapshot.sha`, zero drift |
| Commits | 41 |
| Drift vs `origin/main` | **0 behind, 41 ahead** — re-checked before every dispatch; no merge needed, no conflict |
| Product change | 84 files, +45 868, **−48** |
| Handoff record | 70 files, +11 866 |
| Drive | still in `to-do` — the connector here cannot move folders |

Only 48 deletions across the whole product change. That is the main reason D14 held: the feature is
almost entirely additive, and Simple's paths were extended rather than rewritten.

---

## Slices, with their commits

| # | Slice | Commits | Rework rounds |
| --- | --- | --- | ---: |
| 00 | Project Manager readiness gate | `682f353` `c2f3a7e` `214b00c` | — |
| 01 | Interaction-mode and output-disposition contracts | `584b51f` `b75b8e9` | 1 |
| 02 | Live control plane and persistence | `52ab8cf` `abc73c9` `0de10f8` | 2 |
| 03 | Left-side mode selector | `a3e5583` `347c3c1` `48bea17` | 2 |
| 04 | Presentation working set and transcript tail | `4078acc` `34dcf0b` | 1 |
| 05 | Shared audio capture and explicit-address lane | `34de032` `0461fca` | 1 |
| 06 | Continuous ambient ingestion | `4e85429` `43c51dc` | 1 |
| 07 | Presentation response and speech policy | `708eaef` `0c122d4` | 1 |
| 08 | Speculative preparation and staged display | `6cb43d3` `064e505` | 1 |
| 09 | Fact-check attention, warning and cue | `801e5a8` `726146f` | 1 |
| 10 | Priority addressed turns | `163c409` `640589a` | 1 |
| 11 | Integration, diagnostics, privacy, rollout | `d7eeeb8` `806397a` `49c1949` | 1 |

Thirteen further `S0:` commits carry the orchestration record: the readiness gate, the Human
decisions, and one approval entry per Slice explaining what its QA proved.

**Every Slice took at least one rework round. None was approved as first delivered.**

## Validation

- **Baseline at the branch point**: 248 unit test files, 7 022 tests, **25 stable failures** plus
  three flakes. Reconciled exactly; every implementer received the named list as "not yours".
- **Three flakes**, each investigated rather than dismissed: `test_back_brain_tasks::…[owned_read]`,
  `test_back_brain_worker::test_cancel_during_spawn…[claude]` (a 2 s deadline on a spawn/cancel race),
  and `test_presentation_integration::test_une_source_evincee_par_son_propre_rangement_n_est_pas_citee`
  — which tests the eviction race Slice 11 documents as *unresolved* and is itself order-dependent.
- **Final regression**: 2 720 passed / 13 failed across the 77 affected suites — the identical
  baseline set, test for test. Agent 0 independently re-ran 912 tests across the eleven presentation
  and composition suites.
- **QA**: 24 mandated passes — `qa-verification` and `code-review` on every Slice, plus
  `runtime-validation` on 02, 03 and 09 (two in a real browser driven over CDP) and
  `agent-trace-analysis` on 11.
- **Mutation testing** became standard from Slice 04 onward, and agent 0 required from Slice 09 that
  each harness refuse a red baseline and carry a cosmetic control that must survive.
- **Release verifier**: six of seven static gates pass. The seventh fails at `barehands_replay.py:144`
  and **failed identically at the branch point** — `Issues/003`, deliberately not fixed here.

## Documentation

Seven new contract pages (`docs/presentation-*.md`, `docs/interaction-mode.md`), plus
`ARCHITECTURE.md`, `OPERATIONS.md` with an operator runbook, and `ACCEPTANCE_STATUS.md`.
20 test files added or changed.

## Canonical reuse

Verified against source by reviewers rather than taken on report:

- `VoiceStateDisposition` imported as-is — all seven values reached;
- `CoreWorkView` / `CoreWorkTransport` shape **and** unavailability vocabulary imported, not copied;
- `bgCue` remains the **sole** sound emitter — Slice 09 added only the gate that was missing, and no
  second poll, ledger or notification system;
- `CompositeWakeWordBackend` extended rather than forked;
- `RiskLevel`, `SpeechKind`, `CaptureObserver`, `SceneDisplayTools`, `BackgroundEventLedger`,
  `frame_db`, `SpeechGate`, `check_text` all reused at their existing contracts;
- the neutral `TranscriptionBackend` port became load-bearing for the first time since it was written.

## Residual risks — the honest list

1. **No workstation validation of anything.** No microphone, speaker, wake word, transcription
   provider, `claude` CLI or real Scene was ever exercised. Every number comes from live objects with
   faked outer boundaries. This is by design — the Human's live stack holds the devices — but it
   means **the five Human checks are the first contact with reality**.
2. **`ASK_BRAIN` carries no projection.** A knowledge question reaches the brain byte-identically to
   Simple: no working set, no fresh tail, no prepared material. `submit_brain_turn` has no context
   parameter and the turn is classified after submission by Slice 07's design. **Consequence for the
   Human: step 5 of the workstation checklist cannot distinguish PRESENTATION from SIMPLE.** Judge it
   as "he answers", not "he answers using the room".
3. **A named visual command is not matched to prepared material.** "Montre-moi le bilan Q3" will not
   reuse a staged object; only deictic references resolve. A lexical matcher here would be a second
   classifier, weaker than the brain's — a defensible choice, now stated rather than implied.
4. **Up to six concurrent restricted `claude` sub-agents** is a paper number. Nobody has watched it
   on this machine, and RAM here is routinely under 2 GB free.
5. **The CLI's acceptance of the argv is unproven.** If the installed Claude CLI rejects
   `--tools "Glob,Grep,Read,WebFetch,WebSearch"`, every preparation fails loudly at start with
   `presentation_preparation_start_failed`. Loud, but untested against a real CLI.
6. **A provenance eviction race** (limitation 9bis): the source ring holds 12; under concurrent
   preparation a source can be evicted between recording and citation, producing
   `attention_provenance_unknown` — the right failure, but for the wrong reason.
7. **The staged-object ledger reclaims at PRESENTATION entry, not Voice start**, so orphans from an
   unclean stop survive until someone re-enters. A lost ledger leaks silently against the 512-object
   scene ceiling.
8. **Two pre-existing defects this task surfaced but did not own**: `Issues/001` (a corrupt settings
   file reads as a first launch, silently — a UTF-8 BOM suffices) and `Issues/002` (dropped
   transcripts write `text[:300]` into the trace; Presentation multiplies both the volume and the
   number of people whose speech is captured).

## Human checks — five, all now reachable, none run

| id | Slice | What it settles |
| --- | --- | --- |
| `HV-PRES-MODE-01` | 03 | Selector placement, keyboard, screen reader, and whether amber reads as "running" rather than "warning" |
| `HV-PRES-AUDIO-01` | 05 | One microphone owner, triggers responsive under ambient load |
| `HV-PRES-SPEECH-01` | 07 | Silence on visual commands, speech when it earns its place — **run once per voice architecture** |
| `HV-PRES-ALERT-01` | 09 | Discretion of the contradiction cue and card |
| `HV-PRES-E2E-01` | 11 | The full walkthrough; twelve steps in `docs/ACCEPTANCE_STATUS.md` |

**Restart the JARVIS stack from this branch first** — the running one predates the work.

### Two decisions still yours

1. **Should a contradiction sound different from an agent crashing?** Today it plays the existing
   failure cue. Adding a second emitter was refused deliberately — two emitters means two sounds for
   one event — so this is a one-line change to the cue, not an architecture question.
2. **Is six concurrent sub-agents acceptable on this machine?** See risk 4.

## What agent 0 got wrong

Recorded because the handoff is the durable artefact and a corrected record is worth more than a
clean one.

- **I said the z-index registry comment was test-asserted** and made it a constraint in two dispatch
  briefs. It is not; the test greps CSS, not prose. Corrected in `READINESS.md` §3 G6.
- **I recorded at Slice 06 that D06 holds by a "data dependency".** True of the ambient lane's
  ordering — wrong as the store-level invariant Slice 10 then built on, and the store did not enforce
  it. I had written the narrow finding in language broad enough to be reused. Corrected in the LOG
  and in Slice 10's rework.
- **I told the Human room speech stayed out of durable sinks.** True of every slice I had checked,
  false of the finished system — `claude_local.py:989` wrote the whole prompt, and Slice 11 supplied
  the producer. Found by QA, fixed in the Slice 11 rework, and the correction stated plainly rather
  than absorbed.
- **I dispatched the Slice 08 rework while a QA agent was still mutating the same checkout.** No work
  was lost, but the `one-implementer-per-worktree` memory has been corrected: **a QA agent that
  mutation-tests is a writer, not a reader.**
- **I twice concluded a guard was weak when my own probe had simply not reached it** — once because
  the edit did not apply, once because the `-k` filter never selected the test. A passing probe
  proves nothing until both are confirmed.
