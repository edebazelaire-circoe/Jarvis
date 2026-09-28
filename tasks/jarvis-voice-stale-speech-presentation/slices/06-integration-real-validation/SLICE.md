# Slice 06 — Intégration, métriques et validation réelle

## Goal

Prouver sur une vraie conversation Live que le tour de retard a disparu, et
préparer la validation humaine.

## Context

Les Slices 02–05 sont vertes en tests. Reste à mesurer sur des sessions réelles
et à outiller la lecture du journal.

## Canonical Concepts

Journal Core `conversation_events`, timeline de conversation, testlab
Category 2, métriques de `docs/04-testing-and-quality.md`.

## Scope

### In Scope

- Script/diagnostic de mesure réutilisable sur `conversation_events` : durée
  started→fin par `completion_basis`, paroles d'intention dépassée démarrées,
  attente en file de l'intention courante, `speech_output_stalled`.
- Session réelle Live, scénario de calibration Bare Hands avec interruptions
  volontaires (reproduire la scène du 28/09 : relancer, contester un résultat,
  couper pendant une annonce) ; comparaison avec la ligne de base de la Slice 00.
- Scénario libre hors calibration (question, sous-agent d'arrière-plan,
  interruption pendant le résumé).
- `origin/main` fusionné dans la branche de tâche avant clôture
  (`git fetch` ; `rev-list --left-right --count`).
- Rédiger `HUMAN-VALIDATION.md` (Mesuré / Ressenti / Verdict).

### Out of Scope

- Nouveaux comportements.

## Dependencies

02, 03, 04, 05

## Implementation Steps

1. Outil de mesure.
2. Sessions réelles, traces archivées.
3. Tableau avant/après dans le LOG.
4. `HUMAN-VALIDATION.md`.

## Files Likely Touched

- `jarvis/testlab/**` ou `scripts/` (mesure)
- `tasks/jarvis-voice-stale-speech-presentation/HUMAN-VALIDATION.md`

## Architecture Constraints

Mesure en lecture seule sur le journal ; aucune seconde source de vérité.

## Automated Validation

Suites complètes (en paquets) vertes, hors rouges hérités listés en Slice 00.

## Acceptance Criteria

Toutes les cibles du tableau de métriques atteintes sur session réelle, ou
écart expliqué et accepté.

## Documentation Updates

LOG (avant/après), doc voix du dépôt (fin de parole Live, présentation
revalidée, interruption unifiée).

## Handoff Notes

QA : `qa-verification`, `runtime-validation`, `agent-trace-analysis`.
