# Réponse coupée comptée comme entièrement dite

- **Date** : 2026-09-17
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain`

## Comportement constaté

L'utilisateur a coupé JARVIS au milieu d'une phrase. Au tour suivant, le cerveau a
considéré que toute la réponse avait été dite : « Déjà dit à l'utilisateur » portait le
texte entier, et sa propre session Claude aussi.

## Comportement attendu

JARVIS sait qu'il a été interrompu et ce que l'utilisateur a entendu. Un « oui » dit
après la première phrase d'un long texte ne vaut pas accord sur tout le texte.

## Contexte

Six réponses coupées dans la session, par exemple 1,3 s jouées sur environ 10 s.

## Pistes

- Core avait l'information (registre vocal : audio reçu et audio joué), mais ne la
  transmettait pas au cerveau. Trois coupures réelles y restaient à l'état `unknown`
  au lieu de `interrupted`.
- Correctif (2026-09-17, non commité) : `BrainContext.interruptions`, rendu en ligne
  « COUPÉ » dans la consigne du tour, et fait public ramené au début entendu
  (`jarvis/core/brain_service.py`, `jarvis/core/voice_ledger.py`).
