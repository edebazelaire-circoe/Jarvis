# Tencent MemoryCore adapter (memory handoff, Slice 06)

Optional, off by default. Tencent MemoryCore runs as a local sidecar; JARVIS asks it for one
extra ranked list and mirrors canonical notes to it. **The sidecar is derived, disposable state:
JARVIS starts, writes and recalls with it absent.** Authority rules are in [memory.md](memory.md);
the settings (`memory.tencent.enabled`, `memory.tencent.url`) in [settings/memory.md](settings/memory.md);
the runbook in [OPERATIONS.md](OPERATIONS.md#tencent-memorycore-sidecar).

Code: `jarvis/adapters/tencent_memory.py`. Tests: `tests/unit/test_tencent_memory_adapter.py`
(fake sidecar `tests/fakes/fake_tencent_sidecar.py`), `tests/integration/test_tencent_live.py` (opt-in).

## Upstream pin

| | |
|---|---|
| Upstream | `TencentCloud/TencentDB-Agent-Memory` |
| Commit evaluated | `0468a2a` (valid on GitHub, 2026-10-07; page shows branch `feat/server_team`, release v2.0.0) |
| Licence | MIT (`LICENSE` at the repository root) |
| Vendored | **Nothing.** No upstream code, no copied schema or prompt. JARVIS talks HTTP to a sidecar the user runs. |
| Evaluated | `MemoryCore/v3-api-memorycore-doc.md` at `0468a2a` (the "Memory Core v3 API"). Also exist upstream: Memory Knowledge v3, Memory Proxy v3 and Memory Panel. They are not used (see Out of scope). |

### API surface used (MemoryCore v3, as documented at `0468a2a`)

- Base `http://<host>:8420`; `Authorization: Bearer <KERNEL_AUTH_TOKEN>`; `GET /health` needs no auth.
- The data plane (`/v3/conversation|atomic|scenario|core/*`, `/v3/skill/*`, ...) also requires the header
  `x-tdai-service-id` (the instance id; upstream section 1.4). It is an identifier, not a secret.
  `x-tdai-user-key` belongs to the metadata plane (`/v3/meta/*`) and is not used.
- Every call is `POST` JSON and answers the envelope `{"code": 0, "message": "ok", "request_id": "...", "data": {...}}`.
  `code != 0` is a refusal (400 params, 401 auth, 403 ownership or isolation, 404, 409, 503 dependency).
- Identity: `team_id`, `agent_id`, `user_id` in the body (the doc also allows headers). "v3 enforces
  team + agent + user trio isolation; missing fields fall back to `default`."

| Use | Call | Fields JARVIS sends / reads |
|---|---|---|
| Mirror a note | `POST /v3/conversation/add` | `session_id` (required), `messages[{role: "user" or "assistant", content, timestamp}]` (1..100 messages, content 1..8 192 chars), identity trio. Reads `data.accepted_ids`. |
| Rank | `POST /v3/conversation/search` | `query` (1..2 048 chars), `limit` (max 100), identity trio. Reads `data.messages[].content` in rank order. The `score` is ignored: only the rank is used. |
| Unmirror / replace | `POST /v3/conversation/delete` | `message_ids` (max 5 000; or `session_ids`, max 100; `session_id` is deprecated), identity trio. HTTP 400 when neither is given. Reads nothing (`deleted_count`). |

### Why L0 conversation search, and how a hit maps back

The sidecar keeps **no caller metadata** and offers **no write with a caller id and no idempotency
key** (the doc says "absent" for all three). Atoms (L1) are produced by the sidecar's own extraction,
so their text is paraphrased and cannot be matched back. JARVIS therefore mirrors each note as one L0
message that starts with a marker and searches L0, which returns the stored text verbatim:

```text
[jarvis:<memory_id>:r<revision>]
<title>
<body, clipped to 8 192 chars>
```

A hit is read by that marker only, at the very start of the content (`\A\[jarvis:[A-Za-z0-9_.-]{1,64}:r\d+\]`; the id alphabet is the canonical one). No marker, a malformed id,
an id that is not a canonical note: the hit is **dropped**. The rest of the content is never used.

### Confirmed against the upstream doc, and still NOT verified (loud)

**Confirmed by re-reading `MemoryCore/v3-api-memorycore-doc.md` at `0468a2a` (rework of Slice 06):**
`conversation/delete` takes `message_ids` (max 5 000) or `session_ids` (max 100), not `ids` (the first
version of the adapter sent `ids`: wrong); the data plane needs `x-tdai-service-id` besides the bearer
token; the message role enum is `user | assistant`; `session_id` is required on `conversation/add`;
nothing in the doc mentions compression. The adapter and the fake sidecar follow these shapes, and the
fake answers HTTP 400 to the old one.

**Still unverified.** The doc was read through a summarising fetch, not on a running sidecar, and **no
real sidecar call has been made**. Unverified: that the identity trio in the body of `conversation/search`
filters as documented; that L0 search ranks a verbatim marker message well; that a fixed `session_id`
(`jarvis-memory-mirror`) holding thousands of messages is accepted; that `conversation/delete` accepts
message ids that were returned by `add` in the `accepted_ids` field; the response shape of `delete`
(only `deleted_count` is documented, nothing reads it); the real latency. `tests/integration/test_tencent_live.py`
is the check (revise then replace, agent isolation, add with role `user` and the fixed session): run it
once against a real sidecar before relying on the leg. If an assumption is wrong the failure mode is
degraded recall (`tencent_unavailable`), never wrong recall: the canonical re-resolution stands whatever
the sidecar returns.

## Contract

### Identity mapping and isolation

| Sidecar field | Value |
|---|---|
| `team_id` | a configured constant, default `jarvis` (`register_retriever(team=...)`) |
| `user_id` | the owner, default `owner` (`register_retriever(user=...)`) |
| `agent_id` | the agent id of the note (mirror) or of the `RecallQuery` (recall); `jarvis` when none |

Isolation is decided **by JARVIS on canonical data**, before and after the call. The sidecar's own
isolation is a second layer, never the first:

1. **Before**: `private` scopes never leave the machine, neither a note (mirror) nor the query text,
   unless `allow_private=True` is passed to `register_retriever` (default false; there is no setting
   for it, see Gaps). A query whose scopes are all private makes no call at all.
2. **After**: every hit is resolved on the canonical store and kept only if the note's scope is among
   the query's scopes **and** the note's agent bucket equals the query's agent bucket. A sidecar that
   leaks another agent or scope (test `wrong_identity`) cannot cross it. Superseded, out-of-validity,
   retention and level filters are re-checked on canonical too.

Consequence of the agent bucket: a `shared` note written by agent A is mirrored under A, so Tencent
ranks it only for A's queries. Other agents still find it through lexical and semantic recall.

### Authority

Tencent supplies ranks only. The snippet, title, level, retention, revision and `superseded` flag come
from the canonical store. A hit that does not resolve is dropped; the leg returns what resolves
(`why`: `tencent rank N`, `rank_sources.tencent`). The leg never writes canonical.

### Degradation and circuit breaker

- Every failure is a `LegDegraded`: a timeout gives `tencent_timeout`; transport error, non-200,
  non-JSON, wrong shape, `code != 0`, an answer over 512 KiB or a refused URL give `tencent_unavailable`.
  Lexical recall is untouched (`HybridRetriever`, Slice 03).
- The client times out at 90 % of the leg's slot (250 ms by default) so the failure is counted by the
  breaker instead of being cancelled by the hybrid.
- Whatever goes wrong in a call (a raising token callable, a hostile body) is a counted failure with our
  own sentence; a half-open trial can never stay claimed (a cancelled one is released with no outcome).
- The mirror has **its own client and breaker** (`registration.mirror_client`): a slow or failing mirror
  call never degrades recall, and a dead recall path never blocks the mirror's own bookkeeping.
- Canonical reads of the leg run on the leg's own bounded pool (`LegPool`, like lexical and semantic):
  a hung store call cannot starve Core's executor, and a busy leg reports `leg_busy`.
- **Breaker**: 3 consecutive failures (timeouts and malformed answers included) open it for 60 s. While
  open every call fails at once with no request. After 60 s one trial call is allowed: success closes
  it, failure re-opens it for 60 s. A success resets the count.
- A refused loopback connection can take longer than the slot on Windows: a dead sidecar may then show
  as `tencent_timeout` instead of `tencent_unavailable`. Both are degraded and both count.
- **No synchronous startup probe**; nothing runs at import or construction. Health is the
  `CapabilityReporter` (`capability_id = "tencent"`): `ok` until a call fails (it means "not known to
  fail"), `degraded: tencent_unavailable` after a failure or while the breaker is open, `unavailable:
  tencent_config_invalid` for a refused URL. The mirror reports as `tencent_mirror`
  (`degraded: tencent_mirror_behind` when writes wait or were dropped).

### Transport and secrets

- `httpx`, `follow_redirects=False`, `trust_env=False` (no proxy from the environment), `Accept-Encoding:
  identity`. Answers are read raw in a bounded stream (512 KiB); a `Content-Encoding` other than identity
  is refused without decoding (no compression bomb), a body that is not JSON (including a 200 KB `[[[[`)
  is a failure, and at most 100 hits are read.
- Headers: `Authorization: Bearer <token>` and, when `service_id` is configured, `x-tdai-service-id`.
- URL: `https`, or `http` on loopback only (`127.0.0.1`, `localhost`, `::1`); no credentials, query or
  fragment. Anything else is refused at registration and the leg never calls out.
- The token is `credentials.secret_for(settings, "tencent")` (API Keys page, env `JARVIS_TENCENT_TOKEN`),
  read on every call. It is sent as `Authorization: Bearer` and appears in no status, error, log line
  or ledger (test `test_the_token_never_appears_...`). Errors carry our own sentence (`sidecar answered
  HTTP 401`), never the response body or the URL. A token an HTTP header cannot carry (non-ASCII, blank
  inside, control characters, not a string) is refused before any network with a sentence that quotes no
  part of it.

### Mirror (`TencentMirrorSink`)

- `notify_written(memory_id)`: callable from any thread, never blocks, never raises. Core calls it after
  a canonical write; the canonical write never waits for, nor depends on, the mirror.
- A background task (`await registration.start()`) pushes, one batch at a time, never while a `resync`
  runs. A failed push is retried with a backoff (60 s, then doubling up to 8 intervals), also while
  other writes keep arriving, and by `resync`. At most 1 000 ids wait; beyond that a notification is
  dropped (loss-tolerant) and the status says so until a `resync` completes without failure.
- What is mirrored: notes that are not superseded and not `private` (unless allowed), every retention
  class and scope. Wiki, CodeGraph and Skills assets are not mirrored.
- The sidecar has no idempotency key, so a ledger (`MirrorLedger`, a small JSON file next to the memory
  root's derived indexes when `ledger_path` is given; derived, losing it only costs a re-push) records,
  per note, the digest pushed, the sidecar message ids and the agent bucket they were written to. A
  revised note is replaced (delete in the bucket where it was written, then add), never duplicated.
  One note is never pushed twice at once (per-note lock; the note is read under it). The ledger is
  written once per batch, in a thread, atomically (never on every set); a ledger with malformed content
  is ignored and rebuilt.
- `await sink.resync() -> ResyncReport(pushed, unchanged, removed, failed, stopped)`: makes the mirror
  equal canonical. Idempotent: a second run pushes and removes nothing. It stops early (`stopped =
  "circuit_open"`) when the breaker opens. Without a ledger file, a restart re-pushes everything (the
  retriever de-duplicates by `memory_id`, so the cost is sidecar storage only).

### Known limits of the mirror (not coded, by decision)

- **Crash between add and ledger write (P5).** The sidecar accepted a message and the process died before
  the ledger was flushed: that message is an orphan on the sidecar, unknown to JARVIS. The next resync
  pushes the note again; the orphan stays. It is harmless for recall (the retriever de-duplicates by
  `memory_id` and re-reads canonical) but it takes sidecar space and a stale text.
- **Lost ledger (P7).** A lost or reset ledger cannot remove what is already on the sidecar. Likewise, a
  note that moves from `shared` to `private` (or is superseded) is unmirrored by deleting its ledger
  ids; if the ledger lost them, the old text stays on the sidecar until it is deleted there. To reset
  cleanly, wipe the sidecar's own data and run `resync` (the runbook says so). Do not rely on the
  sidecar for erasure: canonical deletion and the privacy of old text are JARVIS-side.

## Entry point for Core's wiring

`jarvis/core/memory_wiring.py` (Slice 05) calls this and does nothing else Tencent-specific:

```python
from jarvis.adapters.tencent_memory import register_retriever, TencentRegistration

registration: TencentRegistration | None = register_retriever(
    tencent,            # TencentSettings: settings.memory.tencent
    credentials,        # Mapping[str, Any] | Callable[[], Mapping[str, Any]]: the credential settings
                        #   (secret_for(settings, "tencent")); a callable is re-read on every call
    store,              # NoteStore: get(memory_id) and list(MemoryFilters), the canonical store (synchronous)
    *,
    ledger_path=None,   # Path | None: <memory root>/.jarvis/tencent-mirror.json is the suggested value
    allow_private=False,  # bool: send private-scope notes and queries outward (default never)
    team="jarvis",      # str
    user="owner",       # str
    service_id="",      # str: the sidecar instance id, sent as `x-tdai-service-id` when not empty
    transport=None,     # httpx.AsyncBaseTransport | None: tests only
)
```

- Returns `None` when `tencent.enabled` is false: nothing is built, zero network.
- Otherwise: `registration.leg` (a `RecallLeg` named `tencent`, add it to `HybridRetriever([...])`),
  `registration.client` (recall) and `registration.mirror_client` (mirror), two clients with two breakers,
  `registration.sink` (call `sink.notify_written(memory_id)` after each canonical write; `None` when
  the URL was refused, and then `leg.status()` reports `unavailable: tencent_config_invalid`),
  `await registration.start()` once the event loop runs, `await registration.aclose()` at shutdown.
- A settings change of `memory.tencent.*` needs a new registration (close the old one first).
- Aggregate `registration.leg.status()` (`capability_id` `tencent`) and `registration.sink.status()`
  (`tencent_mirror`) in `/v1/memory/status`; when disabled the wiring reports `disabled` itself.

## Update policy

Upstream moves fast (35 commits on the evaluated branch, a release candidate line). Rules:

1. The pinned shape above is the contract. A change upstream is a deliberate update of this page, of
   the adapter and of the fake together, in one commit, after `test_tencent_live.py` passes against the
   new sidecar version. Never "float" to upstream's latest.
2. The adapter touches three paths and the envelope only; keep it that way. New upstream features are
   not adopted by default.
3. Record the commit evaluated here every time the pin is revisited.
4. If a future upstream change breaks the shape, the effect is degraded recall, and the switch to
   disable is `memory.tencent.enabled = false`: no data migration, nothing canonical depends on it.

## Out of scope

MemoryProxy (the front-door LLM proxy), vendoring, mirroring Wiki or CodeGraph assets, the Memory
Knowledge API, a live benchmark in CI, a schema migration (the ledger is a disposable file).

## Gaps and follow-ups

- No `memory.tencent.service_id` setting exists either: until one does, Core passes `service_id` (empty
  works only for a sidecar that does not enforce the header).
- No `memory.tencent.allow_private` setting exists (Slice 10a owns the settings model): the Core wiring
  decides `allow_private`; until a setting exists it is always false.
- The settings layer validates `memory.tencent.url` as http(s) without userinfo, query or fragment; the
  adapter adds the rule that plain `http` is loopback only (the bearer token must not cross a network in clear).
- No route triggers `resync` yet: Core or the Memory Center (Slices 10b, 12) must call
  `registration.sink.resync()`.
