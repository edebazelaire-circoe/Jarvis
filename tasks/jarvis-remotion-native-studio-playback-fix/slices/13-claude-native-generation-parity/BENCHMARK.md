# Slice 13 — Remotion parity benchmark: Jarvis agent vs Claude in a plain Remotion project

Tested code: task branch, before = `40cb68a8` (HEAD at dispatch), after = the `S13:` commits (`aa061dba` … final). Model on both sides:
`claude-sonnet-5-5` (Claude Code 2.1.296), chosen for the USD 15 budget (decided by agent 0's Work Agent: same model on both sides
matters more than the model; the user's own Jarvis runs `opus` by default). Raw traces, sources, frames, metrics:
[`evidence/`](evidence/README.md). Trace analysis: [`evidence/trace-analysis.md`](evidence/trace-analysis.md). Quality is NOT claimed
here: it is HV-RFX-13-01 (blinded decks in `evidence/blind/`).

## 1. Controlled prompts (SLICE step 1)

One template, two topics, word for word the same on both sides (`evidence/harness/briefs.json`); the only difference is where it is said
(Jarvis: an addressed text turn through `POST /api/agent/ask`; direct: `claude -p` started in the project folder):

> Crée une courte présentation vidéo Remotion de 4 scènes, environ 40 secondes au total, en 1920x1080, qui présente {sujet} à {public}.
> Seule source de vérité : le fichier {pack}/README.md ; n'invente aucun chiffre, nom ni fonctionnalité qui n'y soit pas. Direction
> artistique : fond sombre, sobre, typographie nette, une seule couleur d'accent, animations soignées (entrées échelonnées, schémas ou
> éléments animés plutôt que des listes de puces). Textes à l'écran en français et courts. N'installe aucune dépendance : utilise
> seulement react et remotion. Quand c'est prêt, dis-moi en une phrase où la voir.

| Topic | {sujet} | {public} | Source pack (same file both sides) |
| --- | --- | --- | --- |
| Jarvis | JARVIS, l'assistant vocal local de ce poste | des développeurs qui le découvrent | the repository `README.md` (sha256 in each run's `meta.json`) |
| iGuard | IAGuard, l'agent documentaire souverain | un DSI qui évalue l'outil | the user's IGuard `README.md` (not committed; sha256 in `meta.json`) |

Isolation: Jarvis = a throw-away data root, its own Core / Control Center / sandbox / Studio ports, the gate Remotion runtime provisioned by
junction (read only), the Control Center started through `harness/run_cc_strict.py` (`--strict-mcp-config`, no `--chrome`, no browser tab);
direct = a throw-away project (gate `package.json`, `node_modules` entries junctioned one by one so the webpack cache stays in the project),
`claude -p --safe-mode --strict-mcp-config` (no CLAUDE.md, skills, plugins, hooks or memory of the user's home), `npm install`/`create`
denied. The live Jarvis was never started, stopped or used.

## 2. Affordances (SLICE step 2)

| Affordance | Direct Claude in a Remotion project | Jarvis BEFORE (`40cb68a8`) | Jarvis AFTER (Slice 13) |
| --- | --- | --- | --- |
| Source access | files on disk, Read/Write/Edit, any layout, one `Root.tsx` with all compositions | TSX only as JSON strings inside ONE `presentation_draft_assemble` call; no edit of its own scenes afterwards (needs a user turn: `scene.source_request`) | same draft call, `brief.authoring: native`; then `presentation_source read/write` on the scenes it created (no user turn, validated route) |
| Dependencies | whatever is installed (here the gate set, installs denied); `npx` still fetched `tsc` from the registry once | `react`, `remotion` only (`SCENE_ALLOWED_IMPORTS`) | unchanged (no trust widening) |
| Design references | the brief and the README | the brief, the Board, a production dossier, `props.theme` + `./jarvis-kit` mandatory | the brief and the sources; `theme`/kit optional |
| Visual check | `npx remotion still` + Read of the PNG (4–5 frames read per run) | none: no preview tool; review on structure and source text only | `presentation_source preview` (guarded render host) + Read of the JPEG (6–12 frames read per run) |
| Prompt the author receives | Claude Code's own system prompt, no project instructions | the author playbook + the full planner (`PLANNER_PROMPT`, 9 000 chars): 17.4k chars of brief | author playbook with the native loop: 9.7k chars (budget test ≤ 7 000 chars for the playbook itself) |
| Instruction budgets / truncation | none hit | planner budget 9 000 chars; brain asked for short briefs; no truncation observed | same; the `jarvis-presentation` tool catalogue grows 19 138 → 20 888 B (budget 21 000 B) |
| Restricted schemas | none | exact brief + draft schema, 66 gate rules, 48 checked per submission; text in props, colours from `theme`, controls, cues, spoken score | native profile: 18 blocking rules (validity, safety), 23 guided-model rules off, the rest warnings; score, roles, art direction optional |
| Permissions | bypassPermissions in a throw-away folder | brain bypassPermissions; agent writes Core only through its tools | same |
| Roles | one agent | brain → brief → author → review → author again | brain → one author (brief / review only when useful) |

## 3. Results per run

`calls` = tool calls of the agent(s) doing the work (brain excluded); `refused` = tool results that were errors or refusals; `avoidable` =
those a better first attempt would not have caused (environment faults are counted apart); elapsed = from the request to the last tool
result of the work (direct: the CLI's own `duration_ms`); cost = the CLI's `total_cost_usd` (cumulative per session; for Jarvis it includes
the brain and every sub-agent).

| Run | Side, topic | Code | Success | Calls | Refused (avoidable / environment) | Frames read by the agent | Elapsed | Cost USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| d-jarvis-1 | direct, Jarvis | — | yes, 1 composition, MP4 rendered | 13 | 1 / 0 (bash heredoc quoting) | 4 | 310 s | 0.400 |
| d-jarvis-2 | direct, Jarvis | — | yes | 12 | 2 / 0 (heredoc; `ls out` on a missing folder) | 4 | 150 s | 0.343 |
| d-iguard-1 | direct, iGuard | — | yes | 19 | 1 / 0 (heredoc) | 5 | 182 s | 0.468 |
| d-iguard-2 | direct, iGuard | — | yes | 14 | 1 / 0 (heredoc) | 5 | 444 s | 0.417 |
| j-base-jarvis | Jarvis BEFORE, Jarvis | `40cb68a8` | deck delivered, never looked at; review asked for fixes; the 2nd author could not edit and built a SECOND deck | 76 (4 sub-agents) | 15 / 0 (13 draft refusals incl. 4 schema probes "Sonde", 2 `inspect composition` misuses) | 0 | 1 244 s | 3.924 |
| j-native-jarvis | AFTER, Jarvis | `aa061dba` | deck delivered; author stopped and said it could not preview | 9 | 1 / 4 (`strict_content` in the brief / data root path > 260 chars for Chrome) | 0 | 185 s | 0.556 |
| jn2 | AFTER, Jarvis | `4ea12e00` (guide fix) | interrupted: Core and Control Center killed from outside during the 2nd preview | 11 | 2 / 3 (isolation guard read components `Frame`/`Link` as forbidden tags / Core unreachable) | 0 | 253 s | ≈0.55 (est.) |
| jn3 | AFTER, Jarvis | same | interrupted the same way | 9 | 0 / 2 | 0 | 183 s | ≈0.42 (est.) |
| **jn4** | **AFTER, Jarvis** | `4ea12e00` | **yes: 1 assemble accepted, 4 scenes previewed, 2 fixed after viewing (a box touching the edge, an empty lower half), re-previewed** | **18** | **0 / 0** | **6** | **326 s** | **0.562** (+0.05 for the two `remotion_studio` turns) |
| ji1 | AFTER, iGuard | `4ea12e00` | yes; 2 scenes fixed after viewing | 25 | 1 / 0 (scene key with a capital) | 12 | 514 s | 0.834 |
| **ji2** | **AFTER, iGuard** | `2e716732` | **yes: first assemble accepted, 1 scene fixed after viewing (a stray arrow head)** | **18** | **0 / 0** | **8** | **378 s** | **0.717** |

Estimated (jn2, jn3): the stack died before the CLI's cumulative cost was reported; the sub-agent's tokens were priced like jn4's.
**Total real-model spend: about USD 9.3** (direct 1.63; Jarvis 7.6 of which 3.9 the baseline).

## 4. Comparison

- **Avoidable retries.** Direct: 1, 2, 1, 1 (mean 1.25), always the same bash heredoc quoting error before falling back to Write. Jarvis
  after: the final runs of both topics have **0** (jn4, ji2); every avoidable refusal seen on the way was traced to its cause and removed
  (brief key list, key format, component names the guard refuses, 23 irrelevant warnings). Jarvis before: 15. **Acceptance met: Jarvis
  succeeds on the same brief with no more avoidable tool retries than the direct workflow.**
- **Normal editable Remotion code works**: the Jarvis decks are plain React/TSX with their text, colours and helpers in the source
  (`evidence/runs/jn4/sources`, `ji2/sources`), assembled through the native profile and refined through the validated source-edit route;
  the restricted prefab schema remains available (guided, default when `authoring` is absent) but is no longer the only path.
- **Visual check**: before, nobody in Jarvis ever looked at a frame; now the author reads 6–12 frames and fixed what it saw (jn4: 2 scenes, a box touching the edge and an
  empty lower half; ji2: 1 scene, a stray arrow head). The direct agent read 4–5.
- **Cost and time**: Jarvis after costs 1.4–1.8× direct (0.56–0.72 vs 0.34–0.47 USD) and is in the same time range (326–378 s vs 150–444 s):
  the overhead is the brain's turn and the delegation (≈0.17 USD), and each preview's bundling and browser start (30–40 s per scene on this
  loaded host). Before: 9.8× the cost and 4× the time of the slowest direct run.
- **Quality**: not judged here. The blinded frames (`evidence/blind/<topic>/deck-A|deck-B`, 8 frames each at the same relative moments, same
  size and format) are for HV-RFX-13-01; the key is `evidence/blind/key.json`.

## 5. Jarvis gates: kept or dropped for a native deck (SLICE step 4)

Kept (blocking), one line each — the same floor the source-edit gate applies to every later change of a scene:

| Rule | Why it stays |
| --- | --- |
| `brief_invalid`, `draft_schema` | a half-understood request or draft is never assembled |
| `prefab_invalid` | the candidate is valid and passes `SOURCE_GUARDS` (isolation) |
| `prefab_namespace` | the agent publishes only under `presentation-studio.` |
| `pin_unknown`, `scene_incompatible`, `score_incompatible` | pins and values resolve, or the Player / playback breaks |
| `document_invalid` | documents fit their size caps (storage contract) |
| `scene_no_score` | a scene with no score item is unreachable by playback |
| `prefab_engine_mismatch` | Remotion only; the engine is the user's choice |
| `tsx_compile`, `tsx_compile_budget`, `tsx_lint_budget` | the real compiler builds the scene in time, fail closed |
| `tsx_anchor_range` | an anchor outside the composition can never be revealed |
| `tsx_live_ref_invalid`, `tsx_live_ref_unresolved`, `tsx_inspiration_unconfirmed` | Board data and provenance security contracts |
| `behavior_risky` | network, eval, remote references said before the build (the sandbox stays the wall) |

Dropped (off for native, they judge the guided model itself): `tsx_theme_unread`, `tsx_color_hardcoded`, `tsx_text_hardcoded`,
`tsx_props_unread`, `tsx_props_undeclared`, `scene_no_controls`, `scene_unbound`, the five `control*` rules, `cue_weak`,
`cue_stopword_phrase`, `cue_nested`, `cues_sparse`, `jarvis_line_missing`, `notes_missing`, `transition_missing`, `contrast_low` (judges
colour controls), `content_thin`, `text_density`, `text_dense` (read props/data only, empty in native code). Every other rule is a warning.

Also dropped from the default *workflow*: the production dossier and the separate review (now only when useful) — the baseline trace shows
the dossier re-read the same README the author read again, and the review led to a second full deck because the author could not edit.
Kept unchanged: the Player sandbox, the Slice 12 import gate and publish, the allowed-imports list, exports as a user gesture.

## 6. `remotion_studio` answer (folded-in check, Slices 11/12 wording)

Two real turns on the jn4 stack, analysed in `evidence/trace-analysis.md` § 5:
« ouvre cette scène dans Remotion Studio » → one `remotion_studio` call with the deck just created (no `scene_id`), `needs_user`, the brain
said where to click and that it cannot open it, and which deck it assumed. « ouvre la deuxième scène de cette présentation dans Remotion
Studio » → one call with `scene_id` (scene 2), the new wording « affiche cette scène dans Variantes, puis clique… » relayed faithfully. No
claim that anything was opened; no retry. One wording nit flagged (the rail alternative may open another scene).

## 7. Harness incidents (not product defects, said so the numbers can be read)

- Long scratch data root: Chrome's profile path under `render/jobs/<job>/tmp` passed 260 characters; every render failed in
  `presentation_render_sandbox_unavailable` (run j-native-jarvis). Fixed in the harness (short root); documented as a limit in
  `remotion-render.md` § 12.
- The first stacks opened a browser tab on the user's desktop (`jarvis.app` calls `webbrowser.open`); runs jn2 and jn3 lost Core and the
  Control Center to an outside kill a few seconds after their tab was hidden (no crash log, no Windows error event; cause not proven).
  The wrapper now disables the tab; jn4, ji1, ji2 ran clean.
- The host ran out of disk once during frame capture (others' files; Remotion CLI temp bundles of this harness were removed).
