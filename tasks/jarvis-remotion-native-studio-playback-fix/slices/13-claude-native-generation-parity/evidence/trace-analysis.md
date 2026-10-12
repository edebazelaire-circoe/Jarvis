# Agent-trace analysis — Slice 13 (native authoring and parity benchmark)

Sources: the real traces committed in `runs/<run>/` (direct: `stream.jsonl`; Jarvis: `cli/brain.jsonl`, `cli/agent-*.jsonl` = the Claude CLI
session and sub-agent side chains, `jarvis-trace.jsonl` = Jarvis's own journal without its polling rows). Metrics derived by
`harness/trace_tools.py` into `runs/<run>/metrics.json`. Model `claude-sonnet-5-5` on both sides. Redaction: home paths, user names, image
bytes, `<system-reminder>` blocks and the CLI `init` details (skills, plugins, agents) removed at copy time.

Missing evidence, said: the hook-rewritten Agent input is not in the brain's stream (the model's own input is); it is proven instead by the
sub-agent's FIRST user message, which carries the playbook (`MÉTHODE DE PRODUCTION JARVIS`, `CODE REMOTION NATIF`). Costs of jn2 / jn3 are
estimates (stack killed before the CLI reported them).

## 1. Execution paths

**Before (j-base-jarvis, `40cb68a8`).** Brain → `[general] [presentation-brief]` (7 calls, 65 s: read the README, found an empty Board, wrote a
14.8 KB dossier) → `[code] [presentation-author]` (11 calls, 475 s: read `draft_guide`, 5 assembles, 4 refused: `brief.resources[0].kind`,
label > 40 chars, a silence item with a note, `visual` not a list, unknown data keys) → `[general] [presentation-review]` (25 calls, 140 s:
11 `presentation_inspect`, read the scene sources FROM THE DATA ROOT with Glob/Read because no tool shows a scene, 1 misuse of
`inspect composition`; verdict « à corriger ») → `[code] [presentation-author]` again (33 calls, 535 s: could not edit the scenes
— no user turn for `scene.source_request` — so it rebuilt a whole SECOND deck: 7 `draft_check` including 4 « Sonde » schema probes,
3 assembles of which 2 refused). Brain cost USD 3.92, 21 minutes, 0 frames ever looked at, 2 decks left behind.

**After (jn4, ji2).** Brain → one `[code] [presentation-author]` (≈20 s turn) whose brief carries the user's exact words and the source path
(checked in `cli/brain.jsonl`). Author: `ToolSearch` (loads `presentation_inspect`, `presentation_draft_assemble`, `presentation_source`) →
Read the README → `draft_guide` `kind: native` → ONE assemble, accepted (4 scenes, 4 multi-use `agent_authored_scene` records) → 4
`presentation_source preview` → Read 4–6 frames → `presentation_source write` on what it saw (jn4: 2 scenes, « Transcription » touching its box edge and an empty lower half; ji2: 1
scene, a stray arrow head) → preview of the fixed scenes → Read → report. 18 calls each, 0 refusals, USD 0.56 / 0.72.

**Direct (d-*).** Read the README → inspect the project (ls, cat) → a heredoc `cat > src/Root.tsx <<'EOF'` fails on quoting in every run →
Write → `npx tsc` (fetches `tsc` from the registry once, despite « n'installe aucune dépendance ») → `npx remotion still` → Read 4–5 frames
→ sometimes one fix → `npx remotion render` (MP4). 12–19 calls, 1–2 errors.

## 2. Findings

| # | Severity | Finding | Evidence | Outcome |
| --- | --- | --- | --- | --- |
| F1 | MAJOR (before) | The guided schema was the only creation path and produced 13 draft refusals and 4 schema probes on one brief | `runs/j-base-jarvis/cli/agent-ab1a…`, `agent-a9b0…` | native profile; final runs 0 refusals |
| F2 | MAJOR (before) | The author could not edit the scenes it had created (source edits need a user turn), so a review led to a second full deck | `agent-a9b0…`: 2nd `presentation_draft_assemble` delivered `pst_65d6…` beside `pst_ff38…` | `agent_authored_scene` records; jn4/ji2 fix in place with `presentation_source write` |
| F3 | MAJOR (before) | No visual check anywhere in the chain; the reviewer read TSX files from the data root with Glob/Read (bypassing the tools) | `agent-a553…` Glob/Read under `data/prefabs` | `presentation_source preview` + Read; frames read in every final run |
| F4 | MINOR (fixed) | `strict_content: true` in a native brief (the guide listed every brief key) | `runs/j-native-jarvis` 1st assemble | guide lists only native keys; test |
| F5 | MINOR (fixed) | Scene key with a capital letter refused | `runs/ji1` 1st assemble | guide states the key format |
| F6 | MINOR (mitigated) | The isolation guard (case-insensitive filter) refused React components named `Frame` and `Link` as the forbidden `frame`/`link` tags; two submissions lost | `runs/jn2` assembles 1–2 (`markup_tag`) | guide names the tags; the guard itself unchanged (trust decision, flagged to agent 0) |
| F7 | MINOR (fixed) | 23 warnings about the guided model (theme prop, props, controls) on a native deck: noise that pushes back toward the guided model | `runs/j-native-jarvis`, `jn2` reports | `NATIVE_OFF`; test |
| F8 | OPTIMIZATION | Each preview bundles the scene and starts a browser: 30–40 s per scene on this host; the agent asks for the 4 scenes at once and Core serialises them | `jarvis-trace.jsonl` `preview_done` `elapsed_ms` | bundle reuse across a variant's scenes is a possible follow-up |
| F9 | OPTIMIZATION | The author reads only some of the frames it rendered (4 of 16 in jn4's first round) | `runs/jn4/metrics.json` frames_viewed 6 | acceptable; the playbook asks for every image |
| F10 | FLAGGED | The preview answer gives the frames' real path (the junction resolved by Node), not the data-root path the request used | `runs/jn4` preview results | harmless; noted |
| F11 | FLAGGED (harness) | Long data root → Chrome profile path > 260 chars → every render refused `sandbox_unavailable` | `runs/j-native-jarvis` | documented limit (`remotion-render.md` § 12) |
| F13 | MINOR | `tsx_interpolate_unclamped` warned on calls the author says are clamped (options passed through a shared constant the lint cannot see); the author judged them false positives and moved on | `runs/ji2` author report | warning only in native; a lint limit already documented (« known misses ») |
| F12 | FLAGGED (harness) | Stacks killed from outside after their browser tab was hidden (jn2, jn3) | `runs/jn2/jarvis-trace.jsonl` ends on `core_unreachable`, no crash | tab disabled in the wrapper; cause not proven |

Error handling observed: every refusal reached the agent as a typed result with its code and words (`draft_schema` with the field,
`markup_tag` with file:line, `presentation_render_sandbox_unavailable` with Chrome's message and the opt-out — which the agent did NOT take,
correctly), and the j-native-jarvis author stopped and said it could not preview instead of claiming a review. No silent fallback.

## 3. Prompt and routing (SLICE step 5)

- The routing hook's playbook reaches the sub-agent: present in the first user message of every author (`MÉTHODE DE PRODUCTION JARVIS`,
  `CODE REMOTION NATIF`), 9.7k chars total in jn4/ji2 vs 17.4k for the guided author (planner appended).
- The brain followed the new production rule: one `[code] [presentation-author]`, no brief, no review, a short factual brief with the user's
  words and the source path; it answered the user in one sentence and relayed the result.
- First gesture of every native author: `draft_guide` `kind: native`, as the playbook says.

## 4. Retries compared

| | avoidable retries per run | runs |
| --- | --- | --- |
| direct | 1, 2, 1, 1 (heredoc quoting each time; one `ls` on a missing folder) | 4 |
| Jarvis before | 15 | 1 |
| Jarvis after, final code | 0, 0 | jn4, ji2 |
| Jarvis after, intermediate | 1 (F4), 2 (F6), 0, 1 (F5) | j-native-jarvis, jn2, jn3, ji1 |

## 5. The `remotion_studio` answer (Slices 11/12 wording)

Turn 1 « ouvre cette scène dans Remotion Studio » (jn4, after the deck): `ToolSearch` → `mcp__jarvis-remotion__remotion_studio
{presentation_id, variant_id}` (no `scene_id`: nothing was on screen) → `needs_user`, `say` « dans Variantes, clique « Remotion Studio » sous
la vidéo et confirme ; elle y tourne hors du bac à sable ». Brain: « Je ne peux pas l'ouvrir à votre place … J'ai pris la présentation JARVIS
que nous venons de créer, car « cette scène » n'était pas précisée. » — correct: no claim of opening, the risk said, the assumption said.
Turn 2 « ouvre la deuxième scène de cette présentation dans Remotion Studio »: one call with `scene_id` = scene 2 (read from the author's
report, no extra inspect) → the Slice 11 polish wording « affiche cette scène dans Variantes, puis clique … » relayed faithfully, with the
scene's title. 1 call per turn, 0 retries, ≈USD 0.02–0.03 per turn. MINOR wording nit: the brain also offers the rail's « Remotion Studio… »
as an alternative, which opens the presentation's current scene, not necessarily the one named.

## 6. Suggested follow-ups (not done here)

- A JSX-aware check for `markup_tag` (PascalCase components are not DOM elements) — a trust decision for agent 0 / Human.
- Reuse one bundle for the previews of several scenes of a variant (F8).
- `remotion_studio` with a `scene_id`: say that the rail alternative opens the current scene.
