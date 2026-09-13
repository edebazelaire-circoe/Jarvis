# Settings and Prompt Configuration

## Voice Architecture

Replace a flat voice-model choice with:

```text
Voice Architecture
  ○ Simple
  ○ Front Brain
  ○ Duplex
```

Selecting an architecture changes only the fields relevant to that architecture.

## Simple

Conversation provider/model, voice if supported, VAD/interruption controls, reasoning/latency controls if supported, conversation prompt layers, and backend/JARVIS prompt access.

## Front Brain

Reflex/realtime provider/model, front-brain analysis provider/model, reflex prompt, analysis prompt, partial-transcript analysis/budget controls, relevant voice/VAD settings, and backend/JARVIS prompt access.

## Duplex

Duplex provider/model (initially GPT-Live 1), frontend prompt, client-delegation status, idle-close policy, cost guards, and backend/JARVIS prompt access.

## Model lists

Populate from the capability registry. Exact Gemini models/capabilities come from current JARVIS code, not assumptions.

## Prompt inspector/editor

For each runtime role show role name, provider/model, application prompt layers in order, provenance, editable/read-only state, raw content, resolved effective application prompt, dirty status, reset/default action, and validation warnings.

Provider-internal hidden system prompts are not available to JARVIS and must not be represented as visible.

## Edit safety

Persist prompt revisions; attach revision IDs to traces/benchmarks; allow revert; define apply-next-session vs supported hot-update behavior; never silently rewrite a user's custom prompt when switching models.

## Implemented Task10 hooks

Explicit Simple/Front Brain now share `jarvis.conversation.v2` (persona plus `domain/conversation_prompt.py` rules); confirmed history is role-separated initial context, not developer instructions. Front Brain adds `jarvis.front-brain.v1` and strict Task09 schema in `domain/front_brain_prompt.py`. Its exact analysis model/effort/speculation come from the existing FrontBrainVoiceConfig. Defaults are 150 ms debounce, 300 ms minimum interval, 2 s deadline, at most two provisional calls plus one final, and 512 output tokens including reasoning. Request/response byte caps and conservative fixed per-call reservation are separate from measured token usage. Source/config/admission freshness is checked at actual consumption. The hint consumer is diagnostic-only in this slice and cannot delay direct speech or execute work. See [Task10 effective composition, budget units and evidence](10-implementation-evidence.md).

## Task14 implementation: architecture-first Settings

`GET /api/settings` exposes `voice.architecture`: the versioned selection,
compatibility flag, current readiness problem, and a registry-generated list of
architectures. `VoiceCapabilityRegistry.settings_architectures()` owns labels,
descriptions, role fields, model references, selectable/reason metadata, defaults
and bounds. The browser renders those descriptors; it has no provider/model or
architecture-ID switch. Realtime provider controls are projected as model options;
Duplex has no Realtime controls and exposes required client delegation plus its
independent finite idle timeout (5–3600 seconds, default 60).

Simple has one conversation model. Front Brain has reflex and analysis roles,
provisional-delta analysis and supported reasoning efforts from the selected
analysis model. Adapter READY is displayed separately from account availability
UNKNOWN; a registry entry is not an account-access, acoustic or billing claim.
Existing unsupported/unavailable models remain visible with their reason. Explicit
new selections must pass registry support and runtime-readiness validation.
Simple/Front Brain with a saved manual turn boundary are rejected until automatic
segmentation is selected; the inactive legacy setting is never silently rewritten.

`POST /api/settings` accepts `voice.architecture` as the discriminated **config**,
not the query or persistence envelope. A successful explicit change persists
`voice_architecture = {schema_version: 1, config, compatibility: null}` using the
existing atomic Settings writer. All other settings, inactive profiles, prompts
and legacy keys remain intact. The explicit-change latch is crucial: ordinary
Save omits this field. With no existing namespace, Save writes **no canonical
namespace**, leaving legacy/continuous_brain execution and environment inheritance
unchanged. Their Simple projection is descriptive, not a migration. Activating
the same projected mode explicitly preserves its current model.

Settings prepares future configuration; Save does not stop, replace or mutate an
active frontend or its Jobs. Existing process composition still reads configuration
at startup; Task17 owns replacement/reload orchestration. No Live session
timer/control panel (16) or hot switching (17) is implemented here.
Older async panel/catalog responses cannot overwrite a newer panel selection.
Optional Google catalog corruption is isolated with a stable diagnostic and no
raw cache contents; GET performs no provider discovery or network calls.

See [Task14 implementation evidence and exact gates](14-implementation-evidence.md).

## Task15 implementation: registry, effective preview and overrides

The prompt registry describes every current JARVIS-controlled layer by a stable
ID, source file and symbol, role/provider/model applicability, destination
channel, append/replace/message operation, editability and apply policy. Its
programs preserve channel boundaries: Realtime session instructions, structured
initial context and tools; response-specific reflex/verbatim replacements; Luna
instructions, user observation and JSON schema; GPT-Live instructions; Claude
system append/replacement; and Claude/Codex stdin turns are resolved separately.
No flat text is presented as a complete provider system prompt.

Editable scope is deliberately narrow: the shared voice persona and empty user
addition layers for conversation, Front Brain analysis, Duplex, backend system
and backend turns. Tool schemas, runtime data, response delimiters, delegation
rules and safety/runtime invariants are read-only. Overrides live in
`prompt_overrides = {schema_version: 1, overrides: ...}` and store only text plus
the reviewed default revision. Stale defaults and concurrent edits are visible
conflicts; reset removes one override; defaults are never materialized; inactive,
unknown and unrelated settings survive writes.

`GET /api/prompts` projects only the programs applicable to the saved voice
architecture/model and active backend CLI. It returns ordered provenance,
effective layers, channel-specific resolved previews and static/render
fingerprints. Dynamic inputs use an explicitly empty preview and are never
presented as a captured live request. `POST /api/prompts/{id}` edits or resets one
layer atomically. The Prompts Settings tab renders this server projection and
states that provider-internal prompts are unavailable.

Production OpenAI Realtime, Gemini, Luna, GPT-Live and Claude/Codex conversation
paths consume the same registry resolution. Normal diagnostics contain program
IDs, layer revisions and fingerprints, never prompt or transcript text. Settings
save is `saved_only`; provider writes are `sent`; the Realtime session startup
instruction is `acknowledged` only after its matching session update event.
Claude resume is recorded as such because the CLI may retain its earlier system
snapshot. Initialization edits take effect on the next matching session;
invocation additions take effect on the next actual matching send. Task17 still
owns coordinated hot replacement.
