# QA S08 — code review + qa-verification

Slice : `08-presentation-product-ui` (frontend, niveau QA `ui`). Branche `task/jarvis-presentation-edition-v1-s08`,
commits `abdfeea9` + `06edfe55` au-dessus de `cf3f7e44`. Relecteur indépendant, aucun code produit modifié.
Date : 2026-10-26.

## Verdict recommandé : FAIL (1 bloquant, à reprise courte)

L'implémentation est solide et fidèle au contrat : types de Board lus sur Core, jamais devinés ; surfaces de
développement déclarées à la source et cachées sans flash par le marquage serveur ; lecture de l'édition à la demande,
bornée, sans boucle, avec « Réessayer » ; édition `full` inchangée à l'écran. Mais la Slice casse un test unitaire
existant qui passait sur la base (B1), et la LOG ne le signale pas. La correction tient en une ligne de test ; les
autres points sont mineurs.

## Périmètre relu

- Code : `jarvis/domain/product_edition.py`, `jarvis/runtime/product_edition_env.py`, `control_center.py`,
  `control_center.html` (dock, `refreshStatus`, Réglages, raccourcis, lanceur), `control_center_product_edition.js`
  (nouveau), `control_center_boards.js`, `control_center_presentation_rail.js`, `control_center_settings_registry.js`,
  `control_center_barehands.js`.
- Docs : `docs/control-center-shell.md` › *Product edition UI*, `docs/product-edition.md`, `docs/boards.md`,
  `docs/presentation-studio.md` › *Presentation home*, `docs/settings/navigation-registry.md` § 7, `docs/settings/INDEX.md`.
- Tests : `test_product_edition_ui_js.py`, `test_presentation_edition_ui_browser.py`, `test_product_edition.py`,
  `_status_centre_browser.mjs`.
- Captures : `screenshots/` (choix du type, Boards, accueil, lanceur, hub des Réglages ; 1440×900, 1280×720, 600×800).

## Preuves (exécutées par ce QA, `.venv` du dépôt principal, en avant-plan, par lots)

| Lot | Résultat |
| --- | --- |
| `test_product_edition_ui_js.py` + `test_product_edition.py` | 55 passés |
| `test_presentation_edition_ui_browser.py` | 11 passés (2 min 37) |
| `test_boards_hud_js`, `presentation_rail_js`, `settings_registry_js`, `settings_shell_js`, `shell_layers` | 86 passés, **1 échec** (B1) |
| `test_boards_card_browser` + `test_control_center_presentation_rail_browser` | 39 passés, 1 échec intermittent (F1) |
| `test_settings_shell_browser` + `test_global_launcher_browser` | 15 passés |
| `test_status_centre_browser` + `test_boards_hud_browser` | 45 passés |
| `test_presentation_rail_e2e_browser` + `test_settings_message_destinations_browser` | 4 passés, 1 échec connu de main |
| `test_control_center_*` / `*settings*` / `test_barehands*` hors navigateur (101 fichiers) | 2429 passés, 1 sauté, 4 échecs : B1 + 3 préexistants (F2) |

Comparaison avec la base : worktree détaché temporaire de `cf3f7e44` (créé puis supprimé au scratchpad). Sur la base,
`test_control_center_settings_shell_js.py` passe en entier (4/4) ; `test_refus_perime…` passe 2 fois sur 2.

## Findings

### BLOQUANT

**B1 — Test unitaire rendu rouge par la Slice.**
`tests/unit/test_control_center_settings_shell_js.py:155`
(`test_navigation_is_drawn_from_the_registry_and_cycles_categories`) exige
`"function settingsTabs(){" in page and "registry.CATEGORIES.map(" in page`. La Slice remplace ce code par
`registry.categoriesFor(settingsEditionOptions()).map(` (`jarvis/runtime/control_center.html:6668-6670`).
- Scénario : `pytest tests/unit/test_control_center_settings_shell_js.py` → `AssertionError` à la ligne 155.
- Preuve : échoue toujours sur la branche ; passe sur `cf3f7e44`. Il n'est pas dans la liste des échecs connus de main.
  La LOG S08 annonce de larges lots verts mais ne cite pas ce fichier.
- Correction attendue : mettre à jour cette assertion de contrat statique (`categoriesFor(`) et y ajouter le cas
  `options` de `cycleCategory`. Ce test protège la règle « aucune liste de catégories recopiée » : il faut l'adapter,
  pas le supprimer.

### MAJEUR

Aucun.

### MINEUR

**M1 — Une porte de développement reste ouverte en édition Presentation, sans suivi.**
Dans Variantes, l'explorateur garde le bouton « Remotion Studio » et ses textes
(`control_center_presentation_studio_explorer_remotion.js:122,198`), ainsi qu'un message qui renvoie vers une surface
désormais cachée : « carte « Présentations · moteur », onglet « Plugins externes » du dialogue MCP » (`:189`).
- Scénario : édition `presentation`, sans mode développeur ; ouvrez une présentation, Variantes, puis le bouton
  « Remotion Studio » : il reste proposé. Si Remotion n'est pas prêt, le message renvoie vers un dialogue MCP
  introuvable.
- La doc reporte « the wording inside Variantes » à la Slice 09 (`docs/presentation-studio.md` › *Presentation home*,
  « Out of scope ») et l'inventaire classe Variantes en `product`. Mais le `SLICE.md` de la Slice 09 ne mentionne pas le
  masquage des surfaces de développement : le point risque de tomber entre deux Slices. Recommandation : l'inscrire
  dans `Issues/` (I-005) ou dans les notes de la Slice 09, et marquer ce bouton `data-surface="developer"` dès la S09.

**M2 — Un message de la carte Board renvoie vers une page cachée.**
`jarvis/runtime/control_center_boards.js:471` (`PRESENCE_TEXT.refused.said`) dit : « Changez-la dans Réglages › Avancé
& Diagnostics › Architecture & compatibilité. ». En `presentation`, cette catégorie est cachée et la cible ouvre la
première catégorie montrée. C'est une impasse pour l'utilisateur, avec du jargon (« Duplex », « PRESENTATION »). Le texte
existait avant la Slice, mais c'est la Slice qui le transforme en impasse. Le même motif se retrouve dans 18 textes
« Réglages › Avancé/Plugins/Architecture » du dépôt (`app.py:1173,1239`…), dont une partie ne touche que l'opérateur.

**M3 — Le délai dépassé côté relais n'est pas lu comme une issue inconnue.**
`control_center_presentation_rail.js:69` (`CREATE_ERRORS`) ne connaît pas `core_timeout` (le 504 du relais du Control
Center). La table du moteur, elle, le connaît (`control_center_presentation_studio_engine.js:39-50`).
- Scénario : Core met plus longtemps que le délai du relais à créer. Le rail affiche alors « Création impossible :
  <message brut> » au lieu de « l'issue est inconnue, la liste est relue ». Il laisse croire à un échec alors que la
  présentation a peut-être été créée.
- Réutilisation : cette table recopie en partie `ERRORS` du moteur, avec une formulation « produit ». C'est acceptable
  pour le ton, mais la liste des codes devrait venir d'une source unique.

**M4 — Une lecture de l'édition tombée reste muette dans le rail.**
`control_center_presentation_rail.js:160,659` : l'accueil n'existe que si l'édition lue n'est pas `full`. En
`presentation`, si `/api/boards/edition` échoue, un Board Présentation vide garde son rail caché
(`shouldShow` → `false`) : ni cause, ni « Réessayer » à cet endroit. La reprise en arrière-plan existe tant que Core
sert ses Boards, mais la LOG (« une lecture tombée affiche sa cause et « Réessayer » ») ne vaut que pour l'écran du
choix du type.

**M5 — Le marquage de page illisible n'est journalisé nulle part.**
`jarvis/runtime/product_edition_env.py:44` attrape `Exception` sans log. Sa docstring dit « la page le dit à la
console », mais `control_center_product_edition.js:72,92` traite `data-product-edition="unreadable"` comme une page
non marquée, sans aucune ligne de journal. L'effet reste borné (Core refuse de démarrer avec la même valeur), mais la
promesse de la docstring est fausse.

**M6 — Rejet non géré possible.**
`control_center_product_edition.js:135-138` : si `fetch` répond avant l'échéance mais que `response.json()` dépasse
8 s, la promesse `deadline` rejette après la fin de la course et produit un `unhandledrejection` ; la cause est alors
dite « réponse illisible » au lieu de « timeout ». C'est rare, mais facile à corriger (`.catch(()=>{})` sur `deadline`,
ou une échéance qui couvre aussi la lecture du corps).

**M7 — Trous de test.**
- Aucun test navigateur de `JARVIS_DEVELOPER_MODE=1` (page `presentation` marquée `visible`, outils rendus). Seule la
  fonction Python est couverte (`test_product_edition.py:77,560`).
- `test_full_edition_is_unchanged` sert une page **non marquée** (`edition=None`), pas une page marquée `full`
  (`test_presentation_edition_ui_browser.py:325`).
- Aucun test de `surfaces_disagree` (la page dit `hidden`, Core dit `visible`, ou l'inverse).

### OBSERVATIONS

- O1 — Quand la page et Core divergent sur les surfaces, « Core gagne » n'arrive qu'à la première lecture à la demande
  (ouverture du panneau des Boards). Les outils du dock peuvent alors apparaître ou disparaître en pleine session. Le
  cas suppose un réglage différent de Core et du Control Center ; la doc demande de régler les deux.
- O2 — Une valeur illisible de `JARVIS_DEVELOPER_MODE` empêche aussi l'édition `full` de démarrer
  (`product_edition.py:147`, évaluée avant le test `developer_surfaces`). C'est voulu et documenté ; il faut juste le
  savoir pour le JARVIS quotidien.
- O3 — Non vérifié à l'écran : Réglages › Interface & Interactions › Raccourcis liste sans doute encore le raccourci
  « Trace » (`shortcuts.py:103`), et la roue garde « Sélection › Bare Hands » alors que les réglages Bare Hands sont
  cachés. L'ensemble manque de cohérence, sans être une faille.
- O4 — Le lanceur garde ses codes CNV/AGT/ERR et le panneau Agents en `presentation` (classés « product »). C'est un
  choix produit à confirmer par l'utilisateur (HV-UI-01).

## Contrôles demandés

| Point | Constat |
| --- | --- |
| Complétude vs SLICE.md | Étapes 1-6, 8 et 9 livrées. Étape 7 (affordances connecteurs/préparation) reportée : voir ci-dessous. |
| Report du critère 7 | **Acceptable** : la Slice 07 (onboarding/santé) n'est pas livrée, la dépendance est déclarée *soft* (`requires`) et brancher une source de préparation inexistante obligerait à la deviner. À tracer dans `Issues/` (aucune entrée S08 aujourd'hui) pour que la Slice 07 ou la Slice 11 la reprenne sur l'accueil. |
| `full` sans régression | Dix outils, six catégories, trois types disponibles, rail vide caché, moteur nommé (test navigateur `test_full_edition_is_unchanged`, vert). Le CSS ne cache rien sous `visible`. Seul changement : les orbes du type attendent la réponse de Core (quelques ms en local) ; si `/api/boards/edition` échoue, la création attend avec « Réessayer » — conforme à « jamais d'optimisme », mais c'est un nouveau point de blocage. Lots de non-régression verts hors B1/F1. |
| Types venus de Core | Oui : `parse` refuse une charge illisible, `kindView` → `unknown` sans modèle, `createBoard` refuse localement un type non `available` (`boards.js` ~1981), aucune table locale. |
| Surfaces cachées sans flash | Oui : marquage serveur à chaque service (`control_center.py:2685`, `page_edition_markup`), règle CSS unique, roving du lanceur et raccourci `t` gardés, cibles des Réglages refusées vers la première catégorie. Réapparition avec `JARVIS_DEVELOPER_MODE=1` : prouvée côté Python seulement (M7). |
| Lecture à la demande | Oui : `ensure()` ne lit qu'à l'état `idle` (pas de boucle de rendu), échéance de 8 s, reprise 2→30 s seulement si `status.boards.available`, relance au retour de Core, « Réessayer ». Prouvé par `test_product_edition_ui_js.py` et le test navigateur « aucune lecture au démarrage ». |
| Erreurs visibles | Choix du type : cause, `code · message`, « Réessayer », `role=alert`. Création dans le rail : note avec les secondes, cause, relecture. Écarts M3, M4, M5. |
| Accessibilité | `aria-disabled` + `aria-description` sur les orbes à venir, focus sur le type disponible, accueil hors `listbox`, `aria-live` coupé pendant le décompte, `focus-visible`. Le groupe radio du type se parcourt à la Tab, pas aux flèches (comportement préexistant). Contraste de l'étiquette « Bientôt disponible » (#7190a0 sur ~#05080c) ≈ 6:1. |
| Qualité visuelle (3 largeurs) | Choix du type : propre et lisible ; Présentation focalisée, les deux autres éteints en pointillés ; tient sur une rangée à 600 px. Accueil : quatre étapes claires et lisibles à 600 px. Le bouton « Nouvelle » de l'en-tête double « Nouvelle présentation » de l'étape 2 : redondant mais acceptable. Hub des Réglages : quatre cartes, « Connexions ». |
| Réutilisation | Bonne : registre des Réglages étendu (`surface`, `categoriesFor`), contrôle Boards et rail étendus, route de création de Core réutilisée. Doublon partiel de la table d'erreurs (M3). |
| Docs | Cohérentes avec le code (inventaire, états, journal, tests) ; E11 corrigé. Écart : docstring de `page_edition_markup` (M5). |
| Tests | Suffisants pour le parcours principal ; trous M7 ; B1 non mis à jour. |

## Flagged

- F1 — `tests/unit/test_boards_card_browser.py::test_refus_perime_ecarte_et_code_en_infobulle_dans_un_vrai_navigateur` :
  3 échecs sur 5 sur la branche (texte de présence vide alors que l'état vaut `inactive`), puis 2 succès d'affilée ;
  2 succès sur 2 sur la base. Une sonde identique jusqu'à l'action 4 lit bien « Séance inactive ». Ce test paraît
  sensible à la charge de la machine ; aucun lien causal avec la Slice n'est établi. À relancer seul lors de la reprise.
- F2 — Préexistants (échouent aussi sur `cf3f7e44`) et absents de la liste connue :
  `test_barehands_interaction_js.py::test_the_practice_frame_is_moved_by_one_zone_through_the_real_engine`,
  `::test_the_practice_frame_resizes_only_on_two_distinct_compatible_zones`,
  `test_barehands_palette_js.py::test_the_served_page_puts_the_tools_on_the_palette_and_not_in_the_settings`.

## Non vérifié

- Validation en conditions réelles (vrai Control Center + vrai Core, `JARVIS_PRODUCT_EDITION=presentation`, Core arrêté
  puis relancé, création réelle) : relève de la QA `runtime-validation`, à faire en bac à sable. Aucun JARVIS lancé ici.
- Captures absentes : Board hérité « Bientôt disponible » dans la liste, état « Types de Board illisibles » +
  « Réessayer », écrans `full` après la Slice, mode développeur.
- Lecteur d'écran réel (NVDA) : seuls les attributs ARIA ont été relus.

## Risques résiduels

- En `full`, la création d'un Board dépend désormais de `/api/boards/edition` : un Core plus ancien ou une panne de
  cette route bloque la création (avec message et reprise).
- Le masquage n'est qu'une question de navigation : les routes restent servies, Core et la Slice 04 restent la
  frontière.

## Pistes d'amélioration

- Unifier les tables d'erreurs de création (moteur / rail) dans le module de l'édition ou dans un module commun.
- Faire porter aux messages « Réglages › … » une cible structurée (`openSettingsTab(id)`) plutôt qu'un chemin en
  texte : l'édition pourrait alors les réécrire ou les taire.
