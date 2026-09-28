# Slice 00 — Registre de readiness

État : **READY** (H1 et H2 acceptées par l'Humain le 2026-09-24, qui délègue ensuite toute décision à l'agent 0)

Date : 2026-09-24. Base : `origin/main` @ `ddcdb71e17d7be76236c7dd6ab070af90e8f7d65` — exactement le SHA revu par le handoff (`task.json.source_snapshot.sha`). Branche : `task/jarvis-mcp-semantic-batch-inspector` (pas de branche `dev` dans ce dépôt ; créée depuis `origin/main`, sans upstream).

---

## 1. Ce que le handoff déclare

Rendre le MCP Jarvis orienté intention : une intention utilisateur → une `SceneSelection` de domaine → une commande de scène → une révision. Puis un inspecteur MCP lisible, en lecture seule, dans le dock du Control Center, alimenté par la même source de vérité que les serveurs FastMCP. Surface scène ≤ 13 outils, aucun méta-outil visible du modèle, pas de nouveau geste Bare Hands.

## 2. Audit aveugle — ce que le dépôt dit réellement

Conduit par un sous-agent **sans lecture de `tasks/`**, avant réconciliation. Introspection réelle des serveurs via `build_server` + `list_tools()` avec backends simulés.

| Sujet | Réalité au SHA revu |
| --- | --- |
| Serveurs natifs | `jarvis-display` (`display_mcp.py:114`) **13** outils · `jarvis-console` = `settings_mcp.py:59` **3** (`settings_describe/get/set`) · `jarvis-barehands` (`barehands_mcp.py:77`) **5** · `jarvis-drive` **7**, enregistré à la main par l'opérateur (`docs/OPERATIONS.md:1139-1143`), pas par Jarvis. |
| Exposition au modèle | `ClaudeLocalAgent` écrit un `--mcp-config` par serveur (`claude_local.py:766-847`). Display derrière `scene.enabled`, console toujours déclarée. `DISPLAY_TOOLS` (`claude_local.py:216`) classe le temps de tour ; prompts `BRAIN_DISPLAY/BAREHANDS/SETTINGS_PROMPT` nomment les outils, **empreinte de prompt testée** (`claude_local.py:108-109`). |
| Lots scène | `_update_many` (`display_mcp.py:965-1104`), `_dispose` archive/pin (`:1161-1241`), `_show_all_hidden` (`:877-945`) : **un `POST` Core par objet**, `atomicity: "best_effort"`. Plafonds 32 (update_many) / 128 (dispose, bulk), `confirm` si ≥ moitié des visibles, échéance 15 s vérifiée entre commandes. Erreur de transport en cours de lot → exception, compte appliqué seulement dans le texte, `_remember` sauté (cache vu périmé). `_update_many` ré-implémente `_designate` en ligne. |
| Domaine | `apply_scene_command` pur (`scene.py:1264-1305`) → planificateur (`_PLANNERS`, `:1799-1812`) → `ScenePatchOp[]` → une `ScenePatch(revision+1)`. Seul `archive_many` fait N objets / 1 révision (`:1630-1651`), filtré par `bulk_archivable` (`:1540-1567`), ≤ 512 ids. Cascade signal déjà multi-ops dans `archive`. `MAX_PATCH_OPS` borne le patch. Applicateur JS miroir (`control_center_scene.js`), parité testée. |
| Chemin Core | `POST /v1/scene/commands` → `LocalProtocolServer.scene_command` (`protocol/server.py:938-971`, refuse l'acteur `runtime`) → `SceneService._apply_serialized` (`core/scene_service.py:273-304`) sous verrou. Le Control Center proxifie `/api/scene/commands` (`control_center.py:685`). |
| Constellation | MCP `_connected_ids` (`display_mcp.py:600-620`) : BFS non orienté sur relations, `depth` 1–6, objets masqués inclus. UI `constellationOf` (`control_center_scene_interact.js:454-471`) : même BFS **+ arêtes virtuelles `signalOwners`**, sans profondeur, racine en tête, puis filtrée aux nœuds rendus (`control_center_scene_page.js:2663`). **`constellationOf` n'a aucun test.** `signalOwners` JS est un portage de `signal_owners` (`scene.py:1498-1526`) avec test de parité. |
| Sélection | **Aucun concept de domaine.** `let selection=[]` côté page (`page.js:966`) ; glisser porte la sélection mais **commit un `commitUserGeometry` par objet** (`page.js:2491-2501`) → N révisions. Dette Bare Hands documentée : `docs/barehands-contracts.md:3771-3774`. |
| Schémas | `Annotated[..., Field]` partout sauf drive. Entrées durcies `additionalProperties:false` par surcharge de `list_tools`/`call_tool`. **Sorties non typées** : `dict[str, Any]` (mutations), `str` JSON compact et budgété pour `inspect/query/get` (`MAX_INSPECT_BYTES`), `scene_capture` non structuré, console/Bare Hands `dict` nus. Aucune `annotations` (readOnly/destructive). |
| Catalogue existant | Aucun. `TOOL_NAMES` + tests de parité ; `/api/catalog` (`control_center.py:649`) est le catalogue **de modèles**, pas d'outils. `build_server(tools=...)` accepte des backends injectés : introspection sûre possible. |
| Dock | `control_center.html:767-774`. ERR/TRC/AGT via `data-panel` + `#panel` générique ; LAB/CNV/SET boutons dédiés ouvrant leurs dialogues plein écran. **Pas de registre** : `openPanel(name)` codé en dur (`html:1052`), câblage `:3649`. Vanilla JS, **pas de build** : `control_center_*.js` injectés aux marqueurs `/*__…_JS__*/` (`control_center.py:919-996`, constantes `:223-331`). Données par `fetch` + polling, aucune WebSocket. Tests JS = pytest qui lance `node`. |
| Docs canoniques | `docs/scene-model.md` (table outils `:711-779`), `docs/ARCHITECTURE.md` (~`:2020-2401`). `docs/mcp/plan-outils-interface.md` = plan, périmé de son propre aveu. |

### Dérives de doc relevées (à corriger par la slice qui touche le contrat)

- `docs/scene-model.md:715` « un `SceneCommand` par appel » — faux pour update_many/archive/pin/all_hidden (→ Slice 05, qui le rendra vrai).
- Docstring `scene.py:31` « seul `user` archive » — contredit `ALLOWED_SCENE_OPS` (`:274-280`) et `scene-model.md:173` (→ Slice 03).
- Mineur, hors périmètre : clé d'idempotence `drive_update` basée sur `hash(content)`, instable entre processus (`drive_mcp.py:100`) → candidat `Issues/`.

## 3. Réconciliation avec le handoff

Les conclusions du handoff sont **confirmées** : 13 outils scène, boucles `best_effort`, `archive_many` seule vraie batch, écart de constellation via `signalOwners`, glisser multi-objet commité objet par objet, `jarvis-console` générique à préserver, dock correct. Précisions que le handoff n'avait pas et que les slices doivent intégrer :

1. **Deux écarts de constellation de plus** que `signalOwners` : profondeur (MCP borné 1–6, UI illimité) et objets masqués (MCP inclus, UI filtré aux nœuds rendus — à vérifier). Slice 01 doit trancher le contrat pour les deux ; Slice 02 ajoute le premier test de `constellationOf`.
2. **Typage des sorties `inspect/query/get`** : ce sont des chaînes JSON compactes, budgétées en octets pour le cerveau. Slice 04 doit typer sans gonfler le contexte modèle ni casser le format ligne (contrat cerveau).
3. **Empreinte de prompt** : toute retouche de prompt/outil (Slices 04–05) doit mettre à jour les tests d'empreinte `claude_local` et `DISPLAY_TOOLS`.
4. **Pas de registre de panneaux** : Slice 07 suit le modèle LAB/CNV/SET (bouton dédié + dialogue plein écran + module `control_center_mcp_inspector.js` injecté par marqueur), pas `openPanel`.
5. **Glisser multi-objet UI** : le handoff ne l'attribue à aucune slice. Slice 05 ajoute la translation relative côté MCP ; **Slice 03 expose la commande de domaine**, et le commit du glisser de la page doit passer par elle (une révision) — rattaché à Slice 03 (transport/wire) avec parité applicateur JS.
6. **Plafonds actuels** (32 / 128 / 512 / `MAX_PATCH_OPS`) : Slice 01 fixe une borne unique pour les lots atomiques, compatible `MAX_PATCH_OPS` en comptant les cascades.

Graphe de dépendances (`slices/TODO.md`) : valide, acyclique. Identifiants Human : `HV-MCP-INSPECTOR-01` (Slice 07), `HV-MCP-E2E-01` (Slice 08) — uniques, bien formés, préconditions « QA machine verte » présentes. Slices 00–06 : aucun contrôle Human déclaré (`{"checks": []}`), cohérent.

Compétences exigées, présentes dans `C:\DevTools\skills-lib` : `caveman`, `coding-guideline`, `impeccable`, `qa-verification`, `code-review`, `runtime-validation`, `agent-trace-analysis`. Routage « Claude Work Agent » pour le frontend : pas de règle de routage exposée par l'hôte → Slice 07 est déléguée à un sous-agent Claude avec `/impeccable`, limite consignée.

Portes QA par slice :

| Slice | qa-verification | code-review | runtime-validation | agent-trace-analysis |
| --- | :-: | :-: | :-: | :-: |
| 01 contrats (docs) | ✓ | — | — | — |
| 02 sélection/constellation | ✓ | ✓ | — | — |
| 03 lots atomiques | ✓ | ✓ | ✓ (glisser UI) | — |
| 04 catalogue/schémas | ✓ | ✓ | — | ✓ |
| 05 migration jarvis-display | ✓ | ✓ | ✓ | ✓ |
| 06 API catalogue | ✓ | ✓ | ✓ | ✓ |
| 07 inspecteur UI | ✓ | ✓ | ✓ | — |
| 08 intégration | ✓ | ✓ | ✓ | ✓ |

## 4. Baseline mesurée au SHA `ddcdb71`

Worktree détaché `C:/Projects/jarvis/bwt`, `.venv` principal, premier plan, 8 lots.

- `tests/unit` : 248 fichiers — **6 991 passés, 25 échecs, 6 ignorés**.
- `tests/integration` : 67 fichiers — **566 passés, 6 échecs, 22 ignorés**.

**Échecs hérités — pas à vous, ne pas les « réparer » en passant** (sauf décision H2) :

| Fichier | # | Nature | Domaine de cette tâche ? |
| --- | -: | --- | --- |
| `unit/test_scene_artifacts.py` | 6 | le cerveau a maintenant l'autorité pin/move (`APPLIED` attendu `REJECTED_AUTHORITY`) ; message `scene_full` changé | **oui** |
| `unit/test_scene_batch_tools.py` | 3 | `pinned_skipped` absent ; description de l'outil de lot mentionne désormais archive/pin | **oui** |
| `unit/test_scene_capture.py` | 1 | catalogue contient archive/pin | **oui** |
| `unit/test_scene_query_tools.py` | 2 | 13 outils au lieu de 11 ; prompts plus octet-identiques | **oui** |
| `unit/test_scene_service.py` | 2 | autorité cerveau ; nombre d'événements 5 vs 4 | **oui** |
| `unit/test_scene_settings.py` | 2 | prompt système du cerveau changé | **oui** |
| `unit/test_scene_transport_client.py` | 4 | générateur de parité attend des refus `rejected_authority` qui n'existent plus | **oui** |
| `unit/test_scene_interaction_logic.py` | 1 | entrée de menu `select-constellation` ajoutée | **oui** |
| `integration/test_scene_transport.py` | 2 | archive cerveau désormais permise | **oui** |
| `unit/test_barehands_interaction_js.py` | 2 | géométrie du cadre d'entraînement | non |
| `unit/test_barehands_tutorial_retired_js.py` | 1 | texte de prompt Bare Hands | non |
| `unit/test_brain_delegation.py` | 1 | prompt cerveau | non |
| `integration/test_testlab_*_runners.py` | 4 | runners audio/matériel/live | non |

Lecture : `main` a élargi l'autorité du cerveau sur la scène (pin/archive) et ajouté 2 outils + une entrée de menu **sans mettre à jour 23 tests**. Ce sont exactement les fichiers que les Slices 02–05 vont modifier.

Chiffre à re-mesurer à chaque slice, jamais à reporter.

## 5. Décisions requises de l'Humain

### H1 — Task Type (bloquant de planification déclaré)

Le vocabulaire « Workspace Task Type » n'existe pas dans cet espace ; aucune valeur n'est inventée. Précédent : dérogation accordée pour quatre tâches (settings, observability, category2 test lab, bare hands). **Recommandation : même dérogation** ; `metadata.json.task_type` reste `null` avec cette décision consignée.

### H2 — 23 tests périmés dans le domaine de la tâche

Laisser ces tests rouges rend toute preuve « pas de régression » ambiguë précisément là où la tâche travaille. **Recommandation : chaque slice réaligne les tests périmés du fichier qu'elle possède sur le comportement actuel de `main`** (autorité cerveau élargie = vérité actuelle), dans un commit séparé préfixé par son ID et marqué « réalignement baseline », avant sa propre modification :
- Slice 02 : `test_scene_interaction_logic.py` ;
- Slice 03 : `test_scene_artifacts.py`, `test_scene_service.py`, `test_scene_transport_client.py`, `integration/test_scene_transport.py` ;
- Slice 05 : `test_scene_batch_tools.py`, `test_scene_capture.py`, `test_scene_query_tools.py`, `test_scene_settings.py`.

Les 8 échecs hors domaine (Bare Hands, délégation, testlab) restent hors périmètre et vont dans `Issues/`.
Alternative : ne rien réaligner et juger chaque slice uniquement par différence avec la liste ci-dessus.

## 6. Réparations de planification appliquées

- Cette readiness complète « Files Likely Touched » de chaque slice (§2, §3) ; chaque `SLICE.md` renvoie ici.
- Glisser multi-objet UI rattaché à Slice 03 (§3.5).
- Contrat de constellation : profondeur et objets masqués ajoutés au périmètre de Slice 01 (§3.1).

**Décision Humaine 2026-09-24 : « oui et oui ».** H1 : dérogation Task Type, `task_type` reste `null`. H2 : réalignement par la slice propriétaire, selon la répartition ci-dessus. L'Humain délègue désormais toutes les décisions à l'agent 0 ; seuls restent humains le déplacement Drive, les contrôles `HV-*`, l'acceptation finale et toute fusion dans `main`.

État : **READY**.
