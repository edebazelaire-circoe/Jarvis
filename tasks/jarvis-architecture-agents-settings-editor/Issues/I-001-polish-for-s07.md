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

## Sort de chaque point (Slice 07, 2026-10-23)

| Point | Sort |
| --- | --- |
| S01-1 `pending` silencieux quand un autre réglage vocal change en même temps | **reporté à la Slice 08** : touche la projection du graphe (`_voice_link_state`), pas un fichier chaud ; à traiter avec la campagne finale (cas à reproduire en bac à sable avec Voice lancée). |
| S01-2 routes du graphe dans la boucle aiohttp ; `/api/settings` qui écrase avec un brouillon périmé | **fait** pour les routes (handlers `async` de l'application du Control Center, sans exécuteur, services uniques). Écrasement : **atténué** côté page (`syncCoreCliDraft` aligne `cli.agent` / `cli.settings` après la fenêtre du cerveau Core ; `voice.architecture` n'est envoyé que si l'architecture est modifiée dans Avancé) ; le cas restant (Avancé › Architecture vocale modifié dans la même ouverture qu'une bascule du graphe) est **documenté** (`docs/settings/architecture-agents.md` § 5) et laissé à la Slice 08 : une révision sur `/api/settings` sort du périmètre. |
| S01-3 consigne « voix seule » hors registre des prompts | **reporté à la Slice 08** (preuves de prompt, hors fichiers chauds). |
| S01-4 appel halluciné : raison `back_brain_capacity` au lieu de « délégation coupée » | **reporté à la Slice 08** (runtime vocal, à vérifier sur trace réelle). |
| S01-5 test direct de `tool_brain_wiring.resolve_mode` | **fait** : `test_resolve_mode_reads_a_set_variable_first_then_the_saved_block_then_off` (variable vide, bloc présent, variable posée, défaut, valeur inconnue). |
| S01-6 `request_voice_switch` duplique la règle de `save_settings` | **fait** : règle unique `voice_switch.plan_voice_switch` / `VoiceSwitchPlan.issue`, appelée par les deux. |
| S03 fournisseur de candidats du handler de rôles | **fait** : `ControlCenter._measure_routing_candidates`, le calcul extrait de `/api/routing/candidates`. |
| S06 harnais navigateur dupliqué | **fait** : `_subagent_settings_browser.mjs` supprimé, Alt ajouté à `_architecture_settings_browser.mjs`, seul harnais. |
| S06 sélecteurs sans `CSS.escape` | **fait** : `cssId` sur `data-sar-save`, `-discard`, `-reset`, `-role` (retour), `-promote` (×2). |
| S05 montage dans le shell | **fait** : `destroy()` de la fenêtre puis du canevas au démontage ; Échap consommée par le canevas et la fenêtre (le hub n'écoute qu'affiché ; une Échap libre ferme d'abord la fenêtre) ; piège de Tab du shell inactif sur une touche déjà traitée (`defaultPrevented`) ; placement initial qui ne couvre pas le nœud (mesuré en vrai Chrome dans le shell et sur la page de démonstration). |
| S05/S04 ids `tool` / `tool_brain` | **fait** : fixture UI du canevas alignée (`tool_brain`, `brain_type: tool_brain`) ; vérifié en live : le snapshot servi en bac à sable nomme `tool_brain`. Le port `events` du fixture UI reste différent du port runtime `wake` (fixture d'interface seulement). |
