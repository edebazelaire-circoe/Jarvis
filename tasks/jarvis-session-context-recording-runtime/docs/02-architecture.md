# 02 - Target architecture

## 1. Domain model

### JarvisSession

Target semantics:

- stable `jarvis_session_id`;
- `open` until explicit user new-session operation;
- restart/relogin/relaunch rehydrates the open Session;
- stores/derives current active Context identity;
- closed Sessions are historical and immutable except explicitly versioned maintenance metadata if the existing contract requires it.

The current Board fields/bindings may remain temporarily for compatibility, but new Context/Capture state is keyed by `jarvis_session_id`, never `board_id`.

### SessionContext

Suggested minimum structured fields, exact wire names to be finalized in Slice 01:

```text
context_id
jarvis_session_id
status: active | dormant
created_at
activated_at
last_active_at
workspace_ref/path
optional title/label
optional handoff/source-context refs
small runtime metadata
```

Invariants:

- at most one active Context for the open Session;
- creating/activating a Context atomically dormants the previous active Context;
- dormant Contexts are not implicit agent write targets;
- explicit reactivation is allowed;
- workspace paths are backend-derived from IDs, never user-provided arbitrary paths.

### Context workspace

Recommended layout:

```text
<data_root>/sessions/<jarvis_session_id>/
  contexts/
    <context_id>/
      ... agent-owned free-form files ...
  activity.jsonl    # optional reconstructible projection, not competing truth
```

The agent may add/remove/reorganize files in the **active** Context. Backend lifecycle metadata remains in SQLite. If a session-folder activity file is materialized, define whether it is an append-only projection/outbox and how it is reconstructed from canonical events.

## 2. Artifact registry

Use a generic registry rather than one table per capture feature.

Suggested conceptual record:

```text
Artifact
  artifact_id
  kind
  created_at
  started_at? / ended_at?
  source
  session_id?
  context_id?
  payload_ref?
  mime_type?
  size_bytes?
  duration_ms?
  dimensions?
  metadata_json
  state: pending | complete | failed | partial
```

Use explicit relation/provenance records rather than stuffing every derivation into opaque metadata:

```text
ArtifactRelation
  source_artifact_id
  target_artifact_id
  relation: transcribed_from | frame_from | described_from | derived_from | ...
```

Text artifacts may store bounded text directly or in files according to the existing data conventions; large binary payloads do not belong in SQLite.

Payload recommendation:

```text
<data_root>/artifacts/<artifact_id>/
  source.wav
  source.webm / source.mp4 / platform format
  screenshot.png
  transcript...       # when file-backed
  derived/...         # optional derived evidence
```

Paths stored in the registry should be normalized relative references when practical so moving the configured data root does not invalidate records.

## 3. Canonical activity ledger

Record factual, append-oriented activity such as:

- `session.resumed`
- `context.created`
- `context.activated`
- `context.dormant`
- `capture.started`
- `capture.stopped`
- `capture.gap`
- `artifact.created`
- `artifact.finalized`
- `artifact.enrichment.updated`
- `transcript.segment.created`
- `transcript.projection.updated`

Each event should carry stable IDs and timestamps, and be queryable/tailable by Session and Context. Avoid copying raw media or unbounded transcript text into generic runtime journals.

The global `RuntimeJournal` can mirror diagnostics with `jarvis_session_id` / `context_id`, but it is not the product's canonical Session activity store.

## 4. Capture owner

Introduce a capture runtime/service with lifecycle independent of the Brain. Exact process boundary is a Slice 00/05 freshness decision, but these invariants are fixed:

- Brain/MCP/UI are clients;
- explicit capture can be controlled without a live reasoning agent;
- durable state makes active/incomplete capture discoverable after process recovery;
- only one owner controls a physical device/source at a time;
- status truth comes from the capture owner, not frontend optimistic state;
- source media is finalized atomically where possible;
- crashes leave recoverable partial artifacts, never files silently presented as complete.

If true uninterrupted capture across **Core** process death requires a separate supervised process on the target host, implement that boundary rather than falsely claiming continuity. If the supported V1 boundary is Brain death but not capture-service death, document that exact guarantee and recover partial files after service restart.

## 5. Audio recording/transcription

Reuse the current microphone ownership architecture where possible, but separate explicit durable recording from the ambient freshness lane.

Recommended flow:

```text
physical microphone owner
   |
   +--> durable recording sink -> spool/final audio artifact
   |
   +--> segmentation/STT worker -> transcript artifacts
                                      |
                                      +--> live projection / context enrichment
```

The canonical recording sink must not use `drop_oldest`. If disk/IO cannot keep up, fail or record a precise gap/partial state. Transcription may lag without losing source media. Provider failure is retryable from the recording artifact.

Transcript chunks carry recording-relative and wall-clock time ranges and immutable raw accepted text. A readable whole-transcript view is a projection, not permission to rewrite raw evidence.

## 6. Desktop screenshot and screen recording

This is distinct from scene capture.

- screenshot captures the requested desktop/display/window policy established by Slice 07;
- screen recording is continuous media with start/stop lifecycle;
- every result is an Artifact with time/source/session/context metadata;
- screen understanding should sample keyframes or meaningful visual changes rather than sending every frame to vision;
- user-triggered screenshots are high-value observations and may be enriched asynchronously.

OS permissions, multi-monitor selection, codecs and capture library choice are implementation decisions based on the actual supported Jarvis host discovered in Slice 00/07, not guessed into the domain contract.

## 7. Live Context memory worker

A background enrichment worker consumes canonical evidence and updates the active Context workspace/projections incrementally.

It should work from:

- current Context workspace state;
- activity cursor/version;
- new transcript/artifact evidence;
- bounded recent evidence;
- provenance links.

It may revise semantic state, for example changing an issue from open to resolved after later evidence. It must never rewrite immutable raw transcript/media evidence. Updates should be idempotent/replay-safe enough to recover after restart.

## 8. Brain catch-up

On Brain start/resume, inject or make cheaply available:

1. Session identity and active Context identity;
2. active Context compact live summary/state;
3. latest canonical activity cursor/tail;
4. recent transcript tail and relevant artifact refs/indexes;
5. pointers for deeper retrieval.

Do not replay an entire hours-long transcript into every new Brain process.

## 9. API/MCP

Expose capture/session-context commands through one runtime owner. Candidate operations, names not locked until Slice 09 audits the current MCP catalog:

```text
session/current + context status/switch/create/reactivate
capture status
start/stop audio recording
start/stop screen recording
screenshot
artifact get/search/query by time/type/session/context
transcript tail/read
```

MCP tools call the same service/API as the UI. Register metadata, side effects, schemas and availability through the existing MCP catalog mechanisms. No duplicate handwritten frontend catalog.

## 10. Left floating toolbar

Current main has two different tool surfaces. The target is **not** the right `.dock`; it is the fixed left Bare Hands palette (`#barehandsPalette`).

Generalize its visual rail into coherent groups while preserving the existing hand-tool group:

```text
[ Bare Hands lifecycle control ]
[ pointer ]
[ pan     ]
[ select  ]
-----------
[ screenshot ]    action
[ audio rec  ]    toggle + active/elapsed/error state
[ screen rec ]    toggle + active/elapsed/error state
```

Exact icons/order may be refined by `/impeccable`, but capture state must be recognizable without relying on color alone. Capture controls remain available when Bare Hands is off. Update scene safe-area measurement (`CONTROL_SELECTOR`) and browser tests so the scene never places content under the enlarged rail.
