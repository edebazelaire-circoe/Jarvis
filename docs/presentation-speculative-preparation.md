# Presentation speculative preparation: research that stays invisible

Canonical contract for Slice 08 of `jarvis-presentation-interaction-mode`.
Decisions **D03**, **D07**, **D08**, **D12** and **D13** are locked and this
page is where they become code. Companion pages:
[presentation-ambient-lane.md](presentation-ambient-lane.md) (where the
triggers come from), [presentation-working-set.md](presentation-working-set.md)
(where the results land), [scene-model.md](scene-model.md) (who owns the
display).

Implementation: `jarvis/domain/presentation_speculative.py` (the vocabulary and
**the capability table**, pure), `jarvis/core/presentation_speculative.py` (the
service), `jarvis/runtime/presentation_staging.py` (hidden scene objects).
Conformance: `tests/unit/test_presentation_speculative.py`.

## 1. The chain

```text
AmbientTrigger                      Slice 06, handed over by `on_trigger`
   -> TRIGGER_PREPARATION           closed table: nature -> priority + capabilities
   -> SpeculativeJobKey             coalescing by topic and resource
   -> admission                     bounded pool, explicit reserve, preemption
   -> SpeculativePreparationRunner  a port; a bounded sub-agent in production
   -> SpeculativeToolbox            the only way to a tool, allowlist-checked
   -> DisplaySceneStager            optional: a hidden scene object
   -> PresentationWorkingSetStore   the prepared resource, with provenance
```

Nothing on this path speaks, and nothing on it writes.

## 2. The freshness audit, and why this is a separate lane

`SLICE.md` asks for an audit of the existing `back_brain` speculative support
before any machinery is built. It was done, and it concluded **reuse the
vocabulary, refuse the execution path**. Two measured facts:

1. `BackBrainTaskService` already carries `scope="speculative_analysis"`, with
   its own job id, its own `BackBrainSpeculativeProvenance`, a worker
   capability probe and a durable unavailability record. But its execution
   profile launches the CLI with **`--tools ""`** (`jarvis/runtime/claude_local.py`,
   `restricted_args`). Zero tools. That is right for re-reading a transcript
   and wrong for D07, which calls for research, document resolution, code
   inspection and web lookup. Widening that profile would widen the addressed
   path that shares it.
2. `OwnedJobExecution._slots` is an `asyncio.Semaphore(1)`, and `_execute`
   holds it for the whole worker call (`timeout_s` defaults to 900 s). A
   speculative job admitted through that path would **block the next addressed
   turn** — D08 violated as written, with no preemption available, because
   nothing in that semaphore gives a slot back.

So this lane has its own pool, its own execution and its own priorities. What
is reused rather than redeclared: `VoiceStateDisposition` for dispositions,
`RiskLevel` and `FORBIDDEN_TOOL_NAMES` for authority, `ResourceReference` /
`PreparedResource` / `ObservationProvenance` for what gets stored,
`SceneDisplayTools` for the display, `DiagnosticSink` for the journal.

**`BackBrainTaskService`'s addressed-only admission is untouched**, and a test
takes the import closure of this service to show there is no edge to it at all.

## 3. The capability boundary is data

The rule "ambient may search, never write" does not live in a docstring. It
lives in two tables in `jarvis/domain/presentation_speculative.py`:

- `SPECULATIVE_TOOL_RISK` — every tool this lane can name, with its
  `RiskLevel` (`jarvis/domain/actions.py`, the vocabulary `V1_ACTION_POLICY`
  already uses). Not a second risk vocabulary;
- `CAPABILITY_TOOLS` — what each `SpeculativeCapability` grants.

| Capability | Grants |
| --- | --- |
| `research_search` | `WebSearch`, `Grep`, `Glob`, `memory_search` |
| `document_resolution` | `Read`, `Glob`, `Grep` |
| `code_inspection` | `Read`, `Glob`, `Grep` |
| `web_news_lookup` | `WebSearch`, `WebFetch` |
| `data_analysis` | `Read`, `Glob` |
| `fact_verification` | `WebSearch`, `WebFetch`, `Read`, `memory_search` |
| `display_preparation` | `scene_inspect`, `scene_query`, `scene_get`, `scene_create_object`, `scene_update_object` |

`_check_capability_table()` runs at **module load**: every granted tool must be
declared, must carry a risk in `GRANTABLE_RISKS` (`READ` or `EPHEMERAL` —
`WRITE` is excluded in exactly one place), and must not appear in
`FORBIDDEN_TOOL_NAMES` (compared lower-cased, so `Bash` cannot slip past
`bash`). Granting a write tool breaks the import of the module, and therefore
of the package: the fault cannot hide in a rarely-taken branch.

`SpeculativeGrant.permits` is an **allowlist**. An unknown tool is refused for
being unknown, not for having been thought of — the lesson of Slice 04's URL
schemes and Slice 06's import guards.

`SpeculativeToolbox` is the only route from a runner to a tool. It asks the
grant, then delegates. A write tool wired into the toolbox is never called —
not called-then-undone: never called. Every attempt is counted in
`tools_refused`.

### What is deliberately granted to nobody

`scene_set_visibility`, `scene_archive` and `scene_pin` belong to **no**
capability. A preparation stages a hidden object; revealing it is a decision of
policy or of an explicit turn, never a gesture of the work itself. Without that
split, "normally invisible" would depend on the job's good behaviour.

### What the risk table must never contradict

Where a name is shared with `V1_ACTION_POLICY`, the risk must be identical.
`memory_append` is `WRITE` there, so it appears in neither table here. A test
pins that agreement, because two vocabularies about the same word is how they
drift apart in silence.

## 4. Priorities and budget (D08)

P0–P4 lives **here**, never on canonical `WorkItem`. `jarvis/domain/work_state.py`
has no priority field and gains none: it is shared with Simple, and widening it
would be a D14 regression-boundary violation.

| Rank | Meaning | Sacrificial? |
| --- | --- | --- |
| `P0_ADDRESSED_TURN` | an explicit addressed turn — lives in the brain, **never admitted here** | no |
| `P1_EXPLICIT_PREPARATION` | preparation asked for by an explicit turn | no |
| `P2_FACT_VERIFICATION` | from a `checkable_claim` trigger | yes |
| `P3_REFERENCE_RESOLUTION` | from `external_reference` or `open_question` | yes |
| `P4_TOPIC_EXPLORATION` | from `new_topic` | yes |

Two mechanisms, both tested against a genuinely saturated pool:

- **the reserve.** The pool is `MAX_SPECULATIVE_POOL` (8), of which
  `RESERVED_EXPLICIT_SLOTS` (2) can only be taken by an explicit rank.
  Speculative work therefore caps at 6, and a saturated speculative pool always
  leaves the reserve free. `free_explicit_slots` makes that readable rather
  than merely true;
- **preemption.** When the whole pool is full, an arriving explicit rank
  sacrifices speculative work: lowest rank first (P4 before P2), newest first
  within a rank, because a job that is nearly done has already cost what it
  will cost. `note_addressed_turn()` is what a P0 turn calls; it frees a slot
  and names what it threw away. An explicit job is never a victim.

Above both sits the structural fact: this lane holds its own pool and never
touches `BackBrainTaskService`, so no amount of speculative saturation can
consume an addressed request's capacity.

## 5. What the trigger confidences are not used for

`presentation-ambient-lane.md` §11 states plainly that the four confidences
(0.6 / 0.5 / 0.5 / 0.3) are **posed, not calibrated**. They are therefore used
here only as a tie-break within a rank, never as an admission threshold: there
is no `confidence > x` anywhere in this lane, and a trigger at 0.0 is admitted
like any other. The rank comes from the trigger's *nature*, which is closed
data, not from a number nobody has measured.

Likewise, `_references` yields a whole sentence for any of nineteen nouns. That
sentence becomes the `resource_key`, which is why the key is normalised
(case-folded, whitespace-collapsed, edge-punctuation stripped, bounded) — and
why **the key is never journalled**. `SpeculativeJobKey.value` carries speech;
`SpeculativeJobKey.digest` is what goes in a trace line.

## 6. Coalescing

A job's identity is `SpeculativeJobKey(topic_key, resource_key)`. The trigger's
*nature* forms the topic and its text the resource, because one sentence can be
both a claim to verify and a reference to resolve, and those are two different
preparations. A second trigger with the same key joins the first instead of
starting a second job; `joined` counts the arrivals and `coalesced` counts the
merges.

A finished job releases its key, so re-preparing later works. `tracked_keys` in
`stats()` exists so a test can tell "the key was released" from "the job is
gone" — the table is the one memory a leak could grow without the pool moving.

## 7. Results become working-set resources

A runner returns `PreparedFinding`s — references, never payloads, at most
`MAX_FINDINGS_PER_JOB` (4) kept per job, since the store holds 16 in total.
Each becomes a `PreparedResource` through Slice 04's own `ResourceReference`,
so the descriptor validator and the scheme allowlist are **reused, not
rewritten**. A refused reference is counted, never raised.

**Provenance is read, never invented.** The utterance's rank and `spoken_at`
come from the tail in the current snapshot. If the utterance has left the tail,
nothing is stored: a fabricated rank would make `enrichment_lag_*` wrong in the
only direction that matters (Slice 06's finding), and a losing a preparation is
cheaper than corrupting the freshness reading a deictic resolves against.
`observed_at` is the time of the **speech**; `prepared_at` is now.

Every store call's typed disposition is counted under its own name in
`store_dispositions`. None is bucketed: a disposition the lane does not know is
said at `error`, which is Slice 06's `ambient_disposition_unknown` lesson.

## 8. Hidden staging (D12)

A finding with `stage_hidden` gets a scene object, and the stored resource then
points at **that object** (`ResourceKind.SCENE_OBJECT`), because it is the
object that will be revealed.

`DisplaySceneStager` is a thin adapter over `SceneDisplayTools`. It builds no
`SceneCommand`, picks no `SceneActor`, and touches neither pin, geometry,
`exec_state` nor `work_ref` — all of which stay judged by the reducer. A test
asserts the *absence* of those symbols by AST; that is the one source-reading
test here, and it carries its justification (Slice 05's precedent).

**Hidden at birth, not hidden just afterwards.** `stage_hidden` creates the
object with `visibility="hidden"` in the *same* command. Two commands — create,
then hide — would leave it visible in between, on a screen someone is watching.
This is why `SceneDisplayTools.create_object` gained a `visibility` parameter in
this slice: `SceneObjectFields` already carried the field, only the call path
was missing. The parameter is **not** exposed on the MCP tool the brain sees;
the brain creates what it shows.

A failed staging stores nothing. There is no fallback to a visible object,
because a preparation that appears because its staging went wrong is exactly
what "normally invisible" promises never to do.

`reveal(resource_id)` sets the object visible and warms the resource
(`use_resource`). It is a policy call, not a capability.

## 9. Lifecycle

`bind_session` / `end_session` / `retire` / `apply_interaction_mode`, mirroring
the Slice 04 store. Leaving PRESENTATION cancels everything in flight;
`behaving_interaction_mode` is the reading used, so a reserved `meeting`
retires too. That reading never returns `None` — anything unreadable falls back
to `ASSISTANT`, which retires, and that is the safe direction.

**The generation counter rises before the cancellations.** A result that comes
back anyway carries a stale generation and is refused before the store is
touched. The session id alone is not enough: a session retired and re-bound
under the *same* name would otherwise let a previous life's work file its
preparation into the new one.

## 10. Failure behaviour

| Situation | Counter / code | What happens |
| --- | --- | --- |
| Runner raises | `failed` / `presentation.speculative.failed` | said at `error` in the failure's own words, the lane keeps accepting |
| Runner past `DEFAULT_JOB_TIMEOUT_S` (60 s) | `timed_out` | cancelled, counted, said |
| Runner returns a non-`SpeculativeOutcome` | `findings_invalid` | said at `error` |
| More findings than the bound | `findings_dropped_bound` | clipped and said |
| Reference refused by the Slice 04 contract | `findings_invalid` | counted with the refusal's own code |
| Utterance gone from the tail | `findings_invalid` | nothing stored, said |
| Staging raises or returns no id | `stage_failures` | nothing stored, nothing shown |
| Result returns after a retirement | `results_stale_generation` | refused before the store |
| Tool not granted | `tools_refused` | typed refusal, the tool is never called |
| Store refuses | its own code, under `store_dispositions` | counted per disposition |
| Journal raises | — | swallowed with an argument: a broken journal must not take down the lane it observes |

The expected path is journalled at `info` too
(`presentation.speculative.{bound,admitted,coalesced,prepared,revealed,retired}`),
so an empty trace cannot mean both "fine" and "dead".

## 11. Nothing that was said, nowhere in the trace

No journal line from this lane carries a trigger's text, a title, a locator or
a key value — only ids, counts, codes and the key's digest. A test plants a
distinctive phrase, drives the whole lane and searches every emitted line for
it. The first version of this lane failed that test: it journalled
`SpeculativeJobKey.value`, which carries the sentence `_references` handed over.

## 12. What this contract deliberately does not do

- **No runner.** `SpeculativePreparationRunner` is a port. Wiring a real
  bounded sub-agent — with `--tools` built from `SpeculativeGrant.allowed_tools`
  — belongs to the rollout slice, for the same reason Slices 05 and 06 left
  their composition-root wiring there.
- **No composition-root wiring**, and therefore no production activation.
- **No alert policy.** A prepared fact-check resource is a lead; attention is
  Slice 09.
- **No reveal policy.** `reveal()` exists; *when* to call it is Slice 09/10.
- **No priority on canonical work.** That is G5, and it stays that way.
- **No persistence.** That is D13.
