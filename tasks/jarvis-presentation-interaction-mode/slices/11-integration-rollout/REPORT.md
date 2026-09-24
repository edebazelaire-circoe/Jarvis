# Slice 11 - Integration and rollout: the room finally reaches JARVIS

| | |
| --- | --- |
| Commit | `S11: la salle entre dans JARVIS, et SIMPLE ne bouge pas d'un pouce` |
| Files | 2 new runtime modules, 1 new suite, 8 modified modules, 10 documentation pages |
| Tests | **76 new** in `tests/unit/test_presentation_integration.py`, 0 moved, 0 deleted |
| Rework | **five blocking defects**, all closed; see the marked sections. Three of the five were the same shape once more: a guard tested with a double that could not fail |
| Mutations | Four rounds, **44 mutation runs**. Round 1: 32, **3 survivors**, all test gaps. Round 3: 4, **2 survivors**, one of them a bad mutation of mine. Rounds 2 and 4: **0 survivors**. The cosmetic control survived every round |
| Regression | 263 files in eight chunks: **8 082 passed, 26 failed** = the 25 declared baseline failures name for name, plus one load flake proven unrelated |
| Wiring | **All five subsystems.** Before this slice, three independent audits found zero production construction sites |
| Human checks | `HV-PRES-E2E-01` and four carried-forward checks, **none of them marked done** |

---

## 1. What was wired, and where

Slices 05, 06, 08, 09 and 10 each shipped a subsystem deliberately unwired,
with the same argument every time: wiring it earlier would have opened the room
microphone in production for no consumer, on a machine whose live Voice process
holds that device. This slice is the one that joins them.

### The two new modules

**`jarvis/runtime/presentation_runtime.py`** - the composition. Five things
live in it, and nothing else in the repository builds any of them:

| Piece | What it is |
| --- | --- |
| `PresentationComposition` | the configuration as a **dataclass**, filled once by `jarvis/app.py`; `build(session_id)` returns a fresh `PresentationStack`. A test fills the same dataclass with doubles and gets the same composition that ships |
| `PresentationStack` | one session: the working-set store, the audio session, the ambient lane, the speculative service, the attention judge, the addressed-turn service, and the ledgered stager. `start()`, `stop(reason)`, `stats()`, `emit_diagnostics()` |
| `PresentationCoordinator` | process-lifetime. Listens to the mode, enters and leaves, runs the diagnostics loop, exposes `audio` and `turns` to `PersistentVoiceRuntime` |
| `PresentationWakeRouter` | the `WakeWordBackend` the runtime receives. With no session it yields exactly the SIMPLE stack's detections; with one it consumes `ExplicitAddressLane.triggers()`, **arms the addressed turn**, and yields the trigger's label |
| `StagedObjectLedger` / `LedgeredSceneStager` | the unclean-shutdown reclamation Slice 08 carried forward |

**`jarvis/runtime/presentation_preparation.py`** - `PresentationPreparationRunner`,
the production realisation of the `SpeculativePreparationRunner` port, which had
none. Section 3 is its whole story.

### The eight wiring items of Slice 10's REPORT §9

| # | Item | Where |
| --- | --- | --- |
| 1 | build the service with store, speculative, behaving mode, journal and **`clock=time.monotonic`** | `PresentationComposition.build`; the lane's clock is **set from the same field** rather than assumed equal |
| 2 | consume `triggers()` instead of `detections()`, and `arm()` | `PresentationWakeRouter.detections` / `_label` |
| 3 | call `open(text, correlation_id=...)` where the bridge submits | `SpeechScheduler.note_addressed_turn` |
| 4 | hand `plan.situation` to the gate instead of letting it re-classify | `PresentationSpeechGate.note_addressed_turn(..., situation=)`, one retention path for both sources |
| 5 | `await deliver(plan)`, then feed the result | `SpeechScheduler._deliver_addressed_turn` |
| 6 | close the two reaction measures, and **write the audible choice down** | `note_visible_reaction` after the reveal returns; `note_audible_reaction` at the queue. Section 7 states the choice and why |
| 7 | call `conclude(correlation_id)` | in a `finally`, so a failed delivery still settles the turn |
| 8 | add the `SpeechRequest` site to `SPEECH_KIND_SITES` | done - and the site carries the **literal** `SpeechKind.QUESTION`, see below |

Item 8 turned out sharper than "add a row". The guard refuses a bare name at a
`kind=` position, and it is right to: a field copied from the verdict is a field
a future resolver can fill differently, while `VISUAL_COMMAND` admits `QUESTION`
only as a *safety* kind. So the site writes the literal and **refuses** any other
verdict, loudly. Removing the possibility beat handling it - Slice 09's lesson,
applied to Slice 10's item.

Not wired, and stated rather than glossed: **`ASK_BRAIN` does not carry
`to_brain_context()`**. Section 11 has the reason and the cost.

### The changes to existing modules

| File | Change |
| --- | --- |
| `jarvis/app.py` | `_presentation_composition(...)` + the coordinator, the router as the runtime's wake backend. +134 |
| `jarvis/runtime/voice_v2.py` | `presentation=` parameter, `presentation_session()` / `presentation_turns()`, the mode listener, the coordinator closed **before** `mute()`. +46/-1 |
| `jarvis/runtime/speech_scheduler.py` | `presentation_turns=` (a callable), open/deliver/conclude, the clarification request. +216/-1 |
| `jarvis/runtime/presentation_speech_gate.py` | `situation=` passthrough and one shared retention path. +22/-1 |
| `jarvis/runtime/interaction_mode_observer.py` | `add_listener`, the Voice twin of Slice 04's Core-side seam. +34 |
| `jarvis/runtime/claude_local.py` | the fourth execution profile and its tool allow-list. +105/-9 |
| `jarvis/runtime/prompt_catalog.py`, `control_center.py` | the new system prompt, declared and editable. +12 |

`voice_v2.py` keeps accepting Slice 05's `presentation_audio=` alongside the new
`presentation=`: that parameter has its own tests, and removing it would have
been a rollback wearing the clothes of a wiring change.

---

## 2. In-process or relay - the decision, and its evidence

Slice 06 shipped `PresentationObservationSink` as a **synchronous** `Protocol`
and wrote the warning down while the choice was free: a cross-process relay
behind a synchronous Protocol is blocking IO on the Voice event loop, the loop
that also carries the explicit-address lane, which D04 says ambient work may
never delay. It called the "one-line substitution" framing false for the relay
branch.

**Decision: in-process, in Voice.** Two arguments, one structural and one
measured.

### The structural argument, which settles it on its own

`PresentationAddressedTurnService.open()` is synchronous **by AST guard** -
Slice 10 ships a test that fails by name if an `await` appears in `arm()` or
`open()` - and it reads `store.snapshot` inside that frame. A relayed store
makes that read blocking, and there is no repair that keeps the guard. The same
holds for `claims_reader`, which the preparation runner calls to offer claims.

A relay would also have to be **invented**: there is no `/v1/presentation/*`
surface, and Slice 06 explicitly declined to add one because a cross-process
surface carries its own latency budget.

### The measured argument

`scratchpad/s11_relay_bench.py` runs the real `AmbientIngestionLane`, the real
`AudioCaptureHub`, the real segmenter and the real store three ways, while a
5 ms heartbeat task measures how late the event loop is - which is exactly what
every other task on it, including trigger delivery, feels. A manual key is
pressed six times **during** the ambient load.

| Scenario | loop lag max | loop lag p95 | **trigger max** | trigger median | sink calls | sink failures | utterances filed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **A. in-process** (what ships) | 30.5 ms | 14.8 ms | **1.96 ms** | 1.42 ms | 0 | 0 | 6 |
| **B. relay, Core up** (~2 ms per call) | 71.2 ms | 26.2 ms | **67.98 ms** | 27.49 ms | 24 | 0 | 6 |
| **C. relay, Core unreachable** | **8 032.9 ms** | 17.0 ms | **6 029.9 ms** | 0.20 ms | 4 | 4 | 1 |

Read the **trigger max** column. It is the number D04 is about: how long the
user waited between pressing the key and the lane delivering the trigger, while
the room was being transcribed.

- **A vs B.** A healthy relay, answering in 2 ms, turns a 1.4 ms median into
  27 ms and a worst case of 68 ms - a **35x** median penalty for a sink that is
  doing nothing wrong. `_analyse` calls `apply()` up to fourteen times per
  utterance with no `await` between them, so the penalty is per-utterance, not
  per-call.
- **C is the one that settles it.** With Core unreachable, one blocking call
  held the event loop for **8 seconds**, and the press that landed inside that
  window was served **6 seconds late**. Not "slower": a Presentation that
  appears to have stopped listening, because the loop that carries the trigger
  was inside a socket call. The median in C is *low* (0.20 ms) precisely
  because the lane went deaf after three failures and stopped calling the sink -
  which is the lane's failure policy working, and which is also why a median is
  the wrong statistic here. Only one utterance was filed at all.
- **A is not free either**, and saying so keeps the comparison honest: 30.5 ms
  of worst-case loop lag comes from the segmenter's per-frame energy arithmetic
  and from GC. But it never reaches the trigger, because nothing on that path
  blocks.

The measurement matches the structural argument rather than replacing it. The
structural one alone would be enough; this is what it looks like in
milliseconds.

*Caveat, stated:* scenario C used a loopback address with nothing listening, on
Windows, with `urlopen(timeout=2.0)`. The 8 s stall is what this machine did;
another host will produce a different number. The **shape** - a synchronous
socket call on the loop that carries the trigger - is what transfers.

### The consequence, recorded rather than tidied away

`V2App.presentation_working_set` (`jarvis/core/v2_app.py:86`) stays in Core with
**no producer**. Its only wiring remains the mode-change retirement Slice 04
built. Two stores now exist and exactly one is fed. Removing the Core one is a
rollback of Slice 04 with its own test surface, and doing it inside a rollout
slice would be scope creep; the asymmetry is instead written into
`docs/ARCHITECTURE.md`, `docs/interaction-mode.md`,
`docs/presentation-ambient-lane.md` §7 and the module header.

---

## 3. The `--tools ""` question, answered

Slice 08 found that `back_brain`'s `speculative_analysis` profile launches the
CLI with `--tools ""` (`jarvis/runtime/claude_local.py`), which is right for
re-reading a transcript and wrong for D07's research, and left the question here
with one instruction: do not widen the profile without checking who else
consumes it.

### Who consumes it

- `jarvis/runtime/back_brain_worker.py:66` - chosen for **every** job whose
  scope is `speculative_analysis`;
- `jarvis/runtime/live_delegation.py:162` - the Duplex `brain_orchestration=false`
  path, whose own docstring reads *"Legacy `brain_orchestration=false` path:
  speculative analysis, no tools."*

### Why it is not widened

1. those two expect zero tools, and neither asked to change;
2. its system prompt says, in as many words, *"Do not execute actions, retrieve
   external data, invoke tools"* - widening the argument would have handed tools
   to a model instructed not to use them;
3. **decisive**: that path is *durable*. A `speculative_analysis` job is a row in
   the back-brain SQLite state and survives a restart, which is exactly what D13
   forbids a Presentation preparation. Slice 08 corrected its own report on this
   point and called it "the strongest argument, the one not made".

### What was built instead

A **fourth execution profile**, `presentation_preparation`. It keeps every
hardening of the restricted profile - `--restricted --strict-mcp-config
--safe-mode --no-chrome --disable-slash-commands --permission-prompts none
--no-session-persistence`, no routing hook, no MCP config, no resumed session,
`--system-prompt` rather than `--append-system-prompt`, native argv only - and
differs in **two** arguments: `--tools`, comma-joined from
`SpeculativeGrant.allowed_tools`, and the `--system-prompt` it carries - the
speculative one spends its text forbidding tool use, which is right for
re-reading a transcript and wrong for research. ("Exactly one" was loose; the
code comment had it right and this section did not.)

**And neither restricted profile copies its input into the trace** - the change
section 6 explains, and the one that made the privacy claim of this report true
rather than aspirational.

The CLI's own help was read rather than assumed:

```
--tools <tools...>   Specify the list of available tools from the built-in set.
                     Use "" to disable all tools, "default" to use all tools,
                     or specify tool names (e.g. "Bash,Edit,Read").
--restricted         Restricted mode: removes the built-in tools that run
                     commands or code (Bash, PowerShell, REPL ...) and WebFetch
                     unless --tools names them, ...
```

Two consequences read straight off that text, and both are handled:

- `--tools` names only **built-in** tools. `memory_search`, `scene_inspect`,
  `scene_query`, `scene_get` and `scene_create_object` are MCP tools, and a
  restricted profile mounts no MCP server. They are withheld, and the
  withholding is journalled by name (`presentation_preparation_tools_unavailable`)
  rather than silently dropped;
- naming a tool under `--restricted` can **re-add** it: that is how `WebFetch`
  comes back, which D07's web watch needs. So a second allow-list lives at the
  process boundary itself - `CLI_GRANTABLE_TOOLS = {Read, Glob, Grep, WebSearch,
  WebFetch}` - and a name outside it raises at **construction**, before an argv
  exists. A test drives `Bash`, `Edit`, `Write`, `memory_search` and
  `scene_create_object` through that door and gets a refusal for each.

The argv is asserted on what is actually built, with
`asyncio.create_subprocess_exec` intercepted; no `claude` process is launched by
any test. A sibling test pins that `speculative_analysis` **still** sends
`--tools ""`, so "widening it would change its consumers" is a statement a
regression can falsify.

Accepted V1 cost, written here so it is not discovered in use: a preparation
reads the web and the files; it cannot search the canonical memory and cannot
read the scene. Staging a hidden object is unaffected - the *service* stages,
from what the runner returns, and the runner never asks for it.

### The hole this opened onto, which nothing else would have found

`decide_attention` (Slice 09) refuses a verdict whose evidence names a source the
working set does not hold: *"a runner that invents a source does not pass."*
Nothing in the repository ever constructed a `PresentationSource`. The set of
known sources was therefore **always empty**, so every contradiction would have
been refused as `attention_provenance_unknown` - and no test saw it, because
nothing joined the chain end to end.

The runner closes it in the only direction that keeps the guarantee: it
**records the source** in the working set and then cites that record's
identifier. The model never chooses an identifier - it sees locators only - and
claim ids are *given* to it, with any id outside the offered list refused before
the judge. The full chain is exercised in one test and, separately, on a real
trace (section 5).


---

## 4. The architecture matrix

Slice 07 shipped a Presentation that was **mute on all three typed
architectures** because it had been exercised against the legacy one only. That
is the defect this section exists to not repeat.

The repository produces five readings of "which architecture am I" -
`voice_arch` legacy / continuous_brain, and typed SIMPLE / FRONT_BRAIN / DUPLEX.
`test_la_matrice_des_architectures` and its D14 twin are **parametrised over all
five**, on a real `PersistentVoiceRuntime` built the way `jarvis/app.py` builds
it, with the production precondition wired.

| Architecture | `continuous` | Addressed turn can open | PRESENTATION takes the mic | No shared capture in SIMPLE | Result |
| --- | --- | --- | --- | --- | --- |
| `legacy` (`voice_arch`) | **no** | **no** | **refused, by name** | yes | **BLOCKED, loudly** |
| `continuous_brain` (`voice_arch`) | yes | yes | yes | yes | **PASS** |
| `SIMPLE` (typed) | yes | yes | yes | yes | **PASS** |
| `FRONT_BRAIN` (typed) | yes | yes | yes | yes | **PASS** |
| `DUPLEX` (typed) | yes | yes | yes | yes | **PASS** |

**The `legacy` row read "yes" in the first version of this table, and it was
false.** `PersistentVoiceRuntime` builds a `SpeechScheduler` only when
`continuous`, and `continuous` is false for `legacy`; the bridge therefore
receives `on_addressed_turn=None` and the addressed turn never opens. Entering
PRESENTATION there opened the room microphone, ran the ambient lane and the
speculative pool, and left the user with no way to be served - *silently making
Presentation architecture-specific*, which SLICE.md forbids, and the Slice 07
shape this slice was told not to repeat.

PRESENTATION now **refuses to enter** on a non-continuous architecture, before
touching the microphone, under `presentation_architecture_unsupported`, with a
message naming the setting to change. A refused entry leaves the SIMPLE wake
stack untouched - a separate test, because a refusal that breaks what it
protects is not a refusal.

**And the matrix that should have caught this was decorative.** Both tests drove
`presentation_session()`, `_shared_input_source()` and `presentation_turns()`,
none of which reads `voice_arch` or `conversation_architecture`: five rows
differing only in a field the driven path ignored - two tests run five times.
The matrix now carries `continuous` as a column, asserts it per row, and asserts
the refusal on the row that needs it. Probed: removing the guard fails exactly
the `legacy` row and the wake-stack test, and leaves the other four green.

Why it holds by construction rather than by luck: everything this slice adds
hangs off two seams that are architecture-blind.

- **The microphone.** `PersistentVoiceRuntime._shared_input_source()` is
  consulted once per activation, before the bridge is built, on every path. It
  has no branch on `voice_arch` and none on `conversation_architecture`.
- **The addressed turn.** `SpeechScheduler.note_addressed_turn` is reached from
  `realtime_audio._note_addressed_turn`, which both the typed branch
  (`:4531`, from `accepted.source.correlation_id`) and the brain branch
  (`:4567`, from `_last_correlation_id`) call. Slice 07's repair made that seam
  universal; this slice inherits it rather than adding a second one.

Two **named blockers**, which are configuration facts rather than architecture
facts - they follow the *stack* and the *agent CLI*. **Reachability, corrected:**
blocker (a) is reachable on `legacy` **only**, because `voice_composition.py`
pins all three typed architectures to the OpenAI adapter and `jarvis/app.py`
already refuses Gemini Live on `continuous_brain`. "They can occur on any of the
five rows" was false on four of five. Blocker (b) follows the agent CLI setting
and is reachable everywhere. Both are said **once, at the first entry into
PRESENTATION**, not at Voice startup:

| Blocker | Effect | Said where |
| --- | --- | --- |
| voice stack is not OpenAI (Gemini Live) | no ambient transcription. PRESENTATION takes the microphone and answers explicit address; the lane is built with a transcriber that raises, so it becomes **deaf** and says so in `stats()` and in the journal, instead of not existing | `presentation.runtime.transcription_unavailable` at start; `ambient_deaf` in every diagnostics line |
| agent CLI is not Claude (Codex) | no speculative preparation. `--tools` and the restricted profile are Claude CLI arguments; `back_brain_worker` already refuses the speculative scope for the same reason | `presentation.runtime.runner_unavailable` at start |

One architecture-level refusal is inherited, not introduced: Gemini Live already
refuses `continuous_brain` at startup (`jarvis/app.py`), which predates this
slice.

**Not claimed:** no architecture was exercised against a real provider, a real
microphone or a real CLI. The matrix is over live objects built by the
production composition path, with the outer boundaries faked. Section 12 says
what a human must still do.

---

## 5. Agent-trace evidence

Asserted behaviour is not trace evidence, so this section is built from a real
`runtime/trace.jsonl` produced by driving the composed stack, not from tests.

**Source.** `scratchpad/s11_trace_scenario.py` fills the same
`PresentationComposition` dataclass `jarvis/app.py` fills, writes to a real
`RuntimeJournal` under a temporary runtime root, and runs one session:
SIMPLE -> PRESENTATION -> the room talks -> a checkable claim -> an explicit
address -> back to SIMPLE.

**Real:** every module of Slices 04-11, the capture hub and its supervisor, the
segmenter, the explicit-address lane, the working-set store, the speculative
pool and its capability table, the preparation runner and its parser, the
attention judge, the addressed-turn service, and the journal.
**Faked, at the outer boundary only:** the PortAudio device, the transcription
provider, the Claude CLI process (the runner around it is real and parses a real
answer), and the scene transport.

### Execution path, in the order the trace records it

```
audio.capture_hub.opened            process_input_streams=1
explicit_address.started
presentation.audio.started
presentation.working_set.bound
presentation.speculative.bound
audio.capture_hub.subscribed        ambient_ingestion, queued
presentation.ambient.started
presentation.runtime.entered        physical_input_owners=1
  presentation.ambient.segmented  x2
  presentation.tail.observed      x2      <- D06: the tail before any analysis
  presentation.ambient.transcribed x2
  presentation.working_set.applied x17
  presentation.ambient.analysed   x2
  presentation.speculative.admitted x7
  presentation.preparation.tools_withheld x1  (warning, once)
  presentation.preparation.started x7        tools=[Glob,Grep,Read,WebFetch,WebSearch]
  presentation.preparation.prepared x7
  presentation.attention.raised   x2        (warning) contradiction / warning
  presentation.speculative.prepared x5
presentation.runtime.diagnostics             the periodic reading
explicit_address.admitted
presentation.addressed.armed
presentation.addressed.latency  x2           admission, then visible
presentation.addressed.opened
presentation.addressed.reused                addressed_resource_reused
presentation.addressed.settled
audio.capture_hub.unsubscribed / ambient.stopped / speculative.retired
explicit_address.closed / capture_hub.closed / audio.stopped
presentation.working_set.retired
presentation.runtime.left            physical_input_owners=0
```

**80 lines, 77 at `info`, 3 at `warning`, 0 at `error`.**

### The four behaviours SLICE.md asks for

| Behaviour | Trace evidence |
| --- | --- |
| **ambient delegation** | `presentation.speculative.admitted` x7 from two room utterances, then `presentation.preparation.started` with `origin: "ambient"`, `priority: 2`, and the exact tool list that reached the CLI |
| **fact-check** | `presentation.attention.raised` at `warning`, `category: contradiction`, `severity: warning`, `confidence: 0.92`, `source_count: 1`, with an `evidence[0].source_id` that **is** in the working set's sources - the provenance chain of section 3 |
| **resource reuse** | `plan.action=show_prepared`, verdict `reusable / addressed_resource_anchored_to_referent`, then `presentation.addressed.reused` with `code: addressed_resource_reused`. Nothing was re-prepared |
| **priority** | `presentation.addressed.latency` with an **admission of 2.0-3.5 ms** across runs, measured while seven speculative jobs had been admitted |

### Findings, in the `agent-trace-analysis` vocabulary

**MAJOR - fixed in this slice.** `presentation.preparation.tools_withheld` was
emitted at `warning` **once per job**: seven identical warnings for two
sentences heard. The withholding is *structural* - every grant carrying
`RESEARCH_SEARCH` carries `memory_search` - so it is now said once per distinct
tool set (bounded at four by `DISTINCT_TOOL_SETS`) and only the count keeps
rising in `stats()`. A trace nobody can read says nothing; Slice 02 paid this
same lesson at one warning per second.

**FLAGGED - a rollout cost, not a defect.** One utterance produced **four**
speculative jobs (`MAX_TRIGGERS_PER_UTTERANCE = 4`), and each job is one
`claude` CLI process. With `MAX_SPECULATIVE_POOL = 8` and
`RESERVED_EXPLICIT_SLOTS = 2`, up to **six restricted sub-agents run
concurrently**, each with a 60 s budget. That is Slice 08's design working as
specified - speculative work is sacrificial and the pool is the bound - but on a
workstation that is often under 2 GB free it is a real number, and it belongs in
the operator's hands rather than in a surprise. It is in `docs/OPERATIONS.md`
and in section 11. **Not changed here**: the pool is Slice 08's mechanism, and
picking a different number without measuring a real CLI would be a guess.

**FLAGGED - honest limit of the scenario.** The hub's supervisor reaps a device
that stops delivering blocks after `DEFAULT_SILENCE_TIMEOUT_S = 2.5`. The first
run of this scenario stopped feeding PCM during a wait and recorded
`physical_input_owners: 0` - correct behaviour, wrong measurement. The scenario
now keeps a "breathing" feed running, as a real microphone does. Worth keeping
because it is the shape of a false negative a future harness would hit.

**No BLOCKER, no hidden retry, no unnecessary tool call.** Every preparation ran
once; there is no retry line, no fallback line, no error line in the whole
session.

**Missing trace evidence, stated:** no line in this trace came from a real
microphone, a real transcription provider, a real Claude process or a real
scene. Latency numbers here are in-process admission numbers and say nothing
about a provider.

---

## 6. Privacy review

Four questions, each answered with evidence rather than with a policy sentence.

### Is raw audio persisted anywhere?

No. The capture path keeps PCM in memory: the hub fans bounded copies to
subscribers, the segmenter holds a bounded window, and the WAV handed to the
transcription port is built in memory (`pcm16_to_wav`, Slice 06). Nothing on
this path opens a file. The working set refuses non-`str` text at its door -
`store.observe(..., b"\x00\x01\x02\x03")` returns
`REJECTED / presentation_tail_entry_invalid` and the tail stays empty, which is
a test.

### Can the room's speech reach a durable sink?

**It could, and this slice was the producer.** This section said "not through
this slice" and was wrong, in the way this task punishes most: the test that
said so used a scripted sub-agent with **no journal at all**, so it reached the
guard's code and never the state the guard exists for. Tenth occurrence, and the
clearest, because the double chosen could not fail.

`ClaudeLocalAgent.send()` echoes its whole input under `agent.input`, unclipped,
so the message this slice builds - `Heard in the room: <phrase>` - landed in
`runtime/trace.jsonl`: append-only, no rotation, already 23.9 MB on this
machine, and not covered by `log_content`, which gates a different journal.
With `FACT_VERIFICATION` granted, whole `PresentationClaim.statement` sentences
went with it.

**Closed at the CLI, for both restricted profiles.** The echo exists so the
debug console can show the question beside the answer; a restricted profile has
no console - no `--chrome`, no MCP, no persisted session - so the echo has no
reader there, while its input is a room's speech (`presentation_preparation`) or
a provisional transcript (`speculative_analysis`). It is withheld, and a
profile, a length and a code take its place. The ordinary profiles are
untouched, which a control test pins.

Now the original claim holds, and three tests hold it: one drives the **real**
`ClaudeLocalAgent` with a real `RuntimeJournal` to the exact line that leaked;
one proves the debug console keeps its echo; one covers the historical profile.
The planted-phrase test still runs alongside, and the same search over the
80-line scenario trace of section 5 returns zero.

`to_brain_context()` is never called by this slice, so "never into a journal"
holds by absence of a call rather than by discipline.

### What is the working set's lifecycle?

In memory, bounded, session-scoped, and retired on three different paths, all of
which end in `store.retire(reason)`:

- the mode stops being PRESENTATION -> `PresentationCoordinator._leave`;
- the session is stopped for any reason -> `PresentationStack._teardown`, where
  the retirement sits **outside** the loop that stops the other parts, so a
  refusing ambient lane or a stuck microphone cannot keep the room's speech
  alive;
- the Voice process closes -> `PersistentVoiceRuntime.close()` closes the
  coordinator **before** `mute()`.

A test drives a real utterance into the tail, stops the session, and asserts the
snapshot's `session_id`, tail entries and topics are all empty afterwards.

### What does PRESENTATION write to disk?

**Two places, not one** - and the first version of this section said one, which
was true only because the second path was dead (see limitation 5).

1. `runtime/presentation-staged-objects.json`, holding scene object
   **identifiers** and nothing else - no text, no title, no speech. It exists so
   that objects staged before an unclean stop can be archived on the next start,
   which is the opposite of persisting a preparation. A corrupt file is said at
   `error` under its own code rather than read as "nothing to reclaim"; the
   difference between *nothing to reclaim* and *we no longer know what to
   reclaim* is the kind of silence this task keeps punishing. An overflow is
   said too, because losing an identifier is the asymmetric risk while a double
   reclamation costs nothing.
2. **The scene itself** (`data/state/scene.sqlite3`). A staged object carries a
   `title` and a `summary` produced by the sub-agent - a model that read the
   room, so these are not identifiers. They are bounded, hidden until something
   reveals them, and **reclaimed** three ways: `retire()` at the end of the
   session, the ledger at the next entry, and `reclaim_orphans()` at the next
   Voice start. D13 holds here by reclamation, not by absence of writing, and
   saying otherwise would have been the same mistake Slice 08 made when it
   called a durable `INSERT` ephemeral.

Also relevant, and **not** fixed here: `jarvis/runtime/realtime_audio.py` emits
`voice.transcript_dropped` with `text[:300]`. Slice 06 flagged it as a candidate
Issue. It predates this feature, it is on the Realtime path, and PRESENTATION
does not add a second such site - but it means "no transcript text in any trace
line" is true of the ambient lane and of this slice, not of the repository.

---

## 7. Diagnostics

`presentation.runtime.diagnostics`, emitted every 30 s while a session lives and
returned by `PresentationStack.stats()` so a test reads the same numbers an
operator does - one calculation, two readers.

| SLICE.md asks for | Field | Read from |
| --- | --- | --- |
| queue lag | `segments_pending` / `segment_queue`, `analysis_pending` / `analysis_queue` | `AmbientIngestionLane.stats()` |
| backlog | `enrichment_lag_s`, `enrichment_lag_entries` | the Slice 04 snapshot - how far the analysis is behind the speech |
| speculative jobs in flight | `speculative_in_flight`, `speculative_free_explicit_slots`, `speculative_staged` | `PresentationSpeculativeService.stats()` |
| trigger latency | `trigger_latency_s`, `trigger_stale_deliveries`, `triggers_pending` | `ExplicitAddressLane.stats()` |
| (added) the counted invariant | `physical_input_owners` | the ownership registry |
| (added) deafness | `ambient_deaf`, `ambient_degraded` | the lane's own state, so "no transcription" is readable rather than silent |

The **expected** path is logged, not only the failures: a healthy session writes
a reading every 30 s. Without it, an empty trace would mean both "fine" and
"dead". The loop runs only while a session lives, so SIMPLE writes nothing at
all.

The period is not an idle-noise problem: a one-hour presentation writes 120
lines. Slice 02 measured 0 lines/min for the idle mode path and that number is
unchanged - nothing here polls.

---

## 8. The deterministic slow-ambient fixture

SLICE.md asks for one. `test_une_voie_ambiante_saturee_ne_retarde_pas_le_declencheur_explicite`
is it, and its determinism is the point:

- the transcriber **never returns** until the test releases it. There is no
  delay to calibrate and therefore no race: the segment queue fills and stays
  filled;
- the backlog is **asserted before it is opposed** - `segments_pending >= 1` is
  checked *before* the key is pressed. Without that assertion this test would
  measure an idle lane and prove the opposite of its name. That is the failure
  shape this task has catalogued eight times, so it is guarded explicitly;
- after the addressed turn is admitted, the backlog is asserted **still there**:
  nothing drained it to let the turn through;
- the measurement is the service's own `admission_latency_ms`, which comes from
  the trigger's frozen stamp on the lane's clock.

Measured admission under that load: **under 250 ms is the assertion; observed
2-4 ms** across runs, consistent with Slice 10's own 3.6 ms against its saturated
backlog.

A second fixture guards the trap Slice 10 handed over: a controlled clock is
threaded through the whole composition, advanced by exactly 50 ms between the
key press and `open()`, and the latency must read 50.0. The first version of
that test asserted only `is not None` and a mutation walked straight through it -
`time.perf_counter` and `time.monotonic` sit close enough on this machine that
the skew guard never fires, so the service returned a **plausible and wrong**
number. Section 9 has the rest of that story.


---

## 9. Tests, mutations, and the exact commands

### The new suite

`tests/unit/test_presentation_integration.py`, **76 tests**, organised by the
thing they defend:

| Section | Tests | What it proves |
| --- | --- | --- |
| D14 | 3 | the router is transparent with no session; SIMPLE composes nothing; REUNION behaves like SIMPLE |
| one microphone | 3 | one owner before, during and after; a refused entry when a second stream exists; a fresh stack per entry |
| the explicit trigger | 2 | the typed trigger arms the turn and still yields a label; the clock is the lane's, to the millisecond |
| D04 under load | 2 | the deterministic slow-ambient fixture; the diagnostics reading |
| privacy | 3 | no room speech in the trace; nothing survives the retirement; no raw audio in the store |
| unclean shutdown | 3 | reclaimed at start; a corrupt ledger is said; inscribed then erased |
| `--tools` | 4 | the argv actually built; `speculative_analysis` unchanged; the allow-list refuses at construction; no code-running tool is grantable |
| the runner | 7 | MCP tools withheld and said **once**; no tools means no process; provenance recorded before it is cited; an invented claim id refused; an unreadable answer is not a failure; the sub-agent is always closed; a finding cannot self-stage |
| the addressed turn | 5 | one decision one truth; the clarification and its single possible kind; another kind says nothing; SIMPLE unchanged; a broken turn does not mute JARVIS |
| the matrix | 11 | five architectures x (PRESENTATION shares / SIMPLE does not), plus the live mode switch |
| the composition root | 2 | `jarvis/app.py` passes the router and the coordinator; it opens no session at startup |
| observer and shutdown | 3 | a failing listener does not stop the others; a stopped session is not served; a shutdown that goes wrong still gives the room microphone back |
| degradations | 4 | no scene, no wake key, no transcription (deaf **and says so**), no runner — each named, none silent |
| the Control Center card | 1 | a contradiction reaches the real background ledger through the real trace file |
| the real sub-agent (rework) | 3 | the production `ClaudeLocalAgent` does not copy room speech into the trace; the ordinary profile keeps its echo; the historical profile gets the same restraint |
| staging (rework) | 6 | an explicit token stages one object; ambient never does; the model cannot ask; the whole chain reaches the scene and the ledger; a screen-less reuse closes no visible measure, a real one does |
| the architecture blocker (rework) | 4 | the matrix carries `continuous` and asserts the refusal; a refusal touches no wake stack; a broken precondition is a no |
| hygiene (rework) | 7 | blockers are silent in SIMPLE and said once on entry; the absent runner complains once; an evicted source is not cited; the ledger says when it overflows; orphans are reclaimed at startup; a failed composition does not stop Voice |
| the wake router (rework) | 2 | suspend/resume never split across a switch; no iterator is leaked |

Twenty-two of the 76 are "X can never happen" header sentences turned into
cases - the Slice 04 rule.

### Mutations

Harness: `scratchpad/s11_mutate.py`. It carries every countermeasure this task
has accumulated: `git add -N` on the new files before trusting its own diff (the
sixth lie), bytes in and bytes out with each anchor joined by **that file's own
EOL** (the seventh - these sources are CRLF, Slice 04's store is LF), a printed
`git diff --stat` for every mutation, a refusal to start on a red baseline, a
restore in a `finally` with a byte-for-byte check, and `M00-CONTROL`, a
cosmetic comment change that **must survive**.

| Round | Mutations | Caught | Survivors | Control |
| --- | --- | --- | --- | --- |
| 1 | 32 | 28 | **3** (M09, M29, M31) | survived |
| 2 - the three again, with the control | 4 | 3 | **0** | survived |
| 3 - three new guards added after round 1 | 4 | 1 | **2** (M32, M34) | survived |
| 4 - those two again | 4 | 3 | **0** | survived |

Rounds 3 and 4 exist because three guards were written *after* round 1 - the
clock test, the failed-entry test, the shutdown-order test - and a guard that
has not been mutated is a guard nobody has checked.

The seventh lie bit me on my own patch scripts, twice, in exactly the shape the
LOG describes: an anchor written with CRLF against `jarvis/app.py`, which I had
normalised to LF minutes earlier, matched **nothing**. Both times the script's
own `assert count == 1` stopped it before it wrote. That assertion is the whole
value of the rule.

**All three survivors were test defects, not code defects** - the pattern this
task has now catalogued nine times, and all three are the same shape: *the
discriminating state was never constructed*.

- **M09** - give the lane `time.perf_counter` while the service keeps
  `time.monotonic`. My test asserted `admission_latency_ms is not None`. On this
  machine the two clocks sit close enough that Slice 10's skew guard never
  fires, so the service returned a **plausible and wrong** number - precisely
  the failure mode Slice 10 fixed by returning `None` instead of inventing
  `502.0 ms`. Replaced by a controlled clock threaded through the composition,
  advanced by exactly 50 ms, asserting 50.0.
- **M29** - make a failing mode listener re-raise. No test had two listeners, so
  "the loop continues" and "the loop stops" were indiscernible. Replaced by a
  test with a listener that raises **and** a listener that must still be called.
- **M31** - report a stopped session as live. Nothing read `coordinator.audio`
  after a session was stopped outside `_leave`, which is exactly what an
  emergency teardown does - and the consequence would be handing the bridge a
  closed hub. Replaced by a test that stops the stack directly.

Each of the three now fails **exactly one** test, so each is caught by the test
written for it rather than by a neighbour.

Round 3 produced two more survivors and one **bad mutation of my own**, which is
worth recording because it is the same family of self-deception:

- **M32** as first written moved the `presentation.aclose()` call two lines, to
  just after `mute()` and *still before* the two early returns. That changes
  nothing observable, so it survived - and a survivor that models no defect is
  not a test gap, it is a harness fault. Re-aimed at deleting the early call
  (which is what a reader moving it past the early returns effectively does):
  **caught**, by the test written for it.
- **M34** - keep the half-open stack after a failed entry - was a genuine gap.
  The test asserted `coordinator.audio is None`, which stays true anyway
  because the stack never started. What would actually be lost is the **retry**:
  a `_stack` left occupied means a second switch to PRESENTATION never
  rebuilds, so a microphone briefly taken by something else condemns the
  session until Voice restarts. The test now switches away and back, and
  asserts a second session is composed. **Caught.**

That is the ninth occurrence of the pattern in this task, and the second time
this slice produced it *in a test written specifically for the thing it missed*.

### The rework's own round

Seventeen mutations aimed at what the rework changed, because a guard written
after a mutation round is a guard nobody has checked.

| Mutation | What it models |
| --- | --- |
| R01 / R02 | the restricted echo comes back; only the new profile withholds |
| R03 - R06 | staging is not asked for / is granted to ambient / is decided by the model / is asked for every finding |
| R07 | a screen-less reuse closes the visible measure again |
| R08 / R09 | PRESENTATION takes the microphone on an architecture it cannot serve; a refusal is ignored |
| R10 | the brain-turn line claims a context again |
| R11 / R12 | the named blockers move back to startup; the absent runner complains per job |
| R13 | an evicted source is still cited as provenance |
| R14 / R15 | the ledger drops identifiers silently; orphans are no longer reclaimed at startup |
| R16 / R17 | suspend/resume resolve per call again; a switch leaks its iterator |

| Round | Mutations | Caught | Survivors | Control |
| --- | --- | --- | --- | --- |
| rework, first pass | 17 + control | 16 | **1** (R13) | survived |
| rework, second pass on R13 | 1 + control | 1 | **0** | survived |

**R13 was not a test gap - it was dead code of mine, and the mutation is what
found it.** The rework added a re-read of the snapshot after `store.apply()`,
against the eviction race QA described. It could never fire: the store
**refuses** a record it would immediately evict (`presentation_record_too_old`),
so the `applied` check above it already returned `None`. The test I wrote for it
passed for that reason, not for the reason it claimed.

The re-read is removed, and the race is stated instead: it lives *after* this
function returns - between recording a source and the judge reading it - so no
re-read here could close it, and the correct behaviour is the one already in
place, `attention_provenance_unknown`, refused by name. A lost alert, never an
invented provenance. R13 is re-aimed at the guard that is live.

That is the counterpart of the M32 lesson from the first rounds: a mutation that
survives is not automatically a test gap. It may be a bad mutation, or a guard
that nothing can reach - and the second is worse, because it reads as safety.

### Guard probes - applied, and selected

The rule is that a passing probe proves nothing until both are confirmed.

| Guard | Probe | Applied | Selected | Result |
| --- | --- | --- | --- | --- |
| Slice 07 `SPEECH_KIND_SITES` AST guard | a new `SpeechRequest(kind=kind)` site in `presentation_runtime.py` | `diff --stat` 1316 -> 1321 | `1 failed, 118 deselected` | fails, and **names the file**: `{'jarvis/runtime/presentation_runtime.py': ['kind']}` |
| speculative import-closure equality | `from jarvis.runtime.journal import RuntimeJournal` into `presentation_speculative.py` | `1 file changed, 1 insertion` | `1 failed, 88 deselected` | fails, printing `unexpected` |

Tree verified byte-for-byte restored after each.

### The Slice 08 carry-forward: denylist to allow-list

`test_le_service_speculatif_n_atteint_ni_le_back_brain_ni_le_registre_d_outils`
was a denylist. It now sits **beside**
`test_la_fermeture_du_service_speculatif_est_exactement_celle_qui_est_declaree`,
an equality over the 34-module `jarvis.*` closure. The denylist is kept
deliberately, for Slice 06's reason: when it fails, its *name* says what broke,
where an equality says only that a set moved. Third-party packages stay
unasserted - their exact set varies by environment, which is why Slice 08
flagged this rather than declaring it done.

### Commands and counts

Regression, run in eight foreground chunks because
`scripts/verify_release.py` as a single process is killed by this machine's
memory reaper:

```powershell
# chunk N of 8, over `ls tests/unit/*.py` in name order
.\.venv\Scripts\python.exe -m pytest -q <33 files>
```

| Chunk | Files (`ls tests/unit/*.py`, name order) | Passed | Failed | Which failures |
| --- | --- | ---: | ---: | --- |
| 1 | 1-33 | 751 | 2 | `test_barehands_interaction_js.py` x2 — **baseline** |
| 2 | 34-66 | 711 | 2 | `test_barehands_tutorial_retired_js.py` x1, `test_brain_delegation.py` x1 — **baseline** |
| 3 | 67-99 | 1004 (+1 skip) | 0 | |
| 4 | 100-132 | 939 (+1 skip) | 1 | `test_live_reaper_review.py::…nonstealable` — **a third flake**, see below |
| 5 | 133-165 | 1360 | 21 | the eight Scene files, name for name — **baseline** |
| 6 | 166-198 | 1377 | 0 | |
| 7 | 199-231 | 974 | 0 | |
| 8 | 232-264 | 966 | 0 | |
| **total** | **263 files** | **8082** | **26** | **25 baseline + 1 flake**, 2 skips |

**Re-measured after the rework**, over every suite that imports anything this
slice touches (77 files, the same set plus `presentation_addressed_turn`):
**2 720 passed, 13 failed in 2 min 26 s**. The 13 are the baseline subset
present in that file list, name for name — `test_scene_artifacts`(6),
`test_scene_capture`(1), `test_scene_query_tools`(2), `test_scene_settings`(2),
`test_barehands_tutorial_retired_js`(1), `test_brain_delegation`(1) — and they
are the **identical set**, test for test, that the same command produced before
the rework, when 2 560 passed. Nothing moved; the 160 extra passes are the new
tests.

The 25 of the full eight-chunk run are the declared baseline, name for name: `test_scene_artifacts`(6),
`test_scene_batch_tools`(3), `test_scene_capture`(1),
`test_scene_interaction_logic`(1), `test_scene_query_tools`(2),
`test_scene_service`(2), `test_scene_settings`(2),
`test_scene_transport_client`(4), `test_barehands_interaction_js`(2),
`test_barehands_tutorial_retired_js`(1), `test_brain_delegation`(1). Neither of
the two declared flakes reproduced.

**The 26th, and why it is a flake and not a regression.**
`test_live_reaper_review.py::test_running_recovery_attempt_keeps_its_lease_nonstealable`
failed once with a `TimeoutError` on a deadline assertion, inside a chunk that
took 5 min 12 s under load. Re-run alone: **31 passed in 4.34 s**. It imports
`jarvis.core.live_reaper`, `jarvis.core.live_lifecycle`,
`jarvis.domain.live_lifecycle`, `jarvis.ports.live_sideband` and
`jarvis.adapters.openai_live_sideband` — **none of which this slice touches**.
Same family as the two already on the baseline list: a stopwatch assertion that
loses under load.

### Evidence, committed

`s11_relay_bench.py`, `s11_trace_scenario.py`, `s11_mutate.py` and the 80-line
`s11_trace.jsonl` now live in
`tasks/jarvis-presentation-interaction-mode/slices/11-integration-rollout/evidence/`,
with a README saying what each proves and what it does not. They lived in the
session scratchpad, which is where a harness belongs while it is in use - but
three separate readers have now needed them to check a number in this report,
and one QA pass concluded the numbers were unreproducible after looking in a
different place. Nothing imports them and they are not collected by pytest.

### The release verifier

```powershell
.\.venv\Scripts\python.exe -m pytest -q <the eight chunks, above>   # its pytest step, run separately
.\.venv\Scripts\python.exe <the static gates, with subprocess.run stubbed for the pytest step>
```

Its seven static gates, run one by one:

| Gate | Result |
| --- | --- |
| no provider/runtime import in `jarvis/core` | **pass** |
| benchmark tooling allow-list points at real files | **pass** |
| benchmark tooling never imported by production | **pass** |
| no dangerous execution primitive in `jarvis/` | **FAIL - pre-existing** |
| no dangerous primitive in the benchmark tooling | **pass** |
| third-party runtime sources are pinned | **pass** |
| privacy logging disabled by default | **pass** |

**The failing gate is not this slice's.** `jarvis/runtime/barehands_replay.py:144`
contains `subprocess.run(` and is not in the verifier's two-file tooling
allow-list. Proven on **HEAD's own blobs**, before this branch: a scan of
`git ls-tree HEAD jarvis/` finds exactly that one hit. So
`scripts/verify_release.py` has been failing for some time, independently of
Presentation. Not fixed here: adding a file to a security allow-list is not a
rollout slice's call, and "not yours, do not fix" is this task's own rule.
Reported so agent 0 can decide.

Nothing this slice adds trips it: the preparation runner launches its sub-agent
through `asyncio.create_subprocess_exec`, the same primitive `claude_local.py`
already uses.

---

## 10. Where SLICE.md and the live repository disagreed

Stated, not resolved quietly.

1. **"Core also holds the session working set"** (`docs/ARCHITECTURE.md`, and
   the Slice 04 wiring in `jarvis/core/v2_app.py`). It cannot, for the reason in
   section 2: Slice 10's synchronous `open()` reads the store. The Core instance
   is left in place, unproduced, and the asymmetry is now written into four
   pages rather than corrected by a rollback. **Flagged for agent 0**: deciding
   whether Core's copy should be removed is a Slice 04 decision, not a rollout
   one.

2. **SLICE.md asks for the release verifier.** It fails on HEAD, for a reason
   unrelated to Presentation (section 9). Six of its seven static gates pass;
   the seventh has been failing since before this branch.

3. **SLICE.md's "restart reconciliation"** exists here as the staged-object
   ledger, which is a *narrower* thing than the phrase suggests. There is no
   session to reconcile after a restart - the working set is in memory and a new
   session starts empty, which is D13 working. What genuinely survives a restart
   is the scene objects, and those are what is reclaimed.

4. **"Scene unavailable degradation"** is inherited rather than built: with no
   `scene_tools_factory` the stager is `None`, the speculative service already
   counts `stage_unavailable` at `warning` (Slice 08), and the addressed turn
   already falls back from `SHOW_PREPARED` to `REFRESH` when a reveal is
   impossible (Slice 10). This slice adds the composition branch and the
   operator line, not new behaviour.

5. **"Wake unavailable / manual fallback"** likewise: without a Porcupine key
   the composition passes `wake_engine_factory=None`, `PresentationAudioSession.build`
   registers only the manual key, and `ExplicitAddressLane.live_sources` says so.
   Slice 05 built that; here it is only reached.

6. **`docs/02-architecture.md`**, cited by two contract pages, still does not
   exist under `docs/` - it lives in the handoff folder. Noted by Slice 08,
   partially corrected then, still true of `presentation-working-set.md`.
   Untouched: it is a citation defect in someone else's page.

---

## 11. Remaining limitations - the full list

Separately, as SLICE.md asks, and each one is a thing a reader could otherwise
assume works.

### Functional

1. **`ASK_BRAIN` does not carry the working-set projection.** `open()` computes
   `AddressedTurnContext`, and for `REFRESH` / `CLARIFY` / `SHOW_PREPARED` the
   plan is acted on - but on the `ASK_BRAIN` path the brain turn has **already
   been submitted** by the bridge when the classification happens (Slice 07 put
   it there deliberately), and `LocalCoreClient.submit_brain_turn` has no
   context parameter. Passing the projection would need either a new Core
   ingress - a cross-process surface with its own latency budget, which Slice 06
   declined for the same reason - or moving the classification ahead of
   submission on the continuous path, which touches the hottest branch in
   `realtime_audio.py`. **Consequence:** a knowledge question in PRESENTATION
   reaches the brain exactly as it does today; the brain does not learn that
   prepared material exists. Slice 10's `prepared_resources` projection is built
   and is currently read by nobody. **The `ASK_BRAIN` trace line no longer says
   otherwise**: it used to read "remis au cerveau *avec son contexte*", which
   this slice made reachable and therefore made false, in the very artefact the
   acceptance review is read from. It now carries `context_projected: false`.

2. **A named visual command is still not matched to a prepared resource.**
   Slice 10's stated gap, unchanged: `NOT_REQUESTED` says so, and a lexical
   name-matcher would be the second classifier this handoff spent three slices
   removing.

3. **No ambient transcription on a non-OpenAI stack**, and **no speculative
   preparation without the Claude CLI**. Both are named blockers, both said
   **once, at the first entry into PRESENTATION** (not at Voice startup, which
   would put two warnings per launch in the trace of an operator who stays in
   SIMPLE), and both readable in the diagnostics. Neither degrades in silence.

4. **A preparation cannot search the canonical memory or read the scene.**
   `memory_search` and the four scene tools are MCP tools; a restricted profile
   mounts no MCP server. The grant still names them, and the withholding is
   journalled once per tool set.

5. ~~**`DISPLAY_PREPARATION` has no production caller.**~~ **Closed in the
   rework, and it was worse than a limitation.** `stage_hidden=True` had no
   production writer at all, so no resource was ever a `ResourceKind.SCENE_OBJECT`,
   so `_show_prepared` always took the `else` branch and merely warmed the
   resource: **"montre-moi ça" changed nothing on screen** while the trace said
   `addressed_resource_reused` and the visible-latency measure was closed on it.
   Three claims of this report rested on that dead path without saying so.

   The runner now sets `stage_hidden` for the **first** finding of a job whose
   token carries `DISPLAY_PREPARATION` - which `REFRESH_CAPABILITIES` does, so
   an explicit refresh stages a visual, and an ambient job never can because the
   grant cannot even be constructed. One per job: the session budget is eight
   objects and four findings per job would fill it in two requests. The model is
   not consulted - a `stage_hidden` in its answer is ignored, and a test pins
   that.

   And the scheduler no longer claims a visible reaction for a reuse that drew
   nothing: the kind comes off the plan, a non-scene reuse is journalled
   `presentation_reuse_without_screen`, and the measure stays open. Both arms
   are tested, because "never measure anything" would have passed too.

### Operational

6. **Up to six restricted `claude` sub-agents run concurrently.** Four triggers
   per utterance (`MAX_TRIGGERS_PER_UTTERANCE`), a pool of eight with two
   reserved (`MAX_SPECULATIVE_POOL`, `RESERVED_EXPLICIT_SLOTS`), 60 s each. On a
   workstation often under 2 GB free that is a real load. The mechanism is
   Slice 08's and the bound is honoured; the number is now in
   `docs/OPERATIONS.md`, but **no real CLI was ever launched**, so the cost per
   process is unmeasured.

7. **Two global keyboard hooks exist while PRESENTATION runs.** The SIMPLE
   stack's `KeyboardWakeWordBackend` is suspended (`_enabled = False`) but its
   `pynput` listener keeps running, and the session builds its own. Only the
   enabled one queues, so behaviour is correct; the cost is one extra hook.
   Sharing the instance was rejected because `CompositeWakeWordBackend` keeps a
   pump task per child, and two consumers of one queue would lose every other
   press in silence.

8. **A mode change during a switch cancels a pending wake read.** The router
   cancels the in-flight `anext` on the old source, which closes that generator;
   a detection already dequeued at that instant is lost. It is one key press at
   the exact moment the operator changes mode, and the alternative - keeping two
   sources armed - is the duplicate-consumer defect above.

9. **The diagnostics period is fixed at 30 s** and is not a setting. A shorter
   period is a code change.

9bis. **A source can be evicted between being recorded and being judged.** The
   working set holds twelve sources; up to six preparations run at once and one
   utterance can produce four. A source recorded for a verdict may therefore be
   gone when `decide_attention` checks provenance, and the contradiction is
   refused as `attention_provenance_unknown`. That is the right direction to
   fail in - a lost alert, never an invented provenance - and it is not closed.
   A re-read inside `source_recorder` was tried and removed: the window is after
   that function returns, so the re-read was dead code, which a mutation proved.
   Closing it properly would mean the judge holding a reference rather than an
   id, which is Slice 09's shape to change.

### Operational, found in the rework

8bis. **Two durable sinks, not one.** Besides the id-only ledger, a staged
   object writes a `title` and a `summary` into `data/state/scene.sqlite3`, and
   those come from a model that read the room. They are bounded, hidden until
   asked for, and reclaimed three ways - end of session, next entry, next Voice
   start - so D13 holds by *reclamation*, not by absence of writing. Said in
   `docs/OPERATIONS.md` and in §13.

8ter. **`_presentation_composition` still runs at every Voice start**, in SIMPLE
   as in PRESENTATION. It opens no socket and starts no task, but it does
   construct the transcription adapter and resolve the agent settings. It is now
   wrapped: a raise yields `presentation=None`, an `error` line, and a Voice
   that starts exactly as before. What it no longer does is *journal* the named
   blockers at that moment - those wait for the first entry.

### Evidence

10. **No workstation validation of anything in this slice.** No microphone was
    opened, no speaker used, no wake word spoken, no transcription provider
    called, no `claude` process launched, no Core joined, no scene drawn. Every
    number in this report comes from live objects with the outer boundaries
    faked. Section 12 is the gate.

11. **The `argv` is asserted, the CLI's acceptance of it is not.** `--tools
    "Glob,Grep,Read,WebSearch"` is read off `claude --help` on this machine and
    built by the code; no process has consumed it. If the installed CLI rejects
    that spelling, every preparation fails at `start()` - which is loud
    (`presentation_preparation_start_failed`, at `error`) but unproven.

12. **The runner's answer contract is unproven against a real model.** A real
    Claude may not return the compact JSON object the prompt asks for. The
    parser is built for that - a prose answer counts as `unparsable` and yields
    an empty outcome rather than a failure - but the *rate* at which that
    happens is unknown, and an ambient lane whose preparations all come back
    empty looks exactly like one that is working quietly.

13. **`test_live_reaper_review.py::test_running_recovery_attempt_keeps_its_lease_nonstealable`
    failed once**, under a chunk that took 5 min 12 s, with a `TimeoutError` on a
    deadline assertion. It passes alone (31 passed in 4.34 s) and imports
    nothing this slice touches (`live_reaper`, `live_lifecycle`,
    `openai_live_sideband`). Recorded as a **third load flake**, in the same
    family as the two already on the baseline list - not as an inherited
    failure and not as a regression.

### Documentation

14. **`voice.transcript_dropped` still writes `text[:300]` to the trace**
    (`jarvis/runtime/realtime_audio.py`), on the Realtime path. Slice 06 raised
    it as a candidate Issue and it is now `Issues/002`. It means the repository
    as a whole does not hold "no transcript text in any trace line", even though
    this slice and the ambient lane do.

---

## 12. What the Human must do

Five checks are outstanding. **None is marked done here**, and none of them is
reachable without the physical workstation.

The full procedure is in `docs/ACCEPTANCE_STATUS.md`,
*Blocking workstation checklist for PRESENTATION*, twelve numbered steps. What
follows is what each outstanding check needs from it.

**Before anything: restart the stack.** `python -m jarvis core`,
`python -m jarvis control-center` and `python -m jarvis voice` must all be
started **from this commit**. A JARVIS started earlier contains none of this,
and will look exactly like a feature that does not work.

| Check | Owner slice | What it needs, minimally |
| --- | --- | --- |
| **`HV-PRES-E2E-01`** | 11 | the whole walkthrough: steps 1-12. It is the only check that spans the feature, and step 1 (SIMPLE unchanged) is the one to judge first |
| `HV-PRES-AUDIO-01` | 05 | step 11: wake word **and** manual key, with `physical_input_owners: 1` in the trace throughout. Slice 05 could not reach this because nothing constructed the session; it is reachable now |
| `HV-PRES-SPEECH-01` | 07 | step 10: steps 2-9 repeated **on every architecture you run**. Slice 07 shipped a mute Presentation on three of five because it was exercised against one |
| `HV-PRES-ALERT-01` | 09 | step 7: contradict a fact and watch for one card and one cue. **And answer the question Slice 09 left open on purpose:** the cue is the existing *failure* variant, so a contradiction currently sounds like an agent crashing. Should it be distinguishable? It is a one-line change and it has been waiting for this answer since Slice 09 |
| `HV-PRES-PRIORITY-01` | 10 | step 8: press the key while a preparation is obviously running, and judge whether the answer feels immediate. The machine measures 2-4 ms of admission; what a person feels is the part no test can reach |

Two things to record rather than judge, because they are the numbers nobody has:

- **how many `claude` processes actually appear** during a normal five minutes
  of talking, and what that does to the machine (limitation 6);
- **how often a preparation comes back empty** because the model answered in
  prose rather than JSON (limitation 12). `presentation.preparation.prepared`
  with `findings: 0` is the line to count.

And the standing instruction of this task, which applies to all five: **record
failures as failures.** A precise limitation is worth more than a claimed pass.

---

## 13. The two cross-slice proofs worth naming

Both are things previous slices could only *state*, and that wiring makes
checkable.

### The attention card is reachable, proven on the real path

Slice 09 built the floating card and the cue, then wrote: *"Not runnable until
Slice 11. Nothing constructs `PresentationAttentionService` or
`PresentationSpeculativeService` outside tests."* Confirmed independently three
times.

The path from judge to card is not a call - it is a **file**. The judge writes
`presentation.attention.raised` into `runtime/trace.jsonl`; the Control Center's
`BackgroundEventLedger` classifies that kind as `attention` and serves it in the
status digest, which is what the card and `bgCue` consume.

`test_une_contradiction_atteint_le_registre_d_arriere_plan_du_control_center`
drives the whole of it - real store, real source record, real judge, real
`RuntimeJournal`, real `TraceFollower`, real ledger - and reads back
`counts() == {"attention": 1}` with a digest whose `evidence[0].source_id` is
the record the working set holds. The same was re-read off the 80-line scenario
trace of section 5: **two** attention entries, both with verified provenance.

The digest is also where privacy gets its last check: it carries the locator and
the title and **not** the claim, so the phrase planted in the claim and in
`reason` is absent from the digest as well as from the trace.

### The staged-object ledger, and why this section used to be vacuous

An earlier version of this report claimed the ledger and its reclamation as
working behaviour. They were - in tests. In production the ledger was **always
empty**, because nothing ever set `stage_hidden=True` (see limitation 5). So
"exactly one file written" and "orphans are reclaimed" were both true only
because the path that would have written anything was dead.

Both are now load-bearing: an explicit refresh stages one hidden object, the
ledger records it, `retire()` reclaims it at the end of the session, and
`reclaim_orphans()` archives whatever an unclean stop left - **at Voice
startup**, not merely at the next entry into PRESENTATION, so an operator who
is killed mid-presentation and then stays in SIMPLE for weeks does not keep
ghost objects on screen. A test drives the whole chain against the real stager,
the real ledger file and a scene double; another proves the ledger says so when
it overflows, because losing an identifier is the asymmetric risk and double
reclamation is free.

### The microphone invariant is a number, on every path

Slice 05 made "exactly one owner" measurable and then could not measure it in
production, because nothing constructed the session. It is now read in four
places that a test asserts: before the switch (1, Porcupine's), during
PRESENTATION (1, the hub's), after leaving (1, Porcupine's again), and inside
every diagnostics line. The hostile case is constructed rather than described -
a SIMPLE stack whose `suspend()` raises, so the second stream is genuinely still
registered when the session tries to open - and activation **refuses**, with
`device.opens == 0`.

---

## 14. The rework, in one page

Five blocking defects, and three of them were the same shape a tenth time: **a
guard tested with a double that could not fail.**

| # | What it was | Where it is closed |
| --- | --- | --- |
| **B1** | room speech written verbatim into `trace.jsonl`; this slice supplied the producer, and the test that denied it used a journal-less double | §6, and `claude_local.py` for both restricted profiles |
| **B2** | `SHOW_PREPARED` could not show anything - no production writer for `stage_hidden` - while the trace claimed a reuse and a latency measure was closed on it | limitation 5, §13, and both the runner and the scheduler |
| **B3** | on `voice_arch=legacy`, PRESENTATION took the microphone and could never be addressed; the matrix that should have caught it was two tests run five times | §4 |
| **B4** | a trace line asserted a context this slice never delivered | `presentation_addressed_turn.py`, plus the first `ASK_BRAIN` test to exist |
| **B5** | the contract page re-asserted the sentence Slice 10 was reworked for | `docs/presentation-addressed-turn.md` |

Nine smaller items went with them: the operator-facing acceptance page now says
the verifier is not green and restates the matrix; the named blockers no longer
warn at every SIMPLE start; a composition failure can no longer stop `jarvis
voice`; `_AbsentRunner` no longer floods; a source the store refused is no
longer cited as provenance (the eviction race itself is **stated, not closed** -
see limitation 9bis, and the re-read that pretended to close it was removed
because a mutation proved it dead); the ledger says when it overflows and
orphans are reclaimed at Voice startup; the runbook's trace prefix is correct
and four differential rows were added; the second durable sink is named; and
three small router and wording defects are fixed.

**The three that were the recurring pattern.** B1's test substituted a
`ScriptedAgent` with no journal, so it searched a trace nothing had written to.
B2's absence was recorded as a limitation but never connected to the path it
killed, and no test drove a `SCENE_OBJECT` resource. B3's matrix parametrised a
field the driven code never read. In all three the guard's code ran and the
guard's state never existed - and in all three the repair was to build the state
first: the real agent, a real staged object, and `continuous` as a column.

## 15. Method notes worth carrying forward

- **The seventh lie caught me twice, on my own patch scripts.** Both times an
  anchor written with CRLF was applied to a file I had normalised to LF minutes
  earlier, and matched nothing. Both times the script's `assert count == 1`
  stopped it before writing. The rule "read and write bytes, join anchors with
  the file's own EOL" needs a companion: **assert the match count, always, even
  in a one-off fix script.** A patch script without that assertion is a
  mutation harness without a control.

- **EOL normalisation and a running mutation harness must not overlap.** I
  normalised line endings while round 1 was in flight. The harness restores from
  bytes it captured itself, so nothing was lost and the verdicts held - but it
  was the `one-implementer-per-worktree` hazard in a new costume, this time with
  myself as both writers. The tree was re-checked and re-normalised afterwards,
  and round 2 ran on a stable tree.

- **A scenario that stops feeding a fake device measures a lost device.** The
  capture hub reaps after `DEFAULT_SILENCE_TIMEOUT_S = 2.5`, correctly. The
  first trace run recorded `physical_input_owners: 0` and looked like a wiring
  bug; it was a harness bug. Any future scenario against this hub needs a
  "breathing" feed, because a real microphone never goes quiet.

- **A `warning` per job is a `warning` per sentence heard.** The trace, read as
  a trace rather than grepped for one line, showed seven identical warnings for
  two utterances. Reading the whole artefact found something no assertion was
  looking for. The rework found the same shape twice more - `_AbsentRunner`, and
  the named blockers emitted at every Voice start - which suggests it is worth
  asking of every new `warning`: *how often does the condition that produces
  this occur, and does it change?*

- **The choice of double decides what a test can prove.** B1 is the sharpest
  example this task has produced: `test_aucune_parole_de_la_salle_n_entre_dans_la_trace`
  searched the whole trace for a planted phrase, message fields included, and
  passed - against a sub-agent double with no journal at all. The assertion was
  right, the search was right, the subject could not fail. When a test's subject
  is a seam, **at least one test must drive the production implementation of
  that seam**, however awkward; otherwise the suite measures the double.

- **A limitation recorded is not a limitation connected.** B2's cause was in the
  limitation list ("`DISPLAY_PREPARATION` has no production caller") and its
  consequence was in three other sections claiming behaviour that the same
  absence made impossible. Writing a limitation down does not discharge the duty
  to ask what else it makes false.

- **A mutation that models no defect is a harness fault.** The first M32 moved a
  call without crossing the boundary it was meant to cross; it survived, and for
  a moment that looked like a test gap. A survivor is only evidence once the
  mutation is confirmed to break something real.
