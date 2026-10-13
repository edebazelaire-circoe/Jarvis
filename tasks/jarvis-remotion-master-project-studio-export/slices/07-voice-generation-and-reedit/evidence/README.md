# Slice 07 evidence: real trace, create → whole-video export → voice edit → re-export (+ incompatible refusal)

Run `t1`, 2026-10-13, tested code `8c7c6c4a` (S7 commit) on branch `task/jarvis-remotion-master-project-studio-export`. Model
`claude-sonnet-5-5` (Claude Code 2.1.296), the Slice 13 precedent's model. Isolated Jarvis: throw-away data root and runtime under a
scratch folder, its own Core / Control Center / sandbox / Studio ports, the gate Remotion runtime 4.0.534 provisioned read-only, the
Control Center started through `harness/run_cc_strict.py` (`--strict-mcp-config`, no `--chrome`, no browser tab). Every turn is an
addressed text turn through the product's ask route (`POST /api/agent/ask`, `context.addressing: "addressed"`). The live Jarvis was never
started, stopped or contacted. **Total cost: USD 0.95** (the brain CLI's own cumulative `total_cost_usd`, sub-agents included; budget 6).

Files: `runs/t1/cli/brain.jsonl` and `cli/agent-*.jsonl` (redacted CLI sessions), `runs/t1/jarvis-trace.jsonl` (Jarvis journal, polling
rows dropped), `runs/t1/metrics.json` (every call with its result head, refusals, usage, turns and answers), `runs/t1/out/` (ffprobe +
render metadata of both MP4s, frames at 2.5 / 7.5 / 9.0 / 12.5 s of each, `frame-diff.json`). Harness: `harness/bench.py` (up, ask, wait,
jobs, probe, collect, down), `frame_diff.py`, `make_incompatible.py`, `collect_evidence.py` (redaction targets derived at runtime),
`trace_tools.py`. The MP4 files are not committed (size); their SHA-256 are in the probe files.

## The nine steps of `docs/04-testing-and-quality.md` › Voice/agent real trace

| # | Step | Evidence | Verdict |
| --- | --- | --- | --- |
| 1 | Short multi-scene video asked | turn 1 « Fais-moi une courte vidéo Remotion de trois scènes… » → brain answers in 7.3 s and starts ONE `[code] [presentation-author]` background agent (1 `Agent` call) | pass |
| 2 | Master-compatible variant created | author: `draft_guide native` → `presentation_draft_assemble` (refused once, see F1) → delivered, 3 scenes 1920x1080 @ 30, 150 frames each; the assemble result carries `master: ready, mpk_2772…, 3 scenes, 15 s, 1920x1080@30`; 3 previews, 4 frames read, 1 self-correction write (`master` in the write result, new key `mpk_337e…`); 155 s, 16 calls | pass |
| 3 | Agent knows readiness, no invented path | turn 2 « Est-ce que la vidéo entière est prête… » → brain `presentation_inspect variant` → `master.status ready`; answer: « prête… trois scènes, quinze secondes, 1920 par 1080 à 30 images par seconde. Je peux lancer l'export… si vous le demandez » (8.8 s, nothing launched) | pass |
| 4 | Explicit export → whole video, completed | turn 3 « exporte la vidéo en MP4 » → ONE `remotion_export start mp4 settings.scope master` → `video: whole`, job `scope master`, `project_key mpk_337e…`, 3 scenes. Render 34.8 s, 450/450 frames. ffprobe: one h264 stream 1920x1080, 30/1, 450 frames, 15.000 s; metadata `render_scope master`, `render_composition JarvisPresentation`, `render_project_key mpk_337e…`, `render_scene_count 3` (`out/export1.probe.json`). No audio stream (no `<Audio>` in the deck, none required) | pass |
| 5 | User asks to change one scene | turn 4 « Dans la scène 2, remplace le titre « La mouture » par « Moudre juste » et passe le fond… en bleu nuit » | — |
| 6 | Edit through the source/version path | brain: `presentation_edit scene.source_request` (request `psq_…`) + ONE background `[code]` agent; agent: `presentation_source read` → `write` (with `request_id`) → `repinned`, result `master: ready, variant_revision 3, mpk_33ed…` → `preview` → frame read; 38 s, 8 calls, 0 refusals. Brain's answer already warns « L'export MP4 en cours date d'avant ce changement. Il faudra donc le refaire » | pass |
| 7 | Key changes; second full export reflects the edit | turn 5 « Réexporte la vidéo avec ce changement » → ONE `remotion_export scope master` → new job, new snapshot, `project_key mpk_33ed…` (≠ `mpk_337e…`), 36.2 s, same ffprobe facts (`out/export2.probe.json`). Frame check (`out/frame-diff.json`, 6 fps samples, 96x54 grey, mean abs diff 0..255): scene 1 mean 0.01 (identical), **scene 2 mean 11.06** (changed on every sample), scene 3 mean 0.20 (one boundary sample 5.68, the rest ≈ 0). `export2-t007.5.jpg` shows « Moudre juste » on night blue, `export1-t007.5.jpg` « La mouture » on black | pass |
| 8 | No Studio, no claim of editing master files | no `remotion_studio` call, no Studio mention in any answer; every write is `presentation_source write` on a scene; no answer mentions a master file | pass |
| 9 | No avoidable retry loop, no scene export mislabelled | 3 `remotion_export` calls in all, each `scope master`, each labelled whole by the tool and by the brain; one refusal-and-fix in the author (F1), no loop | pass |

**Refusal control (incompatible variant).** `make_incompatible.py` assembled, as the user and without the model, a native deck « Deux
cadences » whose scenes declare 30 and 25 fps. Turn 6 « Exporte aussi la vidéo de la présentation « Deux cadences » en MP4. » → brain
`presentation_inspect overview` → ONE `remotion_export scope master` → refused `presentation_render_master_incompatible` with the § 3
sentence (« Les scènes n'ont pas toutes la même cadence… »), « Rien n'a été exporté ni modifié », and the scene-export offer. Brain's
answer (8.4 s): « L'export… est refusé… Rien n'a été exporté. Je peux en revanche exporter les scènes une par une en MP4, mais ce ne serait
pas la vidéo entière. Voulez-vous que je le fasse ? ». Checked after: no snapshot and no video for that presentation, variant revision
still 1, plan still `incompatible / master_fps_mismatch` (nothing auto-mutated, no scene export launched without the user).

## Trace analysis (agent-trace-analysis axes)

- **Functional / architecture**: the brain orchestrates (2 background agents, 3 exports, 2 inspects, 1 source request); authoring and the
  edit go through `presentation_draft_assemble` and `presentation_source`; readiness is read from the `master` block (the projection of
  `MasterProjectReader.live_plan`), never inferred; export uses `scope: master`. The project key chain is visible in the traces: rev 1
  `mpk_2772…` (assembled) → rev 2 `mpk_337e…` (author's own fix; first export) → rev 3 `mpk_33ed…` (user's edit; second export).
- **F1 — MINOR (inherited, not Slice 07)**: the author's first assemble was refused by the isolation guard, `markup_tag` on a TSX line
  (`<Frame step={1}>`: the guard's known case-insensitive tag filter; `ISOLATION_HINT` names `Frame` explicitly and the model still used
  it). Fixed in one resubmission (renamed `Cadre`).
- **F2 — OPTIMIZATION**: the edit agent called `remotion_status export` on the first job (not needed for the edit). The edit agent was
  started as `[code]` without the `[presentation-author]` marker, so it got no playbook and read `docs/OPERATIONS.md` (as the brain prompt
  says); the Slice 07 bullet there is what it saw about the whole video. Harmless here.
- **F3 — FLAGGED**: `ToolSearch` before the first use of each deferred MCP tool (3 in the brain, 1 per agent) is the CLI's deferred-tool
  loading, not a retry.
- Errors / recovery: one refusal (F1) fixed at once; the incompatible refusal is intentional and was said with its words; no hidden failure,
  no fallback, no repeated call. Missing evidence: per-message output-token counts in the side chains are partial (the cost figure is the
  CLI's own).

## Inherited observations and optimization notes (Slice 07 QA polish)

Warnings in `runs/t1/jarvis-trace.jsonl`, none caused by Slice 07 code (the brain's turn pacing and the relay of background results are
older mechanisms):

- **Three `agent.turn_over_budget`** (budget 8 s): brain turns of **8.8 s**, **12.2 s** and **8.3 s** (« travail fait dans le tour au lieu
  d'un sous-agent »).
- **Two `core.brain.notice_dropped`** (`reason: no_current_source`): background-agent relays with no current intention to say them in.
  The harness drives addressed text turns through the ask route, with no voice source to speak into.

Optimization notes (no behaviour change asked of this Slice):

- **Needless status call** (F2): the edit agent called `remotion_status export` on the first job; nothing in an edit needs it.
- **Repeated `ToolSearch`** (F3): one deferred-tool load per MCP tool before its first use (3 in the brain, 1 per agent); batching the
  `select:` list into one call would save round-trips.
- **`Frame` guard refusal despite the hint** (F1): `ISOLATION_HINT` names `Frame`, the author still wrote `<Frame>` and was refused
  `markup_tag` once before renaming it `Cadre`; the hint is not salient enough at authoring time.
