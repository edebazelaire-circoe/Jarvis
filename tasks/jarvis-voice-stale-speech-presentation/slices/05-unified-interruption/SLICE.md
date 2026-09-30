# Slice 05 — Interruption unifiée : l'utilisateur reprend la main

## Goal

Couper Jarvis pendant qu'il parle a le même effet sur la file que le couper
pendant qu'il réfléchit : plus rien d'ancien ne démarre tant que le nouveau
tour n'est pas qualifié. Aucun travail n'est tué.

## Context

- Pendant la réflexion : `_abandon_brain_turn` → `SpeechScheduler.abandon_turn`
  (corrélation abandonnée, file purgée pour ce tour, `cancel_brain_turn` Core).
- Pendant la parole : `_cancel_provider_output` + `note_interruption` (sortie
  active marquée, chaîne bloquée) ; le reste de la file reste éligible. Entre
  le barge-in et l'adressage du nouveau tour (transcription + décision), une
  parole en file peut démarrer.
- Sur Live, `cancel_output` = `suppress_playback_until_session_end` : à
  concilier (fait établi en Slice 00).

## Canonical Concepts

Barge-in, `thinking_floor`, `abandon_turn`, `note_interruption`, adressage
(`addressed` / `uncertain` / non adressé), `held_for_brain` (Slice 04).

## Scope

### In Scope

- Nouveau geste bouche `note_floor_taken()` appelé par le bridge à tout
  barge-in accepté : gel des départs (`floor_taken`, non éligible) jusqu'à :
  tour adressé/promu ⇒ règles de la Slice 04 ; tour non adressé ou rejeté ⇒
  dégel, file intacte ; aucune décision dans `floor_taken_max_s` ⇒ dégel tracé.
- Le chemin réflexion garde son abandon Core, et pose aussi le gel.
- Tracer les deux chemins sous un même évènement (`voice.floor_taken`, champ
  `while` = `speaking` | `thinking`).
- Faire passer T7.

### Out of Scope

- Annulation de jobs/sous-agents (interdite).
- Heuristiques d'adressage.

## Dependencies

00, 01, 04

## Implementation Steps

1. Freshness-check barge-in / adressage.
2. Gel, dégel, bornes.
3. Brancher le bridge (deux chemins).
4. T7 + tests : bruit non adressé ⇒ reprise ; aucun appel d'annulation de
   travail (asserté sur le faux Core).

## Files Likely Touched

- `jarvis/runtime/realtime_audio.py`
- `jarvis/runtime/speech_scheduler.py`
- `jarvis/runtime/voice_v2.py` (câblage)

## Architecture Constraints

Synchrone côté bridge (aucun await avant l'arrêt audio, comme
`note_interruption`).

## Automated Validation

T7 vert ; `test_realtime_audio_lifecycle.py`,
`test_brain_interrupted_speech.py`, suites scheduler vertes.

## Acceptance Criteria

Après une coupure, la première parole entendue répond à ce que l'utilisateur
vient de dire, ou Jarvis se tait.

## Documentation Updates

Docstrings `abandon_turn`, `note_interruption`, nouveau geste ; doc voix
(barge-in).

## Handoff Notes

QA : `qa-verification`, `code-review`, `runtime-validation` (coupures réelles
pendant parole et réflexion).
