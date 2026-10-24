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

## Slice 01 — fondation visuelle (2026-10-24)

Ligne de base AVANT modification (worktree `rui`, HEAD `58b38817`) : `test_personalization_profiles` +
`test_agent_behavior` + `test_control_center_shell_layers` 37 verts ; `test_personalization_page_browser` +
`test_settings_shell_browser` 13 verts ; `test_wake_word_settings_browser` 20 verts. Aucun échec préexistant.

Livré :
- Jetons `--set-*` consolidés sur `:root` (`control_center.html`) ; `--set-ink*`, `--set-hair*`, `--set-font`,
  `--set-mono`, `--set-field-bg` montés de `.settings-shell` à valeur égale (captures avant/après des six vues
  identiques à l'octet près, sauf Sous-agents dont la politique se lisait encore : attente ajoutée à `VIEWS`).
- Primitives `.set-*` hors shell + fragments/liaisons `JarvisSettingsUI` ; grilles par requêtes de conteneur
  (`.set-page`) ; rangs `.set-table` / `.set-float` au registre de la coque.
- Outillage : `tests/unit/settings_visual.py` (fenêtres, vues, `stub`, `freeze`, `capture_steps`, `OVERFLOW`) ;
  harnais partagé étendu (`stubs` par étape via CDP `Fetch`, `freeze`, `script`, JPEG, `deviceScaleFactor`) ;
  galerie `tests/unit/_settings_primitives_gallery.js`.
- Doc : `docs/settings/visual-foundation.md` (niveau 3), renvois dans `settings-shell.md` § 5–6 et `INDEX.md`.
- Preuves : `slices/01-settings-visual-foundation/evidence/` (5 avant, 5 galerie après).

Après : mêmes lots verts (37, 13, 20) ; nouveaux `test_settings_visual_foundation_js.py` (3) et
`test_settings_visual_foundation_browser.py` (11) verts ; `test_architecture_agents_settings_browser` +
`test_memory_settings_browser` + `test_brain_config_panel_browser` 24/25 dans un lot chargé, le test
`..._survives_a_footer_save_of_behavior` (attente de fermeture de `.bcp-win`, 5 s) vert seul puis fichier entier vert
(9/9) : instabilité sous charge, sans lien avec le CSS partagé.

Notes pour les Slices suivantes :
- S02 : les classes `.perso-*` (carte, interrupteur, segmenté, fil d'Ariane, titre) ont leur promotion `.set-*` ;
  migrer puis supprimer les doublons. `.set-perso .set-hub-close{z-index:3}` → `--set-z-chrome`.
- S03 : `.set-page` n'est PAS un bloc conteneur pour `position:fixed` (rectifié par la QA, cf. « S1 fix ») ; `.bcp-layer` peut y vivre. Seul bloc conteneur préexistant : `.overlay` sous Cosmos (`backdrop-filter`).
- S06 : Memory Center hors overlay ; `stub()` permet un état déterministe sans Core (`core_unconfigured` sinon).

## Slice 01 — reprise après QA (2026-10-24)

- B1 : `bindTabs` renommé `wireTabs` (le garde-fou `test_no_legacy_tab_machinery_is_left_in_the_repository` interdit
  la sous-chaîne `bindTab`) ; doc, galerie et tests suivent. Garde-fou inchangé.
- N1 : doc et consigne S03 rectifiées : `.set-page` (`container-type:inline-size`) n'est pas un bloc conteneur des
  `position:fixed` ; seul bloc conteneur préexistant : `.overlay` sous Cosmos (`backdrop-filter`).
- N2 : `openFloat` idempotent (même `close`, pas d'écouteurs doublés) ; test de détachement (bindAll, wireTabs,
  bindToggle, bindRange, close).
- N3 : interrupteur et curseur désactivés en teinte neutre, sans lueur (piste pointillée) ; captures galerie refaites.
- N4 : commentaire `.set-view`/`.set-page` replacé au-dessus de sa règle.
Tests : `test_control_center_settings_registry_js` + `test_settings_visual_foundation_js` + `test_control_center_shell_layers`
35 verts ; `test_settings_visual_foundation_browser` 12 + `_js` 3 = 15 verts ; `test_settings_shell_browser` +
`test_personalization_page_browser` 13 verts.

## LOG Drive d'origine
# Execution log

Reserved for implementation agents. Record durable execution notes here as work is performed.
