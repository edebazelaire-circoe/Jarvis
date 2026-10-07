# Memory settings (backend model and persistence)

Slice 10a of `jarvis-memory-intelligence-knowledge`. Model: `jarvis/domain/memory_settings.py`
(dataclasses, defaults, combination rule). Persistence and description:
`jarvis/runtime/memory_settings.py`. Not yet registered in `control_center.py`
(Slice 10b adds the endpoints, `status` and the UI).

## Storage

A new top-level key `memory` in `control-center-settings.json`. No new file and
no migration (D6). Secrets are never stored there; see Secrets.

## Entry points

| Function | Contract |
| --- | --- |
| `read_memory_settings(raw, environ=None)` | Tolerant. Effective settings (env > file > default). Never raises. |
| `stored_memory_settings(raw)` | File only, env ignored. Base of a write. |
| `effective_memory_settings(raw, environ=None)` | Per field `{value, source}`, source `default\|file\|env`; `downgraded` carries a compatibility code. |
| `validate_memory_settings_write(raw, stored=None)` | Strict, whole request. Raises `MemorySettingsError(code, message, field)`. Payload is a patch over `stored`. |
| `apply_memory_settings(settings, payload)` | Validate, then set `settings["memory"]`. On refusal `settings` is untouched. |
| `describe_memory_settings()` | Schema served to the UI: types, ranges, enums, defaults, env names, compatibility rules. The UI hard-codes none of it. |
| `memory_state(settings, environ=None)` | `values`, `effective`, `secrets` (`has_secret` per leg). |

## Schema

| Path | Type | Default | Range / values | Env |
| --- | --- | --- | --- | --- |
| `recall.enabled` | bool | `true` | | `JARVIS_MEMORY_RECALL_ENABLED` |
| `recall.max_items` | int | `6` | 1..10 | `JARVIS_MEMORY_RECALL_MAX_ITEMS` |
| `recall.timeout_ms` | int | `400` | 100..1500 | `JARVIS_MEMORY_RECALL_TIMEOUT_MS` |
| `semantic.enabled` | bool | `false` | | `JARVIS_MEMORY_SEMANTIC_ENABLED` |
| `semantic.provider` | enum | `none` | `none`, `openai` | `JARVIS_MEMORY_SEMANTIC_PROVIDER` |
| `semantic.allow_private` | bool | `false` | | `JARVIS_MEMORY_SEMANTIC_ALLOW_PRIVATE` |
| `consolidation.mode` | enum | `manual` | `manual`, `auto` | `JARVIS_MEMORY_CONSOLIDATION_MODE` |
| `consolidation.auto_min_confidence` | float | `0.8` | 0..1 | `JARVIS_MEMORY_CONSOLIDATION_AUTO_MIN_CONFIDENCE` |
| `consolidation.max_candidates_per_run` | int | `20` | 1..100 | `JARVIS_MEMORY_CONSOLIDATION_MAX_CANDIDATES_PER_RUN` |
| `tencent.enabled` | bool | `false` | | `JARVIS_MEMORY_TENCENT_ENABLED` |
| `tencent.url` | text | empty | http(s), max 512, no userinfo | `JARVIS_MEMORY_TENCENT_URL` |
| `knowledge.wiki_enabled` | bool | `true` | | `JARVIS_MEMORY_KNOWLEDGE_WIKI_ENABLED` |
| `knowledge.codegraph_enabled` | bool | `true` | | `JARVIS_MEMORY_KNOWLEDGE_CODEGRAPH_ENABLED` |
| `knowledge.skills_enabled` | bool | `true` | | `JARVIS_MEMORY_KNOWLEDGE_SKILLS_ENABLED` |

Defaults and ranges come from the domain module; the runtime table copies none.
Types are strict on write: a bool is not an int, `"3"` is not `3`.

## Precedence

Per field: environment variable, then file, then default. An empty or
unparsable variable is ignored (the file value stays). Env booleans accept
`1/true/yes/on` and `0/false/no/off`. A write never captures an env value into
the file.

## Compatibility matrix

| When | Requires | Write (strict) | Read (tolerant) |
| --- | --- | --- | --- |
| `semantic.enabled` | `semantic.provider != none` | `memory_settings_semantic_needs_provider` | `semantic.enabled` forced `false` |
| `consolidation.mode = auto` | `semantic.enabled` | `memory_settings_auto_needs_semantic` | `consolidation.mode` forced `manual` |
| `tencent.enabled` | non-empty `tencent.url` | `memory_settings_tencent_needs_url` | `tencent.enabled` forced `false` |

Rules are checked in this order on the merged result, and also degrade in this
order on read (semantic first, because auto consolidation depends on it).
Disabling every optional leg leaves canonical memory usable.

## Error codes (stable)

`memory_settings_bad_payload`, `memory_settings_bad_section`,
`memory_settings_bad_type`, `memory_settings_out_of_range`,
`memory_settings_bad_enum`, `memory_settings_bad_url`,
`memory_settings_secret_refused`, plus the three compatibility codes above.
Messages carry the field path, never the offending value.

## Write semantics

- Whole-request: any invalid field refuses everything; nothing is written.
- Patch: absent fields keep their stored value. The written block holds every
  known field, normalised.
- Unknown top-level, section and nested keys are preserved (stored and sent).
- `has_secret` may be sent back by a UI round trip; it is ignored, never written.

## Secrets

Tokens live in `credentials` only: `semantic` uses provider `openai`, `tencent`
uses provider `tencent` (env fallback `JARVIS_TENCENT_TOKEN`). The `memory`
block refuses any key matching token, secret, password, api key, credential or
bearer, and a URL carrying userinfo. Payloads expose `secrets.<leg>.has_secret`
only, never a value or a hint.
