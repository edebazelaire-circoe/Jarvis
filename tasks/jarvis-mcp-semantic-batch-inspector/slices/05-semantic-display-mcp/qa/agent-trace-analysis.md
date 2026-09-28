# Slice 05 — Agent trace analysis (live brain, real model)

HEAD `f2d706e`, branch `task/jarvis-mcp-semantic-batch-inspector`, 2026-09-25. Claude Code 2.1.282, CLI default model, normal Anthropic API. No source modified.
Evidence: `trace-evidence/` (scripts, raw per-turn stream `brain-turns.jsonl`, readable `turns-dump.txt`, display-server journal `core-display-trace.txt`).

**Verdict: PASS, with 1 MINOR (pre-existing, amplified by the S5 prompt flow) and 2 FLAGGED items.**

## Method

- Isolated Core (`-m jarvis core`, `127.77.0.1:17683`) and Control Center (`17685`). `JARVIS_DATA_ROOT` and `JARVIS_RUNTIME_DIR` were in the scratchpad. The user's live Jarvis (17653/17654) was not touched and was still listening at the end. Every script refuses to run on an empty port or on 17653/17654.
- The brain is the **real `ClaudeLocalAgent`** (profile `conversation`, `display_mcp=DisplayMcpTarget(isolated Core)`), driven through `agent.ask()` exactly like the voice loop. Its argv came from the real code (`trace-evidence/brain-argv.json`): `-p --input-format stream-json --output-format stream-json --verbose --mcp-config <display-mcp.json written by write_mcp_config> --permission-mode bypassPermissions --append-system-prompt <resolved conversation_display_session prompt> --settings <routing hook>`.
  Harness changes, applied only by wrapping `create_subprocess_exec`: `--chrome` removed so the brain cannot reach the user's browser, and `--no-session-persistence` added. Bare Hands and console MCP were not declared, so the prompt is the `conversation_display_session` composition.
- `CLAUDE_CONFIG_DIR` isolation fails (`Not logged in`), so the default user config was used, read-only. The user text was sent without the per-turn voice brief (`build_agent_brief`).
- Seed, posted as `user` / runtime: the constellation `orion` → {budget (pinned), equipe → risques (hidden), planning}, placed near the left edge. Also `courses` (pinned), `idees`, and 4 agent stars (3 completed, 1 running). Revision 25.
- 7 turns in total. Turns 1–6 ran in one conversation. Turn 7 ran in a new process (an extra probe of the partial-refusal wording). Cost was about $0.68.

## Per-turn table

| # | User (FR) | Tool calls (brain) | Core commands | Rev Δ | Result the model received | Reply | Truthful |
|---|---|---|---|---|---|---|---|
| 1 | Masque toute la constellation du Projet Orion. | ToolSearch(select inspect, update_many, query) → `scene_inspect{text:"Orion"}` → **`scene_update_many{select:{constellation:{object_id:"orion"}}, visibility:"hidden"}`** | 1 `patch_selection` | 25→26 (+1) | inspect: raw `{"scene":…}` 1 728 B. Mutation: compact typed JSON 933 B, `matched 5 / changed 4 / unchanged 1`, `hidden_count 1` | « C'est masqué : les cinq éléments du Projet Orion, dont un qui était déjà caché. » | Yes: « dont N » matches `hidden_count` |
| 2 | Réaffiche tout. | `scene_query{visibility:hidden}` → **`scene_update_many{select:{visibility:hidden}, visibility:visible}`** | 1 | 26→27 (+1) | query raw 1 668 B. Mutation 509 B, changed 5, `hidden_count 5` | « Tout est réaffiché. Les cinq éléments … sont de retour, y compris celui qui était déjà caché avant. » | Yes |
| 3 | Déplace cette constellation un peu vers la gauche. | ToolSearch(scene_move) → `scene_query{constellation:orion}` → **`scene_move{select:{constellation:{object_id:"orion"}}, dx:-30, dy:0}`** | 1 `translate_selection` | 27→28 (+1) | 598 B. `delta.requested (-30,0)`, `effective (-12,0)`, `clamped:true`, all 5 changed, hidden 0 | « décalée …, seulement d'un petit cran : elle touche maintenant le bord de l'écran » | Yes: the clamp was reported |
| 4 | Archive les étoiles terminées. | ToolSearch(archive) → `scene_query{kinds:[agent,job], exec_state:completed}` → **`scene_archive{select: same filter}`** | 1 `archive_selection` | 28→29 (+1) | 470 B, 3 archived, `cascade_ids []` | « J'ai archivé les trois étoiles terminées. La veille techno tourne encore » | Yes |
| 5 | Désépingle tout. | ToolSearch(pin) → `scene_inspect{}` → **`scene_pin{object_ids:[orion-budget, courses], pinned:false}`** | 1 `unpin_selection` | 29→30 (+1) | 278 B | « … le budget Orion et la liste de courses. » | Yes: exactly the 2 pinned objects |
| 6 | Archive l'objet zzz-inconnu. | `scene_query{text:"zzz"}` → 0 matches → **no mutation** | 0 | 30→30 (0) | query raw 812 B | « Je ne trouve aucun objet de ce nom …, je n'ai rien archivé. » | Yes (honest refusal) |
| 7 | Archive idees et zzz-inconnu. (new session) | ToolSearch → `scene_inspect{}` → **`scene_archive{object_ids:["idees"]}`** | 1 | 30→31 (+1) | 248 B | « J'ai archivé les idées de vacances. Je n'ai rien trouvé … zzz-inconnu, donc rien d'autre n'a été retiré. » | Yes: it split the request and said so |

- Every mutation was **one set-tool call, and every call posted one Core command**, confirmed three ways: `display.tool` journal (one entry per call), a revision delta of exactly +1, and the page (one rendered-set change per turn, see runtime report). There was **no `scene_update_object` loop, no retry and no tool error**. Turns took 3.4–8.0 s, all within the 8 s budget, with no `agent.turn_over_budget`. Nothing was delegated.
- Reads are the raw text (`{"scene":…}`, `tool_use_result` without `structuredContent`). Mutations reach the model as compact typed JSON (`content` string = `structuredContent`). There is **no `{"result":` wrapper** anywhere.
- One read before each mutation is the prompted pattern (« relis d'abord … »). T5 used a full `scene_inspect` where a `scene_query{pinned:true}` would do, which is acceptable.

### Tool-level refusal path (not reached by the model: it checked before mutating)

The brain never sent an unknown id, so the same real server (`display-mcp.json` written by the real code) was called directly outside the model (`trace-evidence/mcp-probe.txt`). Revision stayed 31:
- `scene_archive{object_ids:[courses, zzz-inconnu]}` → `isError`, « archive_selection refusé … (invalid/unknown_object) … Rien n'a été appliqué (lot atomique : tout ou rien). Refusés : zzz-inconnu (unknown_object, ids). » `courses` was not archived.
- `scene_pin{select:{constellation:{object_id:"zzz-inconnu"}}}` → same shape, and names the constellation root.
- `scene_move{dx:0,dy:0}` → « Argument invalide, rien n'a été envoyé : delta (0, 0) moves nothing », with nothing posted.

## Tool definitions and bytes

Fake-endpoint capture of what the CLI sends (`model-visible-defs.txt`, the same config file, one request):
- 13 `mcp__jarvis-display__*` tools. The key set is exactly `description`, `input_schema`, `name`. The strings `outputSchema`, `annotations`, `readOnlyHint`, `destructiveHint`, `idempotentHint` and `structuredContent` appear **nowhere** in the body.
- **No `title` keywords.** The only `"title"` keys are the real `title` properties of `scene_create_object`, `scene_update_object` and `scene_add_artifact`.
- Bytes (name + description + compact input_schema) are **31 833 B**. The docs and LOG claim 31 832 B, so they are 1 B off. The repo's own `build_catalog()` also gives 31 833 at this HEAD, and the model-side sum is identical. With the `mcp__jarvis-display__` prefix it is 32 106 B, and the compact JSON of the definitions is 32 821 B. The largest are `scene_update_many` (4 769), `scene_query` (4 172) and `scene_update_object` (3 381).
- The live brain loads these **deferred** through `ToolSearch select:` (turns 1, 3, 4, 5, 7). The full definitions are expanded server-side from `tool_reference` blocks, so their exact bytes can't be observed on the real API. S4 showed the deferred definitions carry only `defer_loading` in addition.

## Findings

| Severity | Finding |
|---|---|
| MINOR (pre-existing, amplified) | **Spurious `scene_changed` after a filtered read.** A set call after `scene_query` or a filtered `scene_inspect` always returns « La scène a changé depuis ta dernière lecture (révision N → N+1) : relis-la… ». Here N+1 is the brain's **own** command: T1–T4, `display.tool … "scene_changed": true`. In T1 it also lists 6 unchanged objects as `+ … ` additions (`courses`, `idees`, 4 stars), because the filtered read never showed them. Cause: `_revision_hint` takes the slow path when `_seen_partial` is true, and `_change_hint` then treats `seen_rev != current_rev` as "moved", even though the only change is the expected +1 (`display_mcp.py` ~1732 / ~1766). This logic predates S5, but the S5 prompt now asks for a `scene_query` before every broad set, so almost every set result carries a false "the scene changed without you, re-read" signal. The model ignored it here. The risks are an extra `scene_inspect` or a false « de nouveaux objets sont apparus ». Repro: T1 in `turns-dump.txt`. Suggested fix: after a partial read, when `revision == expected`, emit only the "partial read" variant, or nothing. |
| FLAGGED (doc) | The context cost is 31 833 B, not 31 832 B (`tool-contract.md` §10.5, LOG). This is a 1 B drift, and the gate (≤ S4 baseline 33 090) still holds. |
| FLAGGED | The model never reaches the tool refusal path for an unknown id: it looks the id up first and refuses in words. Refusal wording and atomicity were checked directly on the server (above). Slice 08 could add a turn with a stale id (for example one archived in the page between two turns) to exercise it live. |
| OPTIMIZATION | T1 loaded `scene_query` through ToolSearch without using it. T5 did a full inspect (2 094 B) where `scene_query{pinned:true}` would have been enough. Both are cheap. |

No BLOCKER or MAJOR finding. The hidden_count wording follows the prompt (« dont un qui était déjà caché »). The clamp was reported honestly.

## Not verified

- Exact bytes of the deferred definitions on the real API (not observable). The voice-loop per-turn brief was not included. The brain ran without `--chrome`, Bare Hands or console MCP.
- A multi-turn stale-memory scenario (a page edit between turns) was not run.
