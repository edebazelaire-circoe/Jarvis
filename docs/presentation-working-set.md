# Presentation session working set and transcript tail (contract)

Implementation: `jarvis/domain/presentation_working_set.py` (types, bounds, pure
eviction rules) and `jarvis/core/presentation_working_set.py` (the store).
Conformance: `tests/unit/test_presentation_working_set.py`.

This page covers **what Presentation remembers during one session** — and,
just as importantly, what it deliberately does not remember.

## Two things, on purpose

Ambient analysis lags. Speech does not. So Presentation keeps two separate
stores and one snapshot that carries both:

| | Working set | Transcript tail |
| --- | --- | --- |
| Holds | topics, entities, claims, sources, prepared resources, open questions, attention items | the last few utterances, as spoken |
| Written by | enrichment, once it has understood something | the ambient lane, the moment a transcript exists |
| Depends on enrichment | yes, by definition | **no** — that is the whole point |
| Lifetime | the session | the session, minus a 3-minute window |
| Read by | the priority lane, through the snapshot | the priority lane, through the same snapshot |

Decision **D06**: an explicit turn receives both. A deictic command
("montre-moi ça") resolved only against the working set would point at whatever
the analysis last finished, which may be thirty seconds behind the room. The
snapshot states the gap rather than hiding it, two ways, and both are measured
from `observed_sequence` — the highest utterance rank any committed record
cites:

- `enrichment_lag_entries` — how many tail utterances no committed record cites;
- `enrichment_lag_s` — the span of speech between the last utterance the working
  set cites and the newest one in the tail. When nothing has ever been enriched,
  the floor is the oldest utterance still in the tail, so a store that never
  started reports the **largest** lag, not zero.

Neither reading is derived from `committed_at`. The first version of
`enrichment_lag_s` was, and it lied twice: a never-enriched store reported
`0.0`, indistinguishable from fully caught up, and any record without provenance
— a source, an attention item, which deliberately do not advance
`observed_sequence` — reset it to zero without a single sentence having been
understood. `committed_at` only advances the age-budget clock.

## This is not memory

Decision **D13**. The working set is bounded, session-scoped, in memory only,
and nothing in it is ever appended to canonical memory automatically. A Core
restart starts from an empty store, exactly like `WorkStateStore`. Neither
module imports a repository, an adapter, a history store or `sqlite3` — an AST
guard in the conformance suite fails if one ever appears, and a behavioural test
rebuilds the store from scratch to show nothing comes back.

## Raw audio never enters

The repository already states the rule where the audio lives
(`jarvis/audio/duplex.py`, `jarvis/runtime/realtime_audio.py`: *raw audio is
memory-only and never persisted*). Here it is held by construction: every text
field goes through `check_text`, which refuses anything that is not a `str`, so
a PCM buffer (`bytes`, `bytearray`, `memoryview`) cannot be stored in any
record or tail entry. No field is named after audio either, and a test pins
that too.

## Prepared resources are references, never payloads

A `PreparedResource` carries a `ResourceReference`: a `ResourceKind`, a
`locator` (URL, path, document id, scene object id), a title, and optionally a
**safe structured descriptor** — a flat table of short keys to scalars or
bounded lists of scalars. That descriptor is the representation allowed for a
chart that exists nowhere else; it is data, not a program.

Two rules, on references only:

- `<` is refused in the locator, the title and every string of the descriptor
  (`presentation_resource_not_a_reference`). `>` is allowed, because
  `"marge > 10"` is a legitimate chart label;
- a locator may carry **no scheme at all** (a path, a bare id) or one from
  `ALLOWED_LOCATOR_SCHEMES` = `http`, `https`, `file`, `doc`, `chart`, `scene`,
  `dataset`, `note` — anything else is `presentation_resource_scheme_not_allowed`.
  An allowlist, not a denylist: the first version blocked `javascript:` and
  `data:text/html` by name and therefore let `vbscript:` and
  `data:image/svg+xml` straight through, and an SVG is a script carrier inside
  an `<object>` or an iframe. The resource kinds are closed, so the schemes they
  can carry are closed too. A scheme is at least two letters, so `C:\rapports`
  stays a Windows path.

**None of this applies to text that came from the room.** A claim, a topic or
entity label, a question, an attention reason carry only their size bound
(`bounded_text`). "La marge < 10 %" is an ordinary French sentence; refusing it
— with a code naming a *resource*, and by raising out of a constructor that
Slice 06 calls before `apply()` ever sees the record — was a contract break on
the most ordinary path there is. The tail's text is speech for the same reason:
`"si a < b alors"` is a thing a person says.

Displaying anything remains the scene's authority (D12). A `scene_object`
resource carries an id and nothing else.

## Resource temperature

`hot` / `warm` / `discardable`, and the effective value is **computed**, never
accumulated:

1. the resource's topic has left the working set → `discardable`;
2. it has not been used for more than `MAX_RESOURCE_IDLE_S` → `discardable`;
3. otherwise the declared temperature stands — `hot` right after
   `use_resource()`, `warm` when prepared.

Computing rather than cooling in steps makes the value independent of how many
times the store happened to be called in between: the same session gives the
same temperature, always.

## Bounds

Every collection has a count budget, every text a size budget, and the store
applies an age budget. All of them are module constants with their rationale in
the module header.

| Collection | Count | Eviction order (head goes first) |
| --- | ---: | --- |
| topics | 12 | least recently mentioned, then id |
| entities | 24 | least recently seen, then id |
| claims | 24 | least recently seen, then id |
| sources | 12 | least recently retrieved, then id |
| prepared resources | 16 | **temperature first** (`discardable` → `warm` → `hot`), then least recently used, then id |
| open questions | 12 | oldest, then id |
| attention items | 8 | oldest, then id |
| transcript tail | 16 entries / 4 000 chars / 180 s | oldest sequence |

An attention item's recency moves when it is re-raised, like every other merge:
a contradiction the analysis signals every thirty seconds is alive, and keeping
its first timestamp would have aged it out of the set while it was still being
raised, and sorted it oldest for eviction in the meantime.

Ages: a record older than `MAX_WORKING_SET_AGE_S` (30 min) since its last
mention leaves at the next commit; a tail entry older than `MAX_TAIL_AGE_S`
(180 s) leaves at the next utterance. Age is measured **from the newest known
speech**, not from a wall clock, so the rule is deterministic; `prune(now)`
exists for a store that stops hearing anything at all.

Two bounded memories back the rules up: `MAX_SEEN_OBSERVATIONS` (128) makes a
replayed observation a `duplicate` rather than a second mention, and
`MAX_RETIRED_RESOURCE_KEYS` (64) stops an evicted resource from being
resurrected by a preparation that finished too late.

Each `sort_key` ends with the record id, so two records sharing a timestamp are
evicted in a stable, reproducible order.

Inter-record references (`topic_id` on a claim, on a resource) are **soft**: a
topic that ages out does not delete the facts learned under it. It only makes
the resources prepared for it `discardable`.

`MAX_WORKING_SET_CHARS` (120 000) is a hard ceiling on the compact JSON form,
proving the "max count × max size" product is finite and known. It is not a
prompt budget — that belongs to the brain-turn projection (Slice 10), the way
`MAX_BRAIN_WORK_CONTEXT_CHARS` does for work.

The genuinely maximal working set — 64-character ids everywhere, full
`source_ids`, a maximal descriptor on all sixteen resources, a full attention
reason — measures **92 265** characters, and a test builds exactly that and
asserts it both constructs and fits. The first version of this ceiling was
80 000, *below* the real product, and the test that was supposed to prove it
safe built a half-maximal set. So the honest statement is now two statements:
the ceiling sits above the measured maximum, **and** hitting it anyway is a
typed `CAPACITY` refusal (`presentation_working_set_too_large`), never an
exception out of a public method. A bound believed unreachable is the one that
eventually gets reached.

## What an operation answers

The store reuses `VoiceStateDisposition` (`jarvis/core/voice_state.py`) rather
than declaring a second vocabulary for the same question:

| Disposition | When |
| --- | --- |
| `applied` | the store changed; the `code` says how (`..._added`, `..._coalesced`, `presentation_tail_appended`, `presentation_tail_revised`) |
| `duplicate` | the same `observation_id`, or the same tail revision, seen again |
| `ignored` | no session is bound, or nothing was there to change |
| `stale` | an older transcript revision, speech older than the window, a record older than the age budget, or a retired resource |
| `stale_session` | the observation belongs to a session that has been retired |
| `rejected` | the value is not a legal record (including a raw-audio buffer) |
| `capacity` | the collection is full and the incoming record is the one that would have been evicted — it is refused rather than accepted and dropped |

Coalescing **never rewrites provenance or `first_seen_at`**. A second mention
of a topic raises `mention_count` and `last_seen_at`; a verified claim keeps the
utterance that first stated it. So a claim still names its origin long after
that utterance has left the tail.

## Atomic snapshot

The store holds **one** reference, `self._snapshot`, a
`PresentationContextSnapshot` carrying both halves. Every operation builds a
whole new one and rebinds that single name; a refused operation rebinds nothing.
A reader can therefore never see this second's tail beside last second's working
set, and never a half-written state.

**And a refused call writes nothing at all** — not the snapshot, and not the
store's other memories either. The bounding computation is pure with respect to
the store: it returns the resource ids it *would* retire, and only the commit
path records them. The first version retired them while it was still deciding,
so a refusal left two marks: a resource still visible in the snapshot became
permanently unserviceable, and an id refused for capacity — never stored at all
— was banned for the rest of the session. The second would have hit Slice 08
first, since re-preparing after a capacity refusal is exactly what a speculative
lane does.

A record cannot be *observed* after it was *last seen*, either. That shape let a
refusal push the store's clock forward on the provenance and then fail the age
check on the recency, condemning whatever the advanced clock had just aged out.
It is refused at construction now.

**Every public method returns a typed `PresentationStateResult`**, including on
the char ceiling below. None of them lets a validation error escape. `authorizes_actions` is a `ClassVar` fixed
at `False`: a session snapshot is context, never an order (D03) — the same
stance as `VoiceConversationSnapshot`.

Discipline, as in `VoiceConversationState`: one owner, synchronous, atomic
between two `await`s, never called from a thread.

## Lifecycle

- `bind_session(id)` opens a session; binding a different one retires the
  previous session first, it never merges.
- `end_session()` retires it.
- `apply_interaction_mode(value)` reads the mode with
  `behaving_interaction_mode` — the *behaviour* reading, where a reserved
  `meeting` does not behave — and **retires everything the moment the effective
  mode is no longer PRESENTATION**. An unreadable value retires too: a store
  that cannot tell it is still in Presentation must not keep holding what was
  said in the room.
- Retiring clears both halves, forgets the session, forgets the seen-observation
  and retired-resource memories, **resets the utterance sequence to 1**, and
  raises `generation`. Nothing is copied anywhere and nothing crosses: a store
  whose contract is that nothing survives cannot keep a counter either.
- An observation bearing a retired session's id is answered `stale_session`; it
  cannot land in the next session.

The retirement is wired in `JarvisCoreApplication` through
`InteractionModeService.add_listener`, which notifies **synchronously** at the
moment the mode changes: after the new state is assigned (so a listener reads
the new value), outside the lock (so it cannot deadlock), and before the bus
event is published, with no `await` in between. A `/v1/events`
subscriber is the right way to *learn* a mode change; it is not the right way to
*stop holding* what was said in the room, because it would leave the session
alive for a round trip. A listener that raises is journalled and swallowed: a
state refusing to retire must not block the user leaving Presentation.

## Journal

Kinds: `presentation.working_set.{bound,retired,applied,refused,evicted}` and
`presentation.tail.{observed,refused}`. Lines carry counts, bounded ids and
stable codes — **never** speech, a label, a statement or a question's text.
Values copied into a line are clipped at `MAX_JOURNALLED_VALUE_CHARS` (64), the
same bound the Control Center uses. The expected path is journalled at `info`
alongside the refusals, so "nothing in the journal" cannot mean both "fine" and
"nothing is getting in".

## What this contract deliberately does not do

- **No producer.** Nothing writes to this store yet; Slice 06 owns the ambient
  lane that will.
- **No consumer.** Slices 08 and 10 read the snapshot and the prepared
  resources.
- **No priority field.** P0–P4 belongs to the speculative path (Slice 08) and
  never to canonical work items.
- **No UI.** Slice 09 presents attention items; `AttentionCategory` here is the
  minimal set this store needs and may be widened there.
- **No persistence, ever.** That is D13, not an omission.
