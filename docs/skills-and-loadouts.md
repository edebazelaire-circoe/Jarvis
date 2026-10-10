# Skills and agent loadouts

Contract page for Slice 09 of the memory, intelligence and knowledge handoff.
A **skill** is a versioned, reusable instruction file. A **loadout** says which
knowledge (memory scopes, Wiki pages, CodeGraph repos, skills) one kind of agent
may see. Both are deny-by-default, inspectable data. Contracts:
`jarvis/domain/knowledge.py` (`Loadout`, `KnowledgeAsset`), `jarvis/ports/knowledge.py`
(`LoadoutResolver`). See [memory.md](memory.md) and [knowledge-assets.md](knowledge-assets.md).

| Module | Role |
|---|---|
| `jarvis/domain/skills.py` | `SkillRecord`, `SkillConflict`, `SkillCatalogView`, `arbitrate` (pure) |
| `jarvis/adapters/knowledge_skills.py` | `SkillRegistry`: discovery, enable/disable, import, `KnowledgeAssetProvider` |
| `jarvis/domain/loadout_view.py` | `LoadoutView` (the loadout plus versions, losers, failures), `render_manifest` (pure) |
| `jarvis/core/loadout_resolver.py` | `KnowledgeLoadoutResolver`, presets, `register_knowledge(...)` |
| `jarvis/domain/memory_settings.py`, `jarvis/runtime/memory_settings.py` | `memory.loadouts` rules, see [settings/memory.md](settings/memory.md) |
| `jarvis/runtime/loadout_snapshot.py` | the file snapshot the routing hook reads |
| `jarvis/runtime/routing_hook.py` | appends the manifest to the `Agent` brief |

Tests: `tests/unit/test_knowledge_skills.py`, `tests/unit/test_loadout_resolver.py`,
`tests/unit/test_memory_settings.py` (loadout section).

## Skill lifecycle

```
<data_root>/knowledge/skills/
  <directory>/SKILL.md        front matter + instructions
  .skills-state.json          {"schema": 1, "enabled": ["<id>@<version>", ...]}
```

`SKILL.md` front matter uses the memory front-matter format (one `key: <JSON value>`
per line between two `---`; no YAML):

```
---
id: "code-review"
version: "2.1"
description: "Review a change before merge"
scope: "shared"
allowed_profiles: ["code", "reviewer"]
source: "import:C:/Users/me/skills/code-review"
---
# Steps
...
```

| Field | Rule |
|---|---|
| `id` | token (`A-Za-z0-9_.-`, at most 128). The identity; the directory name is only a hint |
| `version` | dotted numbers, 1 to 4 parts (`1`, `2.1`, `1.4.2`). `10` > `9`, `1` equals `1.0` |
| `description` | non-empty, at most 300 characters |
| `scope` | `private`, `project` or `shared` |
| `source` | non-empty provenance string (where the user got it) |
| `allowed_profiles` | optional list of profile ids and/or role tags. Empty or absent means every profile |

| Step | Call | Effect |
|---|---|---|
| discover | `catalog()` | every valid skill, the winners, the losers, the invalid ones `(directory, reason)`. Never raises on content |
| import | `import_file(path)`, `import_text(text)` | **user-initiated only.** Validates first, writes nothing on refusal. A new version of a known id lands in `<id>--v<version>/`; the same id and version twice is refused. Enabled by default (`enable=False` to keep it off) |
| enable / disable | `enable(id, version)`, `disable(id, version)` | per version, in the state file. A file copied in by hand is discovered but **off** until enabled; an unreadable state file means everything is off |
| use | `list`, `search`, `read` | only the arbitration winner of an enabled skill is visible |

**Version conflicts.** Among the ENABLED records of one id, the highest version
wins. Every other enabled record is a reported loser (`SkillConflict`: id, winner
version, loser version, loser directory, reason `lower_version` or
`duplicate_version`). A disabled record never wins and is not a conflict. Disabling
the winner promotes the next enabled version. `status()` reports `degraded`
(`skills_invalid`, `skills_version_conflict`) so a screen cannot show a clean "on".

**What a skill is not.** There is no execution, no autonomous extraction from a
conversation, no publication to another agent, and no remote fetch. A skill is text
that a loadout names; delivering it is the only thing the system does with it. A
symlink or junction (the directory or the file) is invalid; `import_file` refuses
a linked source with `MemorySecurityError`.

## Loadout policy

`LoadoutResolver.resolve(profile, role) -> Loadout` (never raises). The richer
`explain(profile, role) -> LoadoutView` adds the version of each entry, the skill
losers and the providers that failed; `explain_all()` covers every key the
snapshot holds. `LoadoutView.as_dict()` is the inspection payload (JSON-ready):
profile, role, scopes, ids, `reasons`, `versions`, `conflicts`, `degraded`.

**Key.** `<profile>` or `<profile>:<role>`. Profiles are the routing task
profiles (`desktop`, `code`, `fast`, `general`) plus `brain`. Roles are `coder`,
`reviewer`, `research`, set in the sub-agent brief (see Hook). A role on an
unmarked brief (profile defaults to `general`) selects its base profile: `coder`
and `reviewer` use `code`, `research` uses `general`. An explicit profile is never
overridden by a role.

**Rule.** One rule per key: `memory_scopes` (exactly what may be read), `allow_private`,
and `wiki` / `codegraph` / `skills` switches. A user rule in `memory.loadouts`
**replaces** the built-in preset for its key; lookup order is `<profile>:<role>`, then the
base profile, then the preset.

**Presets** (no rule configured):

| Base profile | Memory scopes | Wiki | CodeGraph | Skills |
|---|---|---|---|---|
| `code` | `shared`, `project:<id>` | yes | yes | yes |
| `general` | `shared`, `project:<id>` | yes | no | yes |
| `desktop`, `fast` | `shared` | yes | no | yes |
| `brain` | `private`, `shared`, `project:<id>` (`allow_private`) | yes | yes | yes |

`project:<id>` appears only when the resolver was given a `project_id`; without it
no preset grants a project scope (and so no project asset).

**Deny by scope (R6).**

- Private memory is never in a non-Brain loadout unless a policy rule names the
  `private` scope together with `allow_private`. The domain refuses the rule
  otherwise, and a stored rule that breaks it is ignored on read (the preset applies).
- Every provider call passes an **explicit scope**, one call per allowed scope. A call
  with no scope sees every scope (Slice 07 gap). The answer is then re-checked: an asset
  whose scope is not the requested one is dropped, so a provider that ignores `scope`
  cannot leak. CodeGraph is project-scoped and is only asked for `project`.
- A skill is included when it is an enabled winner, its scope is allowed (private
  needs `allow_private`) and `allowed_profiles` is empty or lists the base profile or the
  role. That last rule is the "+role" of the presets: a skill listing `reviewer` reaches
  reviewers only.
- A provider that fails contributes nothing; the failure is in `degraded`. Each kind is
  capped at 64 entries (`loadout_truncated`).

## Agent matrix

Default presets with a `project_id`; `S` is a skill with empty `allowed_profiles`, `C`
one listing `code`, `R` one listing `reviewer`, `Q` one listing `research`, `P` a
private skill.

| Agent | Key | Scopes | Wiki | CodeGraph | Skills |
|---|---|---|---|---|---|
| coder | `general:coder` or `code` | shared, project | shared + project | yes | S, C |
| reviewer | `general:reviewer`, `code:reviewer` | shared, project | shared + project | yes | S, C, R |
| research | `general:research` | shared, project | shared + project | no | S, Q |
| desktop agent | `desktop` | shared | shared | no | S |
| fast agent | `fast` | shared | shared | no | S |
| general agent | `general` | shared, project | shared + project | no | S |
| Brain | `brain` | private, shared, project | all | yes | S, P |

Wiki and skill project assets carry no project id (Slice 07 contract), so any
`project:<id>` grant opens all project-scoped pages and skills; only memory scopes are
project-qualified. This is a known contract gap.

## Manifest

`render_manifest(view)`: header with profile and role, then one line per kind
(`skills`, `wiki`, `codegraph`, `mémoire`) listing **ids and versions only**
(`code-review@2.1`). No title, summary or body. At most 1 024 characters
(`MAX_LOADOUT_MANIFEST_CHARS`): entries are dropped from the longest group's tail and
the count is stated (`(+N autres, voir knowledge_search)`). An empty loadout renders
`""`. Bodies are fetched on demand through the `jarvis-memory` tools
(`knowledge_search`, `knowledge_read`, Slice 05b).

## Delivery

**Sub-agents** (`routing_hook`). The hook is a short-lived process and never calls the
network or Core. Core writes `<runtime_root>/loadout-snapshot.json`
(`write_loadout_snapshot(runtime_root, resolver.explain_all())`, atomic) when assets,
skills or settings change; the hook reads one manifest from it:

1. the brief is signed with the charter, then the manifest is appended after it
   (`prompt` + blank line + manifest);
2. the key comes from the markers at the start of the `description` (or `prompt`):
   `[code] [reviewer] ...` is `code:reviewer`, `[reviewer] ...` is `general:reviewer`,
   `[code] ...` is `code`, nothing is `general`. An unknown second word is ignored;
3. a brief already holding the manifest mark `[loadout JARVIS]` is not given a second one;
4. **any failure** (no file, unreadable or oversized file, wrong schema, missing key, a
   text without the mark, an exception) leaves the call exactly as the charter alone
   made it, and prints nothing to the CLI. An unexpected exception is traced as
   `agent.loadout.failed` (code `loadout_snapshot_failed`); a missing snapshot is normal
   and silent;
5. the injection is traced as `agent.loadout.applied` with profile, role, tool use id and
   the manifest size, never its text.

The snapshot is an untrusted input: it is size-capped (4 MiB), the manifest is stripped of
control characters, clipped to 1 024 characters, and ignored without its mark. The file
also carries each key's full view (`view`), the inspection data.

**Brain.** The Brain manifest travels in `memory.knowledge_manifest` (Slice 05); the
builder calls `resolver.resolve("brain")` and `render_manifest(resolver.explain("brain"))`.

## Wiring (Slice 05 / 05b)

Done by the integration step: `jarvis/runtime/knowledge_wiring.py` (`wire_knowledge`, called from
`jarvis/app.py`) builds the Wiki and Skills providers under `<data_root>/knowledge`, calls
`register_knowledge`, `MemoryWiring.register_knowledge` / `set_loadout_resolver`, writes the snapshot at
startup and keeps it current (`LoadoutSnapshotKeeper`: a 15 s poll that rewrites only when the rendered
loadouts changed, so skills, wiki pages and `memory.loadouts` edits are all covered whichever process made
them; `refresh()` is the manual trigger). CodeGraph is not mounted yet (no repo is configured). The
underlying call is:

```python
from jarvis.core.loadout_resolver import register_knowledge
from jarvis.runtime.memory_settings import read_loadout_policy, read_memory_settings

resolver = register_knowledge(
    wiki=wiki_provider,            # WikiProvider or None
    codegraph=codegraph_provider,  # CodeGraphProvider or None
    skills=skill_registry,         # SkillRegistry or None
    policy=lambda: read_loadout_policy(settings_block()),
    knowledge=lambda: read_memory_settings(settings_block()).knowledge,
    project_id="jarvis",
)
```

`policy` and `knowledge` are re-evaluated on every resolution, so a settings change applies
on the next turn. Then: replace `NullLoadoutResolver` with `resolver`, expose
`resolver.explain(...).as_dict()` through the Core route that lists loadouts, and rewrite
the snapshot (`write_loadout_snapshot`) at startup and whenever skills, wiki pages or
`memory.loadouts` change. Core imports no runtime module, so the wiring layer (which may)
supplies the two callables and calls the snapshot writer.

## Limits to know

- **Base profile `general` plus a role.** `general` is also what the hook assumes when a
  brief names no profile, and the hook cannot tell an explicit `[general]` from that
  default. So `[general] [reviewer]` resolves with base `code` (and `[general] [research]`
  with base `general`); only a non-`general` explicit profile is kept.
- **A stale snapshot is applied as-is.** The hook does not check the snapshot's age
  (`written_at` is informative). Core wiring must rewrite it on every skills, wiki or
  `memory.loadouts` change; between a change and the rewrite, sub-agents get the old manifest.
- **Secret guard.** The `memory` settings secret guard checks key names only, and scope
  strings are rendered verbatim in the manifest: never put a secret in a scope id
  (`project:<id>`, `board:<id>`).
- **One broken provider or asset degrades only itself.** A provider that raises, returns a
  non-iterable (`provider_invalid`) or returns a non-asset object (`asset_invalid`, the valid
  assets of the same provider stay), and a skill record that cannot be used (`asset_invalid`),
  each add a reason to `degraded`; the other kinds stay. `resolver_failed` (empty loadout)
  is reserved for a failure outside any provider, such as the settings callables.
- **Skill versions are ASCII.** `0-9` only; a version in other scripts' digits is refused at
  import and a hand-copied one is listed as invalid, never enabled.

## Known gaps

- `PROFILE_RULE` now teaches `[reviewer]` and `[research]` (integration step); `[coder]` is not taught
  (the `code` preset already is the coder loadout).
- No Core route, UI or `jarvis-memory` tool yet: the effective loadout is data
  (`explain().as_dict()` and the snapshot's `view`), displayed by 10b, 11 and 12.
- Wiki and skill `project` assets are not qualified by project id.
