# Jarvis Realtime Surface + Async Brain Orchestration Handoff

This handoff converts the voice architecture discussion into an implementation-ready migration plan for the existing Jarvis repository.

## Objective

Evolve Jarvis from a mostly single-turn Realtime loop with a blocking `claude_task` tool call into a continuous LIVE voice surface backed by a long-lived asynchronous brain owned by Jarvis Core.

The target mental model is:

- OpenAI Realtime is the mouth, ears, and reflex layer.
- Jarvis Core owns truth, intent, durable conversation state, task state, and orchestration.
- A strong brain backend can reason and coordinate work without blocking the voice transport.
- The voice surface can acknowledge quickly, then receive structured speech requests from the brain while work continues.
- The user can interrupt speech without automatically cancelling the underlying work.
- `Jarvis Mute` and inactivity close the LIVE voice surface but do not stop Core or active background work.

## Repository target

- Repository: `edebazelaire-circoe/Jarvis`
- Branch inspected: default branch (`main` at handoff creation time)
- The repository was read for this handoff but was not modified.

## Where to start

**Reprise du 12 septembre 2026 terminée côté logiciel :** lire
[FINAL-REPORT.md](FINAL-REPORT.md) et [ORCHESTRATION.md](ORCHESTRATION.md).
Le code de ce handoff est déjà présent dans `main`. Le suivi canonique est
[docs/handoff-realtime-brain/tasks/TODO.md](../../docs/handoff-realtime-brain/tasks/TODO.md).
La reprise a vérifié chaque slice et corrigé quatre régressions confirmées par revue.
Validation : 1 891 tests réussis, 4 skips attendus, release et smoke Realtime réel
réussis. La recette acoustique reste distincte.

Le plan original du ZIP est extrait dans
`jarvis_realtime_brain_orchestration_handoff/tasks/TODO.md` ; ses cases vierges
décrivent le point de départ historique, pas l'état actuel du dépôt.

## Non-negotiable boundary

`Realtime has reflexes; the brain owns truth and intent.`

Realtime may perform short turn-taking behavior, but it must not invent operational state, task progress, success/failure, or substantive results that have not been authorized by the brain.

## Handoff contents

- `grill-session.md`: reconstructed design conversation and key corrections.
- `docs/`: architecture, decisions, migration strategy, tests, event contracts, migration map, and open questions.
- `tasks/`: ordered implementation slices.
- `templates/`: task and final implementation report templates.

## Important implementation rule

For every coding task, load and follow these local skills before editing code:

- `/caveman`
- `/coding-guideline`

They are expected under `~/ai/skills/`.
