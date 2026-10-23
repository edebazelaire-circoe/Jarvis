# I-001 - Points non bloquants renvoyés à la Slice 07 (agent 0, 2026-10-23)

Issus des QA indépendantes des Slices 01 et 03, acceptés non bloquants.

- S01-1 `architecture_graph.py:254-256` : `pending` silencieux quand un autre réglage vocal change en même
  temps que la délégation ; au minimum un `pending` « relance de la voix attendue » sur l'arête.
- S01-2 Concurrence : monter les routes du graphe dans la boucle aiohttp (pas d'exécuteur) ; `/api/settings`
  peut encore écraser `brain_orchestration` avec un brouillon périmé (comportement existant).
- S01-3 `realtime_frontend_session.py:92-99` : la consigne « voix seule » hors registre des prompts ; les
  empreintes de preuve de prompt ne la décrivent pas exactement.
- S01-4 Appel halluciné de délégation coupée : raison `back_brain_capacity` au lieu de « délégation coupée ».
- S01-5 Test direct de `tool_brain_wiring.resolve_mode` (env vide + bloc présent).
- S01-6 `request_voice_switch` duplique la règle de `ControlCenter.save_settings` (TODO S07).
- S03 Fournisseur de candidats du handler de rôles : brancher sur le calcul de `/api/routing/candidates`.
- S06 Harnais navigateur dupliqué (`_subagent_settings_browser.mjs` copie de `_architecture_settings_browser.mjs`) : n'en garder qu'un.
- S06 Sélecteurs anciens (réinitialisation, promotion) sans `CSS.escape`.
- S05 Montage dans le shell : `destroy()` de la fenêtre au démontage de la section (couche `position:fixed`) ;
  Échap du hub en capture (`control_center.html:~6349`) ne doit pas fermer les Réglages avant la fenêtre ;
  pièges de Tab du shell (`:~6362`) et de la fenêtre sans conflit ; placement initial qui ne couvre pas le
  nœud configuré.
- S05/S04 Ids : le fixture UI du canevas nomme le Tool Brain `tool` ; le runtime dit `tool_brain` — vérifier en
  live et aligner le fixture UI sur le fixture runtime.
