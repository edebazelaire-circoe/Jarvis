# I-004 — Restes de la Slice 04 (QA du 2026-10-27)

- **À faire dans la Slice 06** (finitions d'interface, bon marché) :
  - M1 `jarvis/core/dossier_service.py:672` : « Afficher sur le Board » prend le nom du fichier au lieu du titre `#`, et l'aperçu commence par l'en-tête brut au lieu du Résumé.
  - M2 `dossier_service.py:253-272` : titre `#` tronqué quand l'en-tête frôle 2 Kio (10-11 sources) ; lire le titre au-delà de l'en-tête.
  - M3 : longues URL de l'en-tête coupées au bord droit (1440×900) ; retour à la ligne.
- **Accepté** : M4, l'agent a écrit « BLOQUÉ : Document non enregistré » ; le cerveau a relayé correctement.
- **Hors Slice, pour la Slice 09** : écritures de `summary.md` en plein tour au-delà du budget de temps (déjà I-003) ; l'agent du dossier de production a fouillé `CONTEXT_GLOBAL` (permis, à surveiller) ; la direction de recherche a ouvert une URL d'affiliation ; délégation de la direction de recherche jamais observée sur une question bornée ; rafraîchissement réel d'un document existant non observé.
