# Slice 00 — Readiness et réconciliation (Project Manager)

## Goal

Établir que le diagnostic de ce handoff correspond au code courant, que rien de
plus récent n'entre en conflit, et fixer la ligne de base des tests.

## Context

Diagnostic fait le 28/09/2026 sur `202333d` à partir d'une transcription de
l'utilisateur (session 12:54–12:59) et du journal Core local (18–21/09). La
session de la transcription n'est dans aucune base locale.

## Canonical Concepts

`SpeechScheduler` (éligibilité, sélection, `_await_output`), bridge Live
(quiescence), `BrainService` (`_take_pending_replies`, `announce_notice`,
`_spoken_works`), `SpeechRequest` / `SpeechKind` / `TRANSIENT_SPEECH_KINDS`
(`jarvis/domain/v2.py`), diagnostic testlab `supersession`.

## Scope

### In Scope

- Audit à l'aveugle de `speech_scheduler.py`, `realtime_audio.py`
  (`_play_out`, `_note_live_output_quiescent`, barge-in), `live_frontend_session.py`,
  `brain_service.py`, `control_center.py` (`_analyse_calibration_event`),
  `claude_local.py` (`publish_notice`), `control_center_brain.py`
  (`next_notices`), `v2_app.py` (`_brain_notice_loop`) **avant** de lire
  `README.md` §But.
- Confirmer ou corriger chacun des 6 faits du README (lignes au snapshot).
- Vérifier le comportement `suppress_playback_until_session_end` après un
  barge-in Live (muet jusqu'à la fin de l'incarnation ?) et son interaction
  avec la file — consigner en Issue si hors périmètre.
- Demander à l'Humain la base/trace de la session du 28/09 12:54 ; à défaut,
  retenir comme ligne de base la mesure 18–21/09 (36/74 interruptions à ~30 s)
  et la recalculer.
- Balayage large des tests rouges hérités (`tests/unit` entier en paquets, au
  SHA de branchement, worktree détachée `C:/Projects/jarvis/bwt`) ; liste « pas
  à vous » dans `READINESS.md`.
- Vérifier les handoffs actifs (Drive `current`, branches) touchant voix /
  cerveau / Bare Hands calibration.
- Waiver Task Type.
- Décider un seul état : `READY`, `CONTEXT_REWORK_REQUIRED`, `CONFLICT`,
  `HUMAN_DECISION_REQUIRED`.

### Out of Scope

- Code produit. Délégation de cette Slice.

## Dependencies

None

## Implementation Steps

1. Audit à l'aveugle, puis réconciliation avec le README.
2. Mesure de ligne de base (script de lecture de `conversation_events` :
   durée started→interrupted/completed, raison, par surface).
3. Balayage des tests rouges.
4. `slices/00-project-manager/READINESS.md` (modèle :
   `tasks/jarvis-category2-test-lab/.../READINESS.md`).

## Files Likely Touched

- `tasks/jarvis-voice-stale-speech-presentation/**` uniquement

## Architecture Constraints

Aucun code produit.

## Automated Validation

Ligne de base des suites listées dans `docs/04-testing-and-quality.md`
enregistrée avec la liste exacte des fichiers et le compte.

## Acceptance Criteria

État de readiness explicite ; faits confirmés/corrigés ; ligne de base et
liste des rouges hérités consignées.

## Documentation Updates

`READINESS.md`, `LOG.md`.

## Handoff Notes

Le PM décide en autonomie, avec sa recommandation ; seuls les déplacements
Drive, les checks HV et l'acceptation finale reviennent à l'Humain.
