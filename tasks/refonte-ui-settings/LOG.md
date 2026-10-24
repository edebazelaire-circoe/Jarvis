# LOG — refonte-ui-settings (agent 0)

- 2026-10-24 : démarrage (handle-task start). Pas de `docs/workflows/AGENT_TASK_LIFECYCLE.md` dans le dépôt : repli sur les ID de file Drive et la branche de base `main` notés en mémoire projet.
- 2026-10-24 : dossier Drive `147CbkAhZxTjct5ZX5XBwCxwTJvdU304i` trouvé dans to-do. README lu. Le serveur MCP jarvis-drive s'est ensuite déconnecté : slices/, references/ui/ (5 maquettes), docs/, Issues/, task.json, grill-session.md non encore récupérés. Worktree `../rui`, branche `task/refonte-ui-settings` depuis origin/main `be80ab9b`.

- 2026-10-24 : MCP rétabli ; archive complète téléchargée (5 maquettes PNG lisibles, 8 Slices, JSON valides, depends_on cohérents, IDs HV-* uniques). Drive : toujours dans to-do, déplacement to-do → current à faire par le Human.

## Slice 00 — porte de préparation (agent 0)

Audit aveugle de main `be80ab9b` (= origin/main, aucune dérive) :
- Shell des Réglages : tout dans `jarvis/runtime/control_center.html` (6616 l., un seul `<style>` l. 7–2225), modules `control_center_*.js` injectés par `control_center.py` (jetons `__CONTROL_CENTER_*_JS__`). Aucun fichier `.css`. Jetons `:root` (l. 8, 52), `.settings-shell` `--set-*` (835). Primitives JS `JarvisSettingsUI` (`control_center_settings_ui.js`) sans toggle ni slider ; aucun style `input[type=range]` ; seul interrupteur : `.mcpp-switch` (MCP).
- Hub de 6 cartes déjà fusionné (rebasé dans main : `ad1e7f4d`, `f8e5dbaa`) ; registre `control_center_settings_registry.js`.
- Sous-agents : `control_center_subagents_settings.js` ; Architecture : `control_center_architecture_settings.js` + `control_center_brain_config_panel.js` (CSS injectée par module). Pas d'onglet Brains (contrat conservé).
- Mémoire : 5 sections plates (`MEMORY_SECTIONS`), Memory Center hors Réglages (`control_center_memory.js`, `#memoryCenterMount`).
- Tests navigateur : Chrome sans tête via CDP (harnais `.mjs`), fixture `served` + `open_settings()` dans `tests/unit/test_wake_word_settings_browser.py`, captures via action `shot` / `JARVIS_BROWSER_SHOTS`.
- Personnalisation : page complète NON commitée dans le checkout principal → I-002 (reprise comme base S02).
- Mémoire : recoupement total avec la tâche `jarvis-memory-knowledge-settings-ui` (to-do, arrêtée en S00) → I-001 (décision différée au dispatch de 05/06).

Décisions :
- Task Type : `waived-by-agent-0` (précédents orchestration, settings-ui-reorganization, architecture-agents-settings-editor).
- Propriété des fichiers : seule S01 modifie les jetons et primitives partagés (`:root`, `.settings-shell`, `control_center_settings_ui.js`). S03 et S04 gardent leur CSS dans leur module (STYLE injecté) → parallélisables. S02 possède `.perso-*` et `control_center_personalization.js`. Chaque Slice parallèle a son worktree, fusionné dans `task/refonte-ui-settings` par agent 0.
- Fenêtres de capture : 1672×941 (maquette 01, 02, 03) et 1254×1254 (04, 05), plus 1280×800.
- Ressources : ≤ 3 agents simultanés, tests navigateur par petits lots.

**État : READY** (01–04 dispatchables ; 05/06 conditionnés par I-001 ; 07 après 02–06).

## Slice 05 — Mémoire & connaissances / onglet Mémoire (agent d'implémentation, worktree `rmem`)

- 2026-10-24 : skills `caveman`, `coding-guideline`, `impeccable` chargés. Ligne de base relevée sur une copie
  `git archive` de `3ed0e5af` : `test_memory_settings_surface`, `test_control_center_memory_settings_js`,
  `test_control_center_settings_registry_js`, `test_memory_settings_endpoints`, `test_control_center_memory_js` →
  65 passés, aucun échec préexistant.
- 2026-10-24 : capture « avant » (`evidence/avant-1254.png`, `avant-1280x800.png`) : cinq sections plates, champs bruts.
- 2026-10-24 : décisions (I-001, contrats « Locked product decisions » de la tâche mémoire) :
  - trois onglets = trois sections du shell : `recall` (libellé « Mémoire », vue `memory`), `knowledge_sources`
    (« Connaissances », vue `knowledge`), `memory_center` ; `semantic_retrieval` et `consolidation` deviennent des
    alias de `recall` (registre + `docs/legacy/settings-tab-aliases.md`) ; `memory` reste l'alias de `recall` ;
  - destinations servies : `surface` des champs recalculée côté serveur (`SURFACE_SECTIONS` section → catégorie,
    `_FIELD_SURFACE`) ; `recall.timeout_ms` et tout `tencent.*` vont dans la nouvelle section
    Avancé › Mémoire (`memory_advanced`, groupe Architecture & compatibilité) rendue par la vue `fields` existante
    — c'est le minimum pour que le bandeau « disponibles dans le mode avancé » dise vrai (la page Avancé détaillée,
    S04 de la tâche mémoire, reste hors champ) ;
  - libellés d'options servis en langage produit (`Aucun`/`OpenAI`, `Manuelle`/`Automatique`) et quatre libellés de
    champs reformulés côté serveur ; aucun libellé, borne ni option copié dans le navigateur ;
  - **pas de profil de rappel** Rapide/Équilibré/Approfondi : aucun réglage réel derrière (contrat : pas de preset
    décoratif) ; max du curseur = borne servie (10, la maquette dit 20) ; ligne « Portées » du résumé remplacée par
    « Mémoire privée » (réelle) ;
  - état vivant (`loadLive`) : `/api/memory/status`, notes (`limit=200`, « 200+ » au-delà), candidats proposés ;
    Core muet → « — (Core injoignable) », raison réelle, « Réessayer » ; une source de connaissances n'est « Actif »
    que si Core la déclare saine (graphe de code sans fournisseur : « Indisponible »).
- 2026-10-24 : CSS dans le module (`STYLE` injecté, préfixe `.mem-`, jetons `--set-*`/`--shell-*` seulement) ;
  `control_center.html` : seul le bloc `MEMORY_SECTIONS` change. Interrupteur, curseur, cartes de mode et
  pictogrammes locaux au module (exportés par `JarvisMemorySettings.icon` pour le Memory Center) : à converger avec
  les primitives de la Slice 01.
- 2026-10-24 : tests adaptés ou ajoutés (`test_memory_settings_surface`, `test_control_center_memory_settings_js`,
  `test_control_center_settings_registry_js`, `test_memory_settings_browser` réécrit pour trois onglets + état
  vivant, Core muet, sémantique sans clé, clavier, débordements aux tailles des maquettes ; faux Core
  `tests/unit/_memory_center_fixture.py`) ; `test_connections_settings_browser` et
  `test_settings_accessibility_browser` visent désormais `[data-mem-open=providers]` de l'onglet Mémoire.
  `test_control_center_shell_layers` a refusé un `z-index` non inscrit au registre : retiré.
- 2026-10-24 : contraste (`test_disabled_and_read_only_states_stay_readable`) : les boutons radio du mode de
  consolidation, d'abord masqués, sont devenus de vrais témoins visibles (coin de la carte) ; interrupteurs à l'encre
  du shell. Captures « après » : `evidence/apres-memoire-1254x1254.png`, `apres-memoire-1280x800.png`,
  `apres-degrade-haut-1254x1254.png` et `apres-degrade-1254x1254.png` (Core muet + recherche sémantique sans clé),
  `apres-connaissances-1254x1254.png`.
- 2026-10-24 : tests lancés (venv du dépôt principal, depuis `rmem`) : rapides (surface, module JS, registre,
  endpoints, Memory Center JS, couches du shell) 78 passés ; `test_memory_settings_browser` 13 passés ;
  `test_settings_accessibility_browser` 17 passés (après correctif contraste) ; `test_connections_settings_browser`
  7 passés, 3 échecs **préexistants** (mêmes 3 échecs sur la copie de `3ed0e5af` : ajout/liaison OpenAI et réponse
  tardive des Connexions, sans lien avec la mémoire).

## LOG Drive d'origine
# Execution log

Reserved for implementation agents. Record durable execution notes here as work is performed.
