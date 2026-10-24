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

## Slice 02 — Personnalisation (2026-10-24)

Ligne de base AVANT modification (worktree `r02`, HEAD `10f69d41`) : `test_personalization_profiles` +
`test_agent_behavior` + `test_control_center_settings_registry_js` 45 verts ; `test_personalization_page_browser` +
`test_settings_visual_foundation_browser` 16 verts ; `test_settings_shell_browser` 9 verts. `test_wake_word_settings_browser`
non relancé avant (seul LOG.md diffère de `af1ff5dd`, 20 verts en S01). Aucun échec préexistant.

Livré :
- Page migrée sur les primitives partagées : `.set-view` > `.set-page`, `.set-page-head`, `panel`, `row`, `range`,
  `toggle`, `textarea`, `.set-choice`, `float` + `openFloat`, `medallion`. CSS `.perso-*` doublon supprimé (carte,
  interrupteur, segmenté, préréglage, avatar, mini-bouton, select, erreur) ; restent la composition (colonnes, curseurs
  à crans, profils). `control_center.html` : bloc `.perso-*` réécrit (≈ 60 règles de moins), en-tête de la section.
- Composition de la maquette 01 : 3 colonnes (Voix + Réglages détaillés | Personnalité + Préférences rapides |
  Proactivité & rappels), profil actif en haut à droite, panneau flottant des profils ; 2 colonnes sous 1240 px de
  page, 1 sous 640. À 1672×941 toute la grille tient dans la fenêtre.
- Verbosité et formalité en curseurs à crans fidèles aux choix fermés du serveur, « Hériter » en bouton à part ;
  préréglages en groupe radio ; échéance de 15 s sur lecture et enregistrements (relecture après échéance) ; un texte
  d'instructions en cours de frappe survit au rendu d'une autre carte.
- Écarts de maquette sans donnée (documentés `docs/settings/personalization-page.md` § 2) : Écouter, volume, débit,
  Ton général, Humour, Comportement global (technicité, domaines), Technique/Créatif, 4 interrupteurs de proactivité,
  descriptions de voix, profils prédéfinis. Aucun réglage serveur ajouté, aucun schéma touché.
- Tests : `test_personalization_page_browser.py` étendu (7 tests : colonnes 3/2/1, grille visible à 1672×941,
  garde-fou anti-doublons `.perso-*`, curseurs souris/clavier/Hériter, panneau flottant focus/Échap/clic extérieur,
  états erreur/chargement/désactivé, captures).
- Preuves : `slices/02-personnalisation-ui/evidence/` (2 avant, 6 après/états, JPEG).

Après : `test_personalization_page_browser` 7 verts ; `test_personalization_profiles` + `test_agent_behavior` +
`test_control_center_settings_registry_js` + `test_settings_visual_foundation_js` + `test_control_center_shell_layers`
60 verts ; `test_settings_visual_foundation_browser` + `test_settings_shell_browser` 21 verts ;
`test_wake_word_settings_browser` 20 verts.
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

## Slice 06 — Memory Center dans les Réglages (agent d'implémentation, worktree `rmem`)

- 2026-10-24 : capture « avant » (`evidence/avant-1254x1254.png`, `avant-1280x800.png`) : Memory Center monté dans
  Sessions & Boards, liste + panneau de détail, onglet Santé des index au premier plan.
- 2026-10-24 : décision de maison (I-001, S05 de la tâche mémoire) : **une seule maison**, l'onglet Memory Center des
  Réglages (`memory_center`, vue `workbench` → `mountMemoryCenter`). `#memoryCenterMount`, la vue « étendue » de
  Sessions & Boards et leur CSS (`.wsp.mc-on`, anciennes règles `.mc-*` de la page) sont retirés ; le bouton
  « Memory Center » de Sessions & Boards reste et ouvre cet onglet (`JarvisMemoryCenter.open`). Le bouton Réglages
  du Memory Center ouvre `recall` directement : l'alias `memory` n'a plus d'appelant de code, il reste servi pour les
  liens enregistrés (appelant = `docs/legacy/settings-tab-aliases.md`).
- 2026-10-24 : `control_center_memory.js` réécrit (atelier, maquette 05) : bandeau + 4 statistiques réelles (notes
  « 200+ » au-delà d'une page, candidats en attente, sources actives nommées, état de l'index) ; onglets Notes /
  Candidats / Connaissances / Test de rappel ; table dense paginée par 10 (`limit=11`), recherche (dérivée), filtres
  appliqués au changement, note dans un `<dialog>` (Échap la ferme sans fermer les Réglages) ; rail candidats (3 +
  « Voir les N »), test de rappel, santé des index ; réglages essentiels en lecture seule avec lien vers l'onglet
  Mémoire (contrat « pas de doublon modifiable ») ; santé détaillée vers Avancé › Diagnostics.
  Décisions de candidat : confirmation dans la carte puis envoi optimiste (la carte quitte la file ; refus → elle
  revient avec code réel, `memory_center_decision_refused` journalisé). Aucun « taux de rappel », aucune rétention en
  %, aucune case de sélection multiple (pas d'action groupée côté Core).
- 2026-10-24 : la vue `center` de `JarvisMemorySettings` (bouton qui fermait les Réglages) est retirée.
- 2026-10-24 : tests : `test_control_center_memory_js.py` réécrit (10, node) ; `test_memory_settings_browser.py` :
  4 tests navigateur de l'atelier (données vivantes, pagination, filtre, dialogue + Échap ; décisions confirmées puis
  optimistes, refus remis ; test de rappel à la touche Entrée, Core muet sans chiffre ; entrées tuile / Sessions &
  Boards / « Modifier ») remplacent les 2 anciens tests Sessions & Boards ; `test_memory_settings_endpoints`,
  `test_control_center_memory_settings_js`, `test_control_center_settings_registry_js` adaptés.
- 2026-10-24 : captures « après » : `evidence/apres-notes-1254x1254.png`, `apres-notes-1672x941.png`,
  `apres-notes-1280x800.png`, `apres-bas-1254x1254.png` (réglages essentiels, test de rappel, santé),
  `apres-candidats-1254x1254.png` (confirmation + détail), `apres-degrade-1254x1254.png` (Core muet).
- 2026-10-24 : tests lancés : rapides mémoire/registre/couches 79 passés ; `test_memory_settings_browser` 15 passés ;
  `test_settings_accessibility_browser` 17 passés ; balayage des 82 fichiers non navigateur `control_center|settings|
  memory|workspace` : 2681 passés, 8 échecs dont 7 **préexistants** (identiques sur la copie de `3ed0e5af` :
  `test_control_center_mcp_api` ×6, `test_barehands_tools_settings_js` ×1 — `role="radiogroup"` de la page
  Personnalisation reprise en S2) et 1 instable sous charge (`test_memory_context` budget de temps : 38/38 passés
  seul).

## Retouches après QA des Slices 05/06 (2026-10-24)

- B1 : Core publie l'étage `knowledge:skill` (singulier, `AssetKind.SKILL`) ; l'interface cherchait `knowledge:skills`
  (clé des étages DÉDUITS des réglages, `memory_relay.py`). Carte Skills de l'onglet Connaissances : étage Core
  explicite par source (`SOURCES`) ; libellés et icônes du Memory Center sur `knowledge:skill`. Le faux Core
  `_memory_center_fixture.py` dérive désormais ses étages de connaissance de `AssetKind` ; l'assertion « Skills :
  Actif » du test navigateur couvre la vraie clé.
- B2 : `memory_advanced` (Avancé › Architecture & compatibilité › Mémoire) attendu par
  `test_settings_shell_browser` et `test_advanced_settings_browser` ; tableau des groupes de
  `docs/settings/navigation-registry.md` à jour.
- N1 : pastille Tencent de l'onglet Connaissances : Désactivé (préférence) / Actif / Indisponible ou En panne (activé,
  état Core non ok) / « Activé · état inconnu » (Core muet).
- N2 : refus d'une décision de candidat : avis en français (« ce candidat a déjà été décidé ou a changé
  entre-temps »…), code brut en détail technique, puis relecture de la file et des compteurs.
- N3 : filtre mort `foreign` / `data-memory-center` retiré de `control_center_workspace.js` (et l'attribut du
  Memory Center) ; `docs/settings/memory.md` ne cite plus `#memoryCenterMount` ; aides et remèdes mémoire
  (`memory_settings.py`, `memory_relay.py`, `docs/OPERATIONS.md`, `docs/memory-tencent.md`) disent
  « Réglages › Plugins & MCP › Fournisseurs », la vraie destination du bouton.
- Tests : `test_memory_settings_browser` 15 passés ; `test_settings_shell_browser` + `test_advanced_settings_browser`
  17 passés ; `test_settings_accessibility_browser` 17 passés ; rapides (`test_control_center_memory_js`,
  `test_control_center_settings_registry_js`, `test_control_center_memory_settings_js`, `test_memory_settings_surface`,
  `test_memory_settings_endpoints`, `test_memory_settings`, `test_control_center_shell_layers`) 252 passés ; tests du
  module Sessions & Boards (`test_boards_hud_js`, `test_presentation_artifacts_docs`, `test_workspace_presentations_js`,
  `test_workspace_rail_model_js`) 69 passés.


## Agent 0 — intégration (2026-10-24)

- S02 et S03 APPROUVÉES par la QA (aucun bloquant) et fusionnées. Après fusion, agent 0 a trouvé une régression S03 (`test_control_center_shell_layers.py::test_every_rank_in_css_matches_the_registry`, z-index `.sar-*` hors registre) : renvoyée, corrigée (`01f967e3`), fusionnée (`e4d5bf1d`).
- S05/S06 : QA avec essai réel en bac à sable (vrai Core) → REPRISE (B1 clé `knowledge:skill`, B2 tests Avancé/shell) ; corrigées (`8bc39b13`, `468e1463`), revérifiées par agent 0, APPROUVÉES, fusionnées (`4ae49d1a`).
- Contrôle agent 0 sur la branche d'intégration : 65 tests rapides + `test_memory_settings_browser.py` et `test_personalization_page_browser.py` (22) + couches du shell (12) verts.

### Lot de finitions pour S07 (non bloquants des QA)
- Fondation : `.settings-shell .content h3` (`control_center.html` ~1072) et `.content h3` (~1349) écrasent `.set-panel-title` → exclure les titres de panneau en fondation, puis retirer le contournement `.sar-board .set-panel-head h3.set-panel-title`.
- Cohérence de mise en page : Personnalisation est une page pleine (grand titre, sans rail) alors que Mémoire, Sous-agents, Architecture restent dans le shell à rail ; trancher une seule présentation conforme aux maquettes (grand titre, fil d'Ariane, onglets de page) sans casser la navigation du hub.
- Migrer les contrôles locaux de Mémoire / Memory Center (interrupteur, curseur, cartes de mode, pastilles) vers les primitives `.set-*` ; `.mcpp-switch` → `.set-switch`.
- Retirer `.sar-side` / `.sar-summary` devenues inutiles.
- S02 : tests manquants (refus → restauration, échéance 15 s, brouillon d'instructions préservé, piège Tab) ; commentaire `control_center.html:871` (1080 → 1240 px) ; course possible `control_center_personalization.js:220` ; aides des rappels tronquées sans info-bulle ; espace vide en bas de « Réglages détaillés ».
- S03 : une cellule `guarded` n'affiche pas le code d'erreur.
- S05/S06 : test automatisé de la pastille Tencent (N1) ; valeurs navigateur préexistantes (`max=10` du test de rappel alors que Core accepte 50, libellés `LEVELS`/`RETENTIONS`/`KINDS`) ; `memoryCenterTab` non consommé si l'ouverture échoue.
## Slice 04 — Architecture (2026-10-24)

Ligne de base AVANT modification (worktree `r04`, HEAD `10f69d41`) : tests Python `*architecture*` / `*brain_config*`
+ registre + couches du shell 180 verts ; `test_architecture_settings_browser` + `test_brain_config_panel_browser`
20 verts ; `test_architecture_agents_settings_browser` + `test_settings_visual_foundation_browser` 21 verts. Aucun
échec préexistant.

Livré :
- Canevas (`control_center_architecture_settings.js`) : bandeau de trois cartes `.set-panel` (État du système, Règles
  d'architecture, Actions rapides) calculées depuis le snapshot ; canevas en pleine largeur (au plus 3 colonnes),
  inspecteur flottant au bord opposé à l'élément choisi (absent sans sélection, sous le canevas en colonne unique) ;
  liaisons colorées par canal avec lueur (jetons `--set-*`), mutabilité toujours dite par le trait ; nœuds à médaillon
  lumineux, nœud configuré marqué (cadre pointillé) ; journal d'architecture (`adapter.loadJournal`, `GET /api/trace`
  filtré `architecture.*` / `brain_config.*`, sans `*.read`) avec états chargement/vide/erreur/indisponible ; légende
  des canaux présents + mutabilité ; « Réinitialiser la disposition » en deux temps (`positions: {}`, aucune liaison
  écrite). Le focus et les défilements (canevas, règles, journal) survivent aux rendus ; le journal ne remplace que sa
  carte.
- Fenêtre du cerveau (`control_center_brain_config_panel.js`) : verre flottant de la fondation, surtitre
  « Configuration », médaillon, `.set-select`, `.set-btn`/`-primary`, segments à la teinte du nœud ; événements
  `brain-config:shown` / `brain-config:closed`. Champs, brouillon, PATCH successifs inchangés.
- `control_center.html` : une seule ligne (`subagentsTarget:'subagents'` au montage du canevas).
- Doc : `docs/settings/architecture-tab.md` § 3 (composition, sémantique visuelle, éléments écartés),
  `docs/settings/brain-config-panel.md` § 1 et § 5.
- Tests : nouveau `test_architecture_workspace_browser.py` (4) ; `test_architecture_settings_browser.py` : colonnes
  attendues à 1100 px = 3 (le canevas n'est plus partagé avec l'inspecteur), cas 800 px = 2 ajouté.
- Preuves : `slices/04-architecture-agents-architecture-ui/evidence/` (2 avant, 6 après, JPEG).

Écartés de la maquette (aucune donnée ni action réelle) : latence moyenne, requêtes/min, presets charger/sauvegarder,
puces de responsabilités des nœuds, filtre « Tous les modules » et pause du journal, curseur continu de délégation
(le contrat a 5 niveaux).

Après : 180 + 20 (+4 cas de colonnes) verts ; `test_architecture_workspace_browser` 4 ; `test_architecture_agents_settings_browser`
9 ; `test_settings_visual_foundation_browser` 12 ; panneau/registre/shell/montage 72. Instabilité vue une fois (focus
perdu sur une règle par la relecture du journal) : corrigée (`renderJournal`, clés de focus), test ajouté.

Risques de fusion : `control_center.html` touché d'une ligne (montage du canevas) ; les deux modules et leurs docs
sont propres à la Slice 04.

## Slice 04 — reprise avant fusion (2026-10-24)

- Bloquant QA : avec 3 colonnes, la fenêtre du cerveau s'ouvrait au bord gauche (y = 8) sur « Toutes les
  catégories », l'onglet, le titre et le rail. Nouvelle position initiale (`initialPos`, option `zone`) : côté du nœud
  qui a le plus de place, à 16 px, rétrécie jusqu'à 340 px, jamais sur le nœud, hauteur bornée à la zone ; zone
  donnée par `architecturePanelZone()` (`control_center.html` : sous `#modalTabs` + 8, à droite de
  `#settingsCategories` + 16). Mode feuille sous 720 px et glisser inchangés.
- Test ajouté (`test_architecture_workspace_browser`) : à 1672×941, 1254×1254, 1280×800, `#settingsBack`, l'onglet actif
  et le rail restent atteignables (`elementFromPoint`), fenêtre près du nœud, sans le couvrir, ≥ 340×300.
  `test_brain_config_panel_browser` : le menu de Voice s'ouvre au clavier (la fenêtre, contre Core, couvre Voice).
- Mineur : le serveur journalise la réinitialisation comme un déplacement (`architecture.layout.saved`) ; sans changer
  le contrat, le journal de la page lit `data.nodes === 0` comme « Disposition réinitialisée ».
- Tests : panneau navigateur 8, espace de travail 5, canevas statique + js + couches du shell + panneau js 81,
  `test_architecture_agents_settings_browser` + autres 59 verts. Captures `apres-fenetre-*` refaites.

## LOG Drive d'origine
# Execution log

Reserved for implementation agents. Record durable execution notes here as work is performed.

- 2026-10-24 : agent 0 — S01 APPROUVÉE après reprise (`af1ff5dd`) : QA initiale B1 (garde-fou `bindTab`) corrigé et revérifié par agent 0 (`test_control_center_settings_registry_js.py` 20/20), N1–N4 corrigés. Dispatch : S02 (worktree `r02`, branche `task/refonte-ui-settings-s02`) et S03 (worktree `r03`, branche `task/refonte-ui-settings-s03`) depuis `af1ff5dd` ; S04 après libération d'un créneau (≤ 3 agents, S05/S06 en cours sur `rmem`).

## Slice 03 — Sous-agents en tableau de bord (2026-10-24)

Ligne de base AVANT modification (worktree `r03`, HEAD `10f69d41`) : `test_control_center_subagents_settings_js` +
`test_subagent_role_routing_ui_js` + `test_control_center_settings_registry_js` 72 verts ; `test_subagent_settings_browser`
+ `test_architecture_agents_settings_browser` 13/14 dans un lot, `test_two_tabs_destinations_and_legacy_ids` rouge sous
charge puis vert seul (instabilité de minutage préexistante, sans lien).

Livré (`control_center_subagents_settings.js` seul côté produit ; `control_center.html` non touché) :
- Vue `roles` recomposée en tableau de bord `.sar-board` sur les primitives de la Slice 01 : Vue d'ensemble (4 tuiles
  mesurées) | Politique de délégation (états lus + renvois), lignes des rôles (modèle préféré, source, repli, outils,
  conditions, actions « … »), Matrice de routage (modèles du catalogue × rôles, rang) | Règles globales (registre +
  instantané), puis la fiche du rôle (inchangée sur le fond, en deux colonnes : mission/capacités/instructions | modèles).
- « Vue d'ensemble du routage » retirée : la matrice est la même projection en lecture seule (`showOverview` →
  `gotoModels`, `openMenu`). Projections du routage gardées (`guarded`) : une erreur reste locale.
- Écartés de la maquette (doc § 1 de `docs/settings/architecture-agents.md`) : onglet Brains, 98 %, Priorité, « Ajouter un
  sous-agent », interrupteurs de politique, coût/délai/créativité/collaboration, logos, pictogrammes d'outils.
- Doc : `docs/settings/architecture-agents.md` (table donnée → écran, écarts), `docs/subagent-roles.md` § 8.
- Preuves : `slices/03-architecture-agents-subagents-ui/evidence/` (2 avant, 5 après ; instantané figé servi par `stub`).

Après : node 89 verts (`subagents_settings_js`, `routing_ui_js`, `scene_task_graph_js`, `settings_registry_js`,
`visual_foundation_js`) ; Python rôles 104 verts (`subagent_role_routing`, `_families`, `subagent_roles`,
`architecture_settings_mount`) ; navigateur : `subagent_settings_browser` + `architecture_agents_settings_browser` 16,
`architecture_settings_browser` + `brain_config_panel_browser` 20, `settings_visual_foundation_browser` 12,
`settings_accessibility_browser` 17, tous verts.

Notes : règles `.sar-side`/`.sar-summary` de `control_center.html` devenues inutiles pour la vue `roles` (laissées pour ne
pas croiser S04 ; à retirer en S07). Constat pour la fondation : `.settings-shell .content h3` (15 px, marge 30 px) écrase
`.set-panel-title` dans `#modalContent` ; la Slice 03 le neutralise dans son `STYLE`, une correction partagée serait mieux.
