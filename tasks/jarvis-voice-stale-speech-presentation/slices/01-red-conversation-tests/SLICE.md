# Slice 01 — Tests rouges : retard de 30 s et tour de retard

## Goal

Fixer en tests, **avant tout correctif**, les comportements attendus, afin que
les Slices 02 à 05 aient un juge objectif.

## Context

Les tests actuels encodent le comportement décidé au 19/09 (`carried_over`). Ils
ne couvrent ni une surface sans fin de sortie qui parle en file, ni une
conversation accélérée avec réponses croisées.

## Canonical Concepts

Faux de session Live (surface `requires_local_quiescence_without_output_final`),
testlab virtuel (`jarvis/testlab/virtual/`, runner `supersession`), `SpeechKind`.

## Scope

### In Scope

Tests marqués `xfail(strict=True)` avec la Slice qui doit les faire passer :

- **T1 (→ S02)** Surface Live factice : deux phrases de 2 s en file. La
  seconde démarre < 2 s + grâce + 250 ms après la première (horloge
  simulée), aucun `speech_output_stalled`.
- **T2 (→ S02)** Audio en deux rafales séparées de 150 ms (< grâce) : la
  parole suivante ne démarre pas entre les deux.
- **T3 (→ S04)** A (RESULT, intention N‑1) prête non démarrée ; nouvelle
  intention N ; B' (RESULT, N) arrive : B' est servie avant A.
- **T4 (→ S04)** Même scène, le cerveau termine son tour sans réémettre A :
  A n'est jamais dite ; trace `not_revalidated`.
- **T5 (→ S04)** Le cerveau réémet A (nouvelle parole) : dite une seule fois,
  l'ancienne tracée `revalidated_as`.
- **T6 (→ S03)** Accusé de calibration puis analyse (même évènement) : l'accusé
  n'est jamais dit après l'analyse ; l'accusé non dit expire.
- **T7 (→ S05)** Barge-in pendant une parole, A en file : A ne démarre pas
  avant la décision d'adressage du nouveau tour.
- **T8 (→ S04)** Scénario testlab virtuel « conversation accélérée » (nouvelle
  version du diagnostic `supersession`, v4, métrique
  `speech.stale_formulation_started_count == 0`) — déclaré, pas encore au vert.

### Out of Scope

- Tout correctif produit.
- Modifier les tests existants qui encodent `carried_over` (c'est la Slice 04
  qui les fera évoluer, en le justifiant).

## Dependencies

00

## Implementation Steps

1. Freshness-check des helpers de test du scheduler et du testlab virtuel.
2. Réutiliser les faux existants (sessions, Core) ; n'en créer un nouveau que
   si aucun ne simule une surface sans fin de sortie.
3. Écrire T1–T8, vérifier qu'ils échouent **pour la bonne raison** (message
   d'échec lu et consigné dans le LOG).

## Files Likely Touched

- `tests/unit/test_speech_scheduler_live_completion.py` (nouveau)
- `tests/unit/test_speech_presentation_revalidation.py` (nouveau)
- `tests/unit/test_testlab_virtual.py`, `jarvis/testlab/virtual/**` (déclaration v4)

## Architecture Constraints

Horloge et boucle simulées, aucun `sleep` réel ; pas de dépendance réseau.

## Automated Validation

T1–T8 collectés, tous `xfail` stricts ; suites existantes inchangées.

## Acceptance Criteria

Chaque comportement attendu du README est encodé par au moins un test rouge
nommé et rattaché à sa Slice.

## Documentation Updates

LOG : liste des tests, raison d'échec observée.

## Handoff Notes

QA : `qa-verification` + `code-review`. Coding : `/caveman`, `/coding-guideline`.
