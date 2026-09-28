# Slice 02 — Fin de parole Live par preuve locale

## Goal

Une parole Live libère la bouche quand elle a réellement fini d'être jouée, et
plus jamais au bout de `OUTPUT_TIMEOUT_S` (30 s).

## Context

`SpeechScheduler._await_output` n'est libéré que par `realtime.response_done`
(`note_output_event`), que GPT‑Live n'émet jamais. Le bridge constate la
quiescence (`_play_out` → `confirm_live_output_quiescence` →
`_note_live_output_quiescent`) mais ne la transmet qu'à la surface (orbe).
Résultat : `delivery_not_complete` après 30 s, file qui s'allonge, blocage des
chaînes (`_blocked_chains`). `_wait_for_idle_output` connaît déjà le cas
`_without_output_final` ; `_await_output` non.

## Canonical Concepts

`requires_local_quiescence_without_output_final`, `_ActiveSpeech` (`done`,
`status`, `output_id`), `note_output_event`, quiescence Live et sa
réconciliation tardive (`_reconcile_live_output_drain`), registre de lecture
Core (`observe_playback`, `terminal`), `OUTPUT_STALLED`.

## Scope

### In Scope

- **Investigation d'abord** : le registre de lecture (`observe_playback(...,
  terminal=True)`, `playback_manifest`) donne-t-il déjà une fin par `output_id`
  sur Live ? Si oui, s'y brancher ; sinon, signal bridge → bouche.
- Signal par sortie : audio de **cette** sortie observé (bloc portant son
  `speech_id`/`output_id`) **puis** quiescence périphérique stable pendant
  `live_completion_grace_ms` (défaut à mesurer, ordre 300–500 ms, configurable)
  ⇒ `status="completed"`, `done.set()`.
- Audio repris pendant la grâce ⇒ la grâce repart, pas de fin.
- Aucun audio de la sortie dans `live_first_audio_timeout_s` (borné, bien
  < 30 s) ⇒ libération, statut `unconfirmed`, trace dédiée ; ni `completed`
  ni `interrupted`, et la chaîne n'est **pas** bloquée pour autant si
  l'Humain ne l'a pas coupée.
- Barge-in pendant la grâce : l'interruption l'emporte (comportement actuel).
- `OUTPUT_TIMEOUT_S` reste un filet ; son déclenchement sur Live = anomalie
  (`speech_output_stalled`, niveau warning, compté).
- Revoir la fusion des chunks Live dans `_enqueue` (`len(spans) > 1 and
  _without_output_final`) : dès qu'une fin fiable existe, décider (et tracer
  dans le LOG) si la chaîne multi-paragraphes redevient possible ou si la
  fusion reste. Par défaut : garder la fusion (hors périmètre de risque).

### Out of Scope

- Éligibilité / `carried_over` (Slice 04).
- Pipeline classique : aucune modification de comportement.

## Dependencies

00, 01

## Implementation Steps

1. Freshness-check des fonctions citées.
2. Investigation du registre de lecture ; décision consignée.
3. Implémenter le signal et la grâce ; bornes en constantes nommées.
4. Faire passer T1 et T2 (retirer `xfail`).
5. Test de parité surface classique.
6. Trace : `voice.speech.completed` avec `completion_basis`
   (`provider_response_done` | `local_quiescence` | `unconfirmed`) et
   `release_after_quiescence_ms`.

## Files Likely Touched

- `jarvis/runtime/realtime_audio.py`
- `jarvis/runtime/speech_scheduler.py`
- `jarvis/runtime/live_frontend_session.py` (si le registre de lecture est la source)
- tests Live / scheduler

## Architecture Constraints

Le bridge reste seul consommateur du flux fournisseur. Pas de nouvelle source
de vérité : si le registre de lecture Core sait, c'est lui. Aucune fin inventée
sur une surface qui émet `response_done`.

## Automated Validation

T1, T2 verts ; suites Live/scheduler/lifecycle vertes ; parité classique.

## Acceptance Criteria

Sur une session Live nominale, zéro `speech_output_stalled`, et la parole
suivante démarre au plus `grâce + 250 ms` après la fin réelle de l'audio.

## Documentation Updates

Docstrings de `_await_output`, `_without_output_final`,
`_note_live_output_quiescent` ; contrat Live dans la doc voix du dépôt.

## Handoff Notes

Parallélisable avec la Slice 03 (worktree distincte). QA : `qa-verification`,
`code-review`, `runtime-validation` (session Live réelle courte : 5 phrases
courtes enchaînées, mesure de l'écart quiescence → libération).
