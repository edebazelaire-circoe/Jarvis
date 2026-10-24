# Functional Specification

## Page shell

Title: **Mémoire & connaissances**.

Use the same Settings shell as the other redesigned pages: dark neon/glass visual language, clean hierarchy, no decorative quote, circular profile/avatar control top-right.

Primary internal destinations:

- Mémoire
- Connaissances
- Memory Center

## Mémoire

### Rappel

Expose:

- recall enabled;
- maximum memories per turn;
- plain-language explanation that recall can combine lexical and semantic results.

Raw timeout in milliseconds is Advanced-only.

A `Rapide / Équilibré / Approfondi` preset is allowed only if implementation defines an explicit mapping to real runtime settings; it must not be decorative.

### Recherche sémantique

Expose:

- enabled;
- embedding provider from server schema;
- private-scope permission;
- credential configured/not-configured state only.

Do not hard-code provider options in frontend. Do not show secret values.

### Consolidation

Expose:

- manual / auto;
- confidence threshold when auto is relevant;
- maximum candidates per run.

Explain that candidates are proposals, not canonical memories until accepted or auto-commit rules legitimately apply.

### Summary card

May summarize:

- canonical memory availability;
- effective recall legs in plain language;
- consolidation mode;
- major scopes.

The summary is status, not a second editable copy.

## Connaissances

### Source cards

Show Wiki, CodeGraph and Skills with distinct states:

- enabled/active;
- disabled;
- unavailable/degraded.

Current `main` wires Wiki and Skills. CodeGraph must remain unavailable until a real provider/repository exists.

### Agent access/loadouts

Provide an editable matrix/card view for effective policy.

User-facing dimensions should include:

- Memory access;
- private memory permission;
- Wiki;
- CodeGraph;
- Skills.

Rows should map to meaningful Brain/agent role identities. Internally preserve canonical loadout keys and validation rules.

Private memory remains deny-by-default for non-Brain loadouts unless a valid rule explicitly grants `private` with `allow_private=true`.

The UI must support adding/updating/removing loadout overrides without forcing manual settings-file edits.

### Scopes

Explain private/shared/project scopes in product language. This is explanatory unless backed by editable canonical rules.

## Memory Center

Dedicated workspace. Keep:

### Notes

- list/search;
- filters by level, retention and kind;
- include superseded toggle;
- detail view with body, provenance, revision, scope, relations;
- clearly label canonical content.

### Candidates

- proposed candidates queue;
- detail with provenance/conflicts;
- accept/reject after confirmation;
- preserve conflict/error/unknown-outcome handling.

### Knowledge

- read-only provider/loadout inspection is allowed, but should deep-link to editable Knowledge Settings rather than duplicate editing.

### Recall Test

- user phrase input;
- max item count within server/runtime bounds;
- show which memories would be recalled, scores/ranks/why/timings where helpful;
- nothing is written or injected by the test.

### Health

Detailed health may remain accessible but should be secondary. Advanced diagnostics is the canonical technical destination.

## Advanced & diagnostic

Move or expose there:

- `recall.timeout_ms` raw tuning;
- Tencent enable/url/service id/private permission;
- Tencent mirror health;
- detailed lexical/semantic/Tencent capability codes;
- index syncing details;
- environment/file/default provenance;
- raw restart-required technical details;
- detailed per-leg timings and degradation codes.

Normal page may show a concise warning and a deep link.

## Forbidden UX

- raw `memory_scopes` as the primary editor;
- editable duplicate settings in multiple tabs;
- showing CodeGraph as active when no provider is mounted;
- treating derived indexes as memories;
- showing token/key values;
- inventing providers, rebuild buttons or index-management operations that Core does not expose.
