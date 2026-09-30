# Slice 03 — Relais spontanés typés (accusés transitoires)

## Goal

Aucun relais spontané ne devient une parole éternelle : chaque relais déclare
son genre, et un accusé est transitoire et remplacé par ce qu'il annonce.

## Context

`BrainService.announce_notice` crée toujours `SpeechRequest(kind=RESULT,
priority=NORMAL)` sans `work_id`, `supersedes_key` ni `expires_at`. Il porte
l'accusé `CALIBRATION_ANALYSIS_ACK` (« Tes résultats viennent d'arriver, je les
analyse. », publié par `ControlCenter._analyse_calibration_event` via
`ClaudeLocal.publish_notice`) **et** la réponse d'analyse du tour ouvert pour la
calibration, ainsi que les résumés de sous-agents d'arrière-plan. Ces paroles
échappent à `_spoken_works` (pas de `work_id`) et au TTL (pas transitoires).

## Canonical Concepts

`announce_notice`, `publish_notice` / `_append_notice`, `/api/agent/notices`
(`control_center_brain.next_notices`), `v2_app._brain_notice_loop`,
`SpeechKind`, `TRANSIENT_SPEECH_KINDS`, `with_default_ttl`, `supersedes_key`,
`_may_supersede`.

## Scope

### In Scope

- Étendre le chemin de relais de bout en bout (notice CLI → HTTP → Core) avec
  `kind` (défaut `result`), `supersedes_key`, `ttl_s` optionnels, `work_id`
  optionnel ; compatibilité ascendante (champs absents = comportement actuel
  **sauf** le TTL, voir plus bas).
- Accusé de calibration : `kind=ack` (ou `progress`), TTL court,
  `supersedes_key="calibration:<identifiant d'évènement>"`.
- Réponse d'analyse de calibration : même `supersedes_key` ⇒ remplace l'accusé
  s'il n'a pas démarré.
- Résumés de sous-agents d'arrière-plan : `work_id` du sous-agent quand il est
  connu (pour la Slice 04 et `_spoken_works`).
- Un relais `result` sans `work_id` reçoit malgré tout une identité de
  présentation traçable (`speech_id`) — nécessaire à la Slice 04.
- Trace `core.brain.notice_relayed` enrichie de `kind`, `supersedes_key`,
  `expires_at`.

### Out of Scope

- Politique d'éligibilité entre intentions (Slice 04).
- Texte des accusés (inchangé).

## Dependencies

00, 01

## Implementation Steps

1. Freshness-check de la chaîne complète des relais (4 fichiers).
2. Contrat de notice étendu, validé à chaque frontière (valeurs inconnues ⇒
   refus tracé, jamais silencieux).
3. Brancher la calibration (accusé + analyse).
4. Faire passer T6.
5. Tests de compatibilité : un relais ancien format est toujours dit.

## Files Likely Touched

- `jarvis/core/brain_service.py` (`announce_notice`)
- `jarvis/core/v2_app.py` (`_brain_notice_loop`)
- `jarvis/adapters/control_center_brain.py` (`next_notices`)
- `jarvis/runtime/claude_local.py` (`publish_notice`, `_append_notice`)
- `jarvis/runtime/control_center.py` (`_analyse_calibration_event`)
- `jarvis/runtime/barehands_calibration.py` (si l'identifiant d'évènement y naît)

## Architecture Constraints

Core ne fabrique aucun texte (Décision 14) ; le Control Center ne choisit que
le genre et la clé, pas la formulation.

## Automated Validation

T6 vert ; `test_barehands_calibration_*`, `test_background_failure_speaks.py`,
`test_brain_delegation.py` verts.

## Acceptance Criteria

En calibration, l'accusé est dit au plus une fois, avant l'analyse, et n'est
jamais dit après elle ; aucun relais n'est émis sans genre.

## Documentation Updates

`docs/05-event-contracts.md` du dépôt (forme d'une notice) ; docstring
`announce_notice`.

## Handoff Notes

Parallélisable avec la Slice 02. QA : `qa-verification`, `code-review`,
`agent-trace-analysis` (une calibration réelle : accusé, analyse, ordre).
