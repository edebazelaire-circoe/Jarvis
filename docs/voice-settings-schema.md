# Voice settings schema

`GET /api/settings` exposes three distinct Voice views. They must not be
confused when rendering or saving settings:

- `voice.stack` is the stored compatibility stack.
- `voice.effective_stack` is the stack selected by
  `resolve_voice_composition`; an explicit versioned architecture currently
  derives `openai_realtime`, even if the inactive compatibility stack remains
  `gemini_live`.
- `voice.settings` and `voice.stacks` retain the historical per-stack values
  and field descriptors. Inactive values are preserved, including
  `openai_realtime.ack_delay_ms`.

## Metadata projection

`voice.categories` is ordered: `architecture`, `conversation`,
`turn_taking`, `models`, `audio`, `advanced`, `diagnostic`.

`voice.option_metadata` contains every persisted Voice option exactly once,
then the computed diagnostic projections. Every entry provides an `id`,
`persistence`, `source`, native `kind`, canonical `type`, display `label` and
`help`, normalized `options`, `category`/`destination`, `advanced`,
`runtime_status`, and `readonly`. Numeric constraints and conditional metadata
are included when the owning live descriptor supplies them. Model options keep
provider/model identity, selectability, adapter state and availability, but do
not copy nested `settings_fields`; the historical stack descriptors remain the
single owner of those transport fields.

The projection is assembled from the live capability, stack, authorization
and shortcut registries. Inventory guards fail tests when a live persistable
field has no category mapping. Diagnostics have `persistence: null` and are
read-only. `owner_profile_path` is also read-only, though its configured value
continues to live in the settings file.

## Write and diagnostic contract

The projection is additive and read-only. `POST /api/settings` retains its
existing request forms and ignores projected `categories`, `option_metadata`
and `effective_stack`; none is persisted. Metadata contains no secret values
and performs no provider I/O.

Echo-cancellation applicability uses the same effective composition as the
runtime. Therefore an explicit continuous OpenAI architecture reports AEC as
applicable even when the stored compatibility stack is Gemini. Existing
`voice.echo_cancellation`, authorization, switch and catalog diagnostics remain
the runtime authorities; the schema introduces no event or diagnostic channel.

Voice capture reports carry the composition `configuration_id` and effective
`architecture` alongside the historical operational `arch`. The Control Center
trusts an AEC runtime result only when its configuration ID matches the current
composition. Reports from older Voice processes, which lack that ID, remain
usable only for the unambiguous compatibility `continuous_brain` mode. A report
from another configuration is displayed as runtime context but cannot override
the settings probe; `restart_required` stays true.

Contract regression coverage lives in
`tests/unit/test_voice_settings_schema.py` and the existing Settings endpoint
suite.

## Control Center rendering

The top-level `Voix` tab renders its seven sub-tabs directly from ordered
`voice.categories`. Each `voice.option_metadata` entry is rendered exactly once
under its backend-provided category. Generic persistence adapters update the
existing `voice`, `audio`, authorization, architecture, and shortcut request
shapes; the browser does not maintain a second setting-to-category map.

Audio device discovery and diagnostic refresh are local, guarded asynchronous
operations. A closed or superseded panel cannot publish its response. Device
errors and successful empty detection expose retry without blocking the
remaining Voice categories; audio testing stays disabled until both an input
and an output exist. Provider-backed model selects hydrate locally from
`/api/models` using each record's `source`, retain saved absent values, expose
unavailable evidence, and never remount the shared comparison catalog. A
strict `provider:role` source plus `voice_stack_settings.*` persistence gate
keeps architecture model selectors on registry-provided options only. A
diagnostic refresh replaces only read-only server state while preserving the
draft. The Models panel owns a separate shared catalog controller for the
backend roles `realtime`, `transcription`, and `speech`; switching sub-tabs,
rerendering, or closing aborts and destroys that controller. Search, filters,
sort, and comparison selection are retained per role. Diagnostic metadata is
the single rendering inventory; its owner profile path comes from the
effective verifier settings and is not repeated by parallel raw-status blocks.
