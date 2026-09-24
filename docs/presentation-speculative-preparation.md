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

1. **that path is durable, and D13 forbids it.** A job there is accepted by
   `state.accept_speculative_job` (capacity 16), written to SQLite and
   recoverable after a restart. Presentation's memory is bounded and
   session-scoped; backing a preparation with it would make survive exactly
   what D13 says must not. This is the decisive argument.
2. `OwnedJobExecution._slots` is an `asyncio.Semaphore(1)`, and `_execute`
   holds it for the whole worker call (`timeout_s` defaults to 900 s). What is
   missing there is not cancellation — that machinery exists — but
   **concurrency**: a speculative job would occupy the only slot and delay the
   next addressed turn, which D08 refuses.
3. Incidentally, its execution profile launches the CLI with **`--tools ""`**
   (`jarvis/runtime/claude_local.py`), so zero tools, where D07 calls for
   research and reading. Widening that profile would **not** touch the
   addressed path — `back_brain_worker.py` selects `speculative_analysis` only
   for a speculative job, the addressed one staying on `job_result` — but it
   would change what today's `speculative_analysis` consumers see
   (`live_delegation.py`). A real argument, and the weakest of the three.

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
| `display_preparation` | `scene_inspect`, `scene_query`, `scene_get`, `scene_create_object` — **never ambient** |

Seven names project onto **four** distinct tool sets: `code_inspection` and
`document_resolution` grant exactly the same thing, and `data_analysis` is a
strict subset of both. The names state the work's *intention*, not a further
technical boundary, and a reader who counts seven boundaries is wrong.
`TRIGGER_PREPARATION` reaches only four of the seven; the other three are
reachable only through `reserve_explicit`, which has no production caller in
this slice.

### Ambient and explicit are not the same grant

`scene_create_object` is declared **`WRITE`**, not `EPHEMERAL`. An earlier
version followed `BOARD_PRESENT`'s precedent, and that precedent does not
transfer: `board_present` POSTs to a loopback board that **stores nothing**
(`adapters/barehands_board.py`), while `scene_create_object` reaches
`INSERT INTO scene_objects` in `data/state/scene.sqlite3`
(`core/scene_service.py` → `adapters/sqlite_scene.py`) and **survives a process
restart**. A scene object is durable; calling it ephemeral made D13 false.

So the capability that grants it — `display_preparation` — sits **outside**
`AMBIENT_CAPABILITIES`. A grant whose origin is `AMBIENT` cannot even be
*constructed* with it; the refusal is in `SpeculativeGrant.__post_init__`, so
an illegal ambient grant cannot exist and no path can receive one.

`_check_capability_table()` runs at **module load**: every granted tool must be
declared; every tool granted by an **ambient** capability must carry a risk in
`GRANTABLE_RISKS` (`READ` or `EPHEMERAL` — `WRITE` excluded in exactly one
place); and no granted tool may appear in `FORBIDDEN_TOOL_NAMES` (compared
lower-cased, so `Bash` cannot slip past `bash`). Granting a write tool to an
ambient capability breaks the import of the module, and therefore of the
package: the fault cannot hide in a rarely-taken branch.

`SpeculativeGrant.permits` is an **allowlist**. An unknown tool is refused for
being unknown, not for having been thought of — the lesson of Slice 04's URL
schemes and Slice 06's import guards.

`SpeculativeToolbox` is the only route from a runner to a tool. It asks the
grant, then delegates. A write tool wired into the toolbox is never called —
not called-then-undone: never called. Every attempt is counted in
`tools_refused`.

### What is deliberately granted to nobody

`scene_set_visibility`, `scene_archive`, `scene_pin`, `scene_update_many`,
`scene_add_artifact` and — this one was the defect — **`scene_update_object`**
belong to no capability.

`SceneDisplayTools.update_object` accepts `visibility`, an arbitrary
`object_id`, **and** `geometry`, `layer` and `order`. It is
`scene_set_visibility` and more, including the user's placement authority that
D12 says never to bypass. Granting it three lines below the table that withheld
`scene_set_visibility` was not a boundary; a job could reveal its own staged
object, and hide or move one of the user's.

A preparation stages a hidden object; revealing it is a decision of policy or of
an explicit turn, never a gesture of the work itself.

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
(case-folded, whitespace-collapsed, edge-punctuation stripped, bounded, **then
stripped again**: slicing a space-collapsed string at 64 lands on a space often
enough that ordinary long triggers were refused as illegal requests) — and why
**the key is never journalled**.

The 64-character bound also **merges things that are not the same**. Against
`MAX_TRIGGER_TEXT_CHARS = 320` it keeps a fifth of a maximal trigger, so two
claims differing only after the 64th character — "…in France" and "…in Germany"
— share a key, and the second is answered `COALESCED` without being prepared.
It is bounded and it fails safe (we prepare less, never more), but it is not the
"by topic" coalescing the name suggests. `SpeculativeJobKey.value` carries speech;
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

A finding with `stage_hidden` gets a scene object **if the job's grant carries
`display_preparation`** — which an ambient grant cannot. Staging is the only
effect in this lane that reaches durable state, and it was once the only one the
capability table did not gate: a `new_topic` ambient job, with no scene tool in
its grant at all, created a scene object. `_store_finding` now asks
`grant.may_stage` and counts `stage_refused`.

The stored resource points at **that object** (`ResourceKind.SCENE_OBJECT`),
because it is the object that will be revealed.

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

### A staged object has a lifetime

Because it is durable, "the session ended" does not make it go away — the scene
has to be told. `retire()` therefore reclaims every object this lane staged, via
`scene_archive`, which is granted to no capability: only the lane takes back
what it put there, never the job that asked for it. Failures are counted
(`discard_failures`) and said, never swallowed.

Two bounds back that up: `MAX_STAGED_OBJECTS` (8) caps how many can exist at
once, and `stats()` publishes `staged_objects` so the count is readable. Without
them each preparation left an object forever, counting against
`MAX_SCENE_OBJECTS` (512) until the scene answered `SCENE_FULL` — and one
existing brain call, `scene_set_visibility(scope="all_hidden",
visibility="visible")`, reveals **every** hidden object indiscriminately,
including speculative stagings the user never asked for.

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
| Staging not granted | `stage_refused` | nothing staged, nothing stored |
| Staged budget reached | `stage_refused` / `stage_budget_full` | nothing staged, said |
| Reclaiming a staged object fails | `discard_failures` | counted and said |
| Journal raises | `diagnostic_failures` | swallowed — a broken journal must not take down the lane it observes — but **counted**, so `stats()` cannot report a healthy lane beside an empty trace |

The expected path is journalled at `info` too
(`presentation.speculative.{bound,admitted,coalesced,prepared,revealed,retired}`),
so an empty trace cannot mean both "fine" and "dead".

## 11. Nothing that was said, nowhere in the trace

No journal line from this lane carries a trigger's text, a title, a locator or
a key value — only ids, counts, codes and the key's digest. A test plants a
distinctive phrase, drives the whole lane and searches every emitted line for
it. The first version failed that test: it journalled `SpeculativeJobKey.value`,
which carries the sentence `_references` handed over.

**And no exception text either.** This is the one deliberate departure from "a
failure is told in its own words": a runner is handed `request.text`, which is
speech, and any runner echoing its input into an error message would deposit it
here, at `error`, in a durable file. A second version interpolated `{exc}` in
five places and three of them leaked. Lines therefore carry `error_class` and a
stable code; a failure's full text belongs to the runner's own channel, not to
the room's trace. The test drives the **failure** paths, not only the happy one
where the rule holds for free.

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
- **No persistence of its own.** The lane keeps nothing on disk. Its one
  durable footprint is the scene objects it stages, and D13 is honoured by
  *reclaiming* them when the session or the mode ends rather than by pretending
  they were ephemeral — which is what an earlier version of this page claimed,
  wrongly.
