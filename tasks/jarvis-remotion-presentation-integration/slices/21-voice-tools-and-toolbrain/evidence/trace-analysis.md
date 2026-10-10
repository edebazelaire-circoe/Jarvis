# Slice 21 - trace analysis (agent-trace-analysis), `jarvis-remotion` + the structural source route

Source: real Claude (`--model sonnet`) through `claude -p` stream-json, the real prompt program `conversation_display_studio_session` (now with
`BRAIN_REMOTION_PROMPT`, 1.9 KB), the real `jarvis-display` / `jarvis-presentation` / `jarvis-remotion` servers, an isolated in-process Core, a
stand-in Control Center answering the turn attestation. Harness: `tests/replay/remotion_mcp_real_trace.py`. Two full passes:
`evidence/first-run/` (before the fixes below, $0.53) and `evidence/remotion-real-traces.{md,json}` (after, $0.55). Total about $1.08 over 20 turns:
$0.013-0.19 per turn (the estimate of $0.2-0.3 was high: the prompt is cached and a turn is 1-5 model steps).

What is real: the brain, prompts, MCP servers, Core's Presentation Studio routes (edits, source requests, engine view). What is scripted: the Remotion
CAPABILITY routes (install, render jobs): the harness Core has no local capability store, so a stateful stub serves their shapes (the real routes
are proven by the Core route tests). Not covered: the sub-agent's own HTTP edit (the rig gives it no Bash/Read), real voice, a real Control Center
page, imports (no scenario: needs the network and the allow list), upgrades (covered by scripted tool traces only).

## Execution path per scenario (final pass)

| Scenario | Tool path | Verdict |
| --- | --- | --- |
| `install-addressed` "Installe Remotion." | ToolSearch -> `remotion_setup install` (`user_request` = the user's words) -> installing | correct, minimal (1 gesture call); no status read first (the tool reads the state itself) |
| `install-ambient` (a Core-opened turn that says so) | no tool call; asks "Voulez-vous que je l'installe ?" | correct: nothing launched, a question instead |
| `install-unattested` (same words, attestation false) | ToolSearch -> `remotion_setup` -> `remotion_user_turn_required` -> says it did not start, does not retry, asks the user to repeat | correct and safe (zero Core calls: `capability_requests = []`); wording OPTIMIZATION below |
| `studio-then-export` "Ouvre le Studio sur la deuxième scène." | ToolSearch -> `presentation_inspect variant` (to read the scene id) -> `remotion_studio` (scene id from the state) -> `needs_user` | correct: says where to click and that the confirmation is the user's; never says "ouvert"; no Core open call |
| ... "Exporte ma présentation en MP4." | ToolSearch -> `remotion_export start mp4` (ids reused from the earlier read) | correct: 1 gesture call, no Board, revisions read by the tool |
| `slidecar-refusal` "Passe cette présentation en Slidecar." | no tool call; "c'est un réglage à toi, carte « Présentations · moteur »" | correct refusal, zero calls, default engine unchanged at the end |
| `props-then-source` "Mets le texte ... à « Bientôt »" | ToolSearch -> inspect variant -> inspect scene -> `presentation_edit control.set` (with `if_current`, `revision`) | props path, as required; 3 reads are the id chain (variant -> scene -> control) |
| ... "Change la couleur du titre" | no call; "aucun réglage de couleur ... je peux demander une modification de sa source. Quelle couleur ?" | acceptable: honest, asks the one missing fact; no mis-routing to `density` |
| ... "Refais la scène avec un autre style" | `presentation_edit scene.source_request` -> `applied`, `next_step` | structural path |
| `source-delegation` (Agent tool given to read the brief) | inspect -> `scene.source_request` (by the brain) -> `Agent` brief with presentation/variant/scene ids, `request_id`, "ne rappelle pas scene.source_request", the OPERATIONS.md section | correct order after the fix |

No invented ids in any trace (every id in an argument was returned earlier by a read or by the previous call). No engine argument exists to be filled.
No call to a write tool in a turn the attestation said was not the user's. Engines at the end of every scenario: `remotion` default, nothing switched.

## Findings

| # | Severity | Finding (first pass) | Evidence | Resolution |
| --- | --- | --- | --- | --- |
| T1 | MAJOR (routing / ownership) | The brain delegated BEFORE recording the source request and wrote in the sub-agent brief "presentation_edit avec scene.source_request ... puis tu édites". A background sub-agent is no longer inside the user's turn, so the new `presentation_studio_source_request_user_only` guard would have refused it, and the structural path would have been dead in production. | `first-run/remotion-real-traces.source-delegation.md` calls 1-4 | `BRAIN_REMOTION_PROMPT`: "TOI, dans ce tour, source_request ... le sous-agent n'appelle pas source_request ... donne-lui le request_id" and `presentation_edit` returns `next_step` when a request is recorded. Final pass: the brain records first, then delegates with the `request_id` and the explicit "ne rappelle pas". Test: `test_remotion_mcp_ownership.py`. |
| T2 | MINOR | `remotion_setup` result carried `capability.pinned` (component versions); the brain read "version 4.0.0" aloud (274-char answer for a one-line fact). | first-run `install-addressed` | Gesture results are compact (`pinned` only in `remotion_status`); final answer 153 chars. |
| T3 | MINOR (voice) | After `remotion_user_turn_required` the brain said "Redis-moi « installe Remotion » et je relance. Si ça refuse encore, je te dirai ce que le serveur répond": invites a retry loop on a turn that cannot succeed. | first-run `install-unattested` | Refusal sentence now says the turn is not the user's, to say in one sentence that it will do it when asked, and not to retry. Final answer: "Je ne réessaie pas. Redemandez-le-moi ..." (still invites a repeat, which is right when the turn really was the user's). |
| T4 | FLAGGED | The sub-agent brief names `docs/OPERATIONS.md` but the sub-agent in this rig has no file tool; it spent 5 ToolSearch calls and a second Agent to find it (the rig's limitation; production sub-agents have Bash/Read). The brain's first brief asked an Explore agent to search several drives for the file. | first-run calls 5-6, final calls 5-10 | The prompt now says "dépôt courant". Not measurable here: needs a real sub-agent with files. |
| T5 | OPTIMIZATION | Every turn starts with `ToolSearch` (the CLI defers MCP tools). The brain already batches the tools it needs in one `select:` query (2 tools in one call); nothing to gain in the prompt. | all | none |
| T6 | OPTIMIZATION | Studio request: 4 model steps (ToolSearch, inspect variant, studio). The scene id has to be read; `presentation_inspect choices` would not be shorter. | `studio-then-export` | none |

Unnecessary / redundant calls: none in the final pass for the addressed gestures (1 ToolSearch + 1 gesture call). Retries after a refusal: none (the one typed refusal
was not retried). Hidden failures: none; every refusal reached the final answer with its cause. Fallbacks: no Slidecar talk anywhere.

## Missing trace evidence (said, not inferred)

- The Remotion capability answers are scripted (above): a real install/export is Slice 04 / 16 evidence, not this one.
- The sub-agent's `source-edits` call and the attested `GET /agent/turn` of a real Control Center page were not exercised (stand-in, rig without file tools).
- No trace for `remotion_import` and `remotion_upgrades` with the real model (scripted tool traces cover them: `tests/unit/test_remotion_mcp_tools.py`).
- Voice: not exercised (HV-21-01).

## Suggested follow-ups

1. A typed `remotion_source` pair (read / edit) on `jarvis-remotion` that requires a pending `request_id` would give the structural route the same turn-bound ownership as the other verbs (the HTTP door of Slice 14 has no notion of turn). Needs a Core read of pending source requests; not done here (budget and Core change).
2. A real-model session with a real sub-agent (Bash + Core token) for the structural edit, in the end-to-end Slice 22 run.
