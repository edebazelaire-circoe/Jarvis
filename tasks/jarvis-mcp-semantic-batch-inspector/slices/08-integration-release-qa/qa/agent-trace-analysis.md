# Slice 08 — Agent trace analysis (live brain, real model, final surface)

HEAD `a9a5b16`, 2026-09-25. Claude Code 2.1.282, model `claude-opus-5-5[1m]`, normal Anthropic API. No product source was modified by the run.

**Verdict: PASS.** There are no BLOCKER, MAJOR or MINOR findings, and 2 items are FLAGGED.

## Method

- **Isolated runtime.** Core ran on `127.77.0.1:17683` and the Control Center on `127.0.0.1:17685`. Data and runtime lived in the scratchpad (`evidence/scripts/env.sh`, `start.sh`). Every script refuses an empty port and ports 17653/17654. The live Jarvis was untouched and still listening at the end. The CC's own brain was disabled (`JARVIS_CLAUDE_CLI=__qa_no_brain_claude__`), and `webbrowser.open` was a no-op.
- **Brain.** The real `ClaudeLocalAgent` (profile `conversation`) had `display_mcp` set to the isolated Core and `console_mcp` set to the isolated CC. Its argv came from the real code (`evidence/brain/brain-argv.json`). The harness changes were: `--chrome` removed and `--no-session-persistence` added. The default user Claude config was used read-only, so the user-scope `jarvis-drive` and a claude.ai connector were also loaded. The brain called neither.
- **Seed** (`seed.txt`), revision 25:
  - The constellation `orion` → {budget (pinned), planning, equipe → risques (hidden)} near the left edge, all orbiting.
  - `courses` (pinned) and `idees`.
  - 4 agent stars, 3 completed and 1 running.
- **Turns.** 8 turns ran in one conversation (`evidence/brain/turns.jsonl`, readable `turns-dump.txt`). The trace sources were the stream-json events per turn, the runtime trace (`core-cc-trace.jsonl`: `display.tool`, `display.read`, `settings.tool`), Core snapshots before and after each turn, and a page sampler.
- **Cost: $0.585** in total, cumulative `cost_usd` at turn 8. Turns took 3.9–7.5 s each.

## Per-turn table

| # | User (FR) | Brain calls | Set calls | Rev Δ | Result seen by model | Reply | Truthful |
|---|---|---|---|---|---|---|---|
| 1 | Masque toute la constellation du Projet Orion. | ToolSearch(select inspect, update_many, query) → `scene_inspect{text:Orion}` → **`scene_update_many{select:{constellation:{object_id:orion}}, visibility:hidden}`** | 1 | 25→26 | 354 B typed: matched 5, changed 4, unchanged 1, `hidden_count` 1 | « …soit cinq objets, dont un qui l'était déjà. » | yes (constellation → hidden wording allowed and correct) |
| 2 | Réaffiche la constellation du Projet Orion. | `scene_query{constellation}` → **`scene_update_many{constellation, visible}`** | 1 | 26→27 | 355 B: changed 5, `hidden_count` 5 | « …cinq objets… Ça comprend Risques Orion, qui était déjà masqué avant ta première demande. » | yes |
| 3 | Déplace toute la constellation … jusqu'au bord gauche. | ToolSearch(scene_move) → `scene_query{constellation}` → **`scene_move{constellation, dx:-12, dy:0}`** | 1 | 27→28 | 445 B: 5 changed, delta −12 effective, `clamped:false`, hidden 0 | « collée au bord gauche… n'a bougé qu'un peu, parce qu'elle en était déjà tout près. » | yes (the brain computed the exact distance to the safe-area edge, −152) |
| 4 | Archive les étoiles terminées. | ToolSearch(archive) → `scene_query{kinds:[agent,job], exec_state:completed}` → **`scene_archive{same select}`** | 1 | 28→29 | 316 B: 3 archived, `cascade_ids` [] | « …les trois étoiles terminées : … » | yes |
| 5 | Désépingle tout. | ToolSearch(pin) → `scene_inspect{}` → **`scene_pin{object_ids:[orion-budget, courses], pinned:false}`** | 1 | 29→30 | 278 B | « …les deux objets qui l'étaient : Budget Orion et la liste de courses. » | yes |
| 6 | Archive l'objet zzz-inconnu. (refusal) | `scene_inspect{text:zzz}` → 0 match → **no mutation** | 0 | 30→30 | 875 B raw | « Je ne trouve aucun objet nommé zzz-inconnu… je n'ai rien archivé. » | yes |
| 7 | Ramène la constellation … vers le centre. | `scene_query{constellation}` → **`scene_move{constellation, dx:100, dy:-7}`** | 1 | 30→31 | 447 B, not clamped | « …ramené … au centre de l'écran. » | yes (stored group now spans x −52…52 around the origin) |
| 8 | Quels réglages de la scène peux-tu changer ? | ToolSearch(settings_describe) → `settings_describe{category:scene}` | 0 | 31→31 | 92 B raw text | « …le seul, l'interrupteur qui l'allume, est allumé et en lecture seule… » | yes (the env var pins it) |

- **One call, one command, one revision.** Every set operation was **one set-tool call and one Core command, with +1 revision**:
  - The runtime trace has exactly one `display.tool` per call, with op `patch_selection`, `translate_selection`, `archive_selection` or `unpin_selection`.
  - The Core snapshot revision moved by exactly +1.
  - The page saw the revision sequence 25, 26, 27, 28, 29, 30, 31 with no intermediate revision.
  - `scene_changed` was `false` on every call, so the Slice 05 rework holds: there is no false "the scene changed" hint after a filtered read.
- **No retry, no tool error, no loop**, and no `scene_update_object` per object. Nothing was delegated. There was no `agent.turn_over_budget`.
- **hidden_count wording** appeared only where the prompt allows it:
  - T1 (constellation): « dont un qui l'était déjà ».
  - T3 and T4: hidden 0, so nothing was said.
  - T5 (`scene_pin` by ids): no wording.
- **Refusal (T6).** The model checked before mutating and refused in words. The tool-level refusal wording (atomic, every offender named) was proven directly on the server by Slice 05 (`slices/05-*/qa/trace-evidence/mcp-probe.txt`). That code path is unchanged since.

## Slice 04 — six points, checked on this live trace

| # | Point | Result |
|---|---|---|
| 1 | Reads never `{"result":…}`; no `structuredContent` for inspect/query/get/describe | **PASS**: `scene_inspect` ×3, `scene_query` ×4 and `settings_describe` start with `{"scene":` or are raw text, `tool_use_result` has no `structuredContent`, and there are 0 occurrences of `{"result":` in the trace. `scene_get` was not called, so it is not verified live. |
| 2 | Mutations: `structuredContent`, compact JSON, dict key order | **PASS** for all 5 scene mutations (`tool_use_result` keys `content`, `structuredContent`, with fields in `SceneBatchResult` order). Not exercised live: Bare Hands, `settings_get`/`set`, duplicate `scene_link`. |
| 3 | ToolSearch `select:` path on the real API; no annotations or `outputSchema` in definitions | **PASS**: 5 `ToolSearch select:` calls returned `tool_reference` blocks, and display and console tools loaded. The definitions themselves cannot be observed on the real API, so a fake-endpoint capture was made with all three native servers (`evidence/inspector/parity.json`): keys are `name`, `description`, `input_schema` only, and `outputSchema`, `annotations` and `*Hint` are absent from the whole request. |
| 4 | No `output_contract` / `*_failed` | **PASS**: 0 occurrences in the runtime trace, the brain trace and the turn events. `errors.jsonl` has only the 2 intentional "Claude CLI not found" lines, from the CC brain being disabled. |
| 5 | Spoken answers correct after raw-text reads | **PASS**: counts, ids reused in the next mutation (T5 ids, T3/T7 constellation root), and names. |
| 6 | Scene-read bytes vs baseline | **PASS**. Same seed as Slice 05: `scene_inspect{text:Orion}` 1 728 B (identical), full inspect 2 094 B (identical), `scene_query{constellation}` 1 684–1 694 B (S5: 1 668–1 689 as revision digits grow). No wrapper, so the −7–15 % gain measured in Slice 04 holds. |

## Findings

| Severity | Item |
|---|---|
| FLAGGED | **The CLI rewrites `…` to `...`** in the tool definitions it sends (`scene_move` description, `settings_describe` search help). The byte count is the same, so `context_bytes` stays exact. The inspector shows `…` and the model reads `...`. This is harmless and documented in tool-contract §10.8. |
| FLAGGED / OPTIMIZATION | T5 used a full `scene_inspect` (2 094 B) where `scene_query{pinned:true}` would do. T1 loaded `scene_query` through ToolSearch without using it. Both are cheap, and Slice 05 saw the same. |

## Not verified

- The exact bytes of the deferred definitions on the real API (they are expanded server-side from `tool_reference`).
- The per-turn voice brief (`build_agent_brief`) was not included.
- A tool-level refusal reached by the model itself: the model always looks up the id first.
