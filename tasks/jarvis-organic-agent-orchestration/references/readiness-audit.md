# Slice 00 — Audit de readiness (audit aveugle puis réconciliation)

Date : 2026-10-20. Auteur : Work Agent de la Slice 00. Worktree `C:/Projects/jarvis/orch`,
branche `task/jarvis-organic-agent-orchestration`, issue de `main`.

**État de readiness : `READY`** (après les amendements consignés ici et dans les `SLICE.md`).
Une décision produit non bloquante pour les Slices 01 à 04 doit être tranchée avant le dispatch
de la Slice 05 : Q1 (§6).

Ordre suivi : l'audit du §1 a été mené sur le code et la documentation du dépôt **avant** toute
lecture de `README.md`, `docs/`, `references/`, `Issues/` et des `slices/` de ce handoff (seul
`slices/00-project-manager-readiness/SLICE.md` a été lu d'abord, pour le contrat). La
réconciliation (§2 et suivants) vient ensuite.

---

## 0. Tête du dépôt et topologie

| Fait | Preuve |
| --- | --- |
| HEAD de la branche de tâche = `336f21be` (« Merge branch 'task/quick-fixes-pre-presentation' ») | `git log --oneline -3` |
| `origin/main` = HEAD, aucune dérive au 2026-10-20 | `git fetch` puis `git log HEAD..origin/main` vide |
| Base du handoff `82051c3a` ; entre elle et HEAD, un seul commit : `3351ef59` (lasso, Suppr/-, roue épinglée, Dossier direct) | `git log 82051c3a..336f21be` |
| `3351ef59` ne touche que l'UI scène/dossier/roue (`control_center_scene_page.js`, `control_center_tool_wheel.js`, `control_center_dossier*.js`, docs `control-center-shell.md`, `scene-selection-batch.md`) : aucun contrat Work State, rôle, loadout, Scene domaine, migration. Impact : nul sur le plan, sauf vigilance de fusion pour la Slice 09 (`control_center_scene_page.js` +62 lignes) | `git diff --stat 82051c3a 336f21be` |
| `e05d931d` (registre des rôles, mode Interview) est **antérieur** à la base du handoff : il était déjà dans `82051c3a`, mais le handoff ne le mentionne nulle part | `git merge-base --is-ancestor e05d931d 82051c3a` vrai |
| Aucun processus à l'écoute sur `17653/17654/27653/27654` au moment de l'audit (lecture seule, rien lancé) | `Get-NetTCPConnection -State Listen` |
| Lot de tests de référence vert : `test_subagent_roles.py`, `test_work_state_contracts.py`, `test_schema_migrations.py` — 123 passés | `.venv/Scripts/python.exe -m pytest` (avant-plan) |
| Le dépôt n'a pas de `docs/workflows/AGENT_TASK_LIFECYCLE.md` : repli sur la mémoire projet (pas de branche dev, brancher depuis `main`, worktree dédié, un seul writer par worktree) | `ls docs` |

Worktrees voisins pertinents (`git worktree list`) : `subag` (`task/jarvis-subagent-roles-interview`,
HEAD `e05d931d`, propre), `eph` (`task/jarvis-ephemeral-tasks`, HEAD `39ea9909`, 13 fichiers non
commités), `bor` (`task/jarvis-board-orbital-ui-workspace-rail`, non mergé : touche l'UI Control
Center, à surveiller par la Slice 09/10).

---

## 1. Audit aveugle (code actuel, avant lecture du handoff)

### 1.1 Work State (vérité d'exécution vivante)

- Contrats neutres et bornés : `WorkStatus` (`jarvis/domain/work_state.py:68`), `WorkObservation`
  (`:369`), `WorkItem` (`:507`), `WorkSnapshot` (`:616`), `WorkLink` (`:317`, `work_id` +
  `correlation_id`), application pure `apply_observation` (`:706`). Identité = `(source,
  external_id)`, jamais déduite d'un libellé (docstring `:16-20`). Terminal définitif (`:24`).
- Pas de champ rôle, mission, relation sur `WorkItem` ; champs déjà présents : `parent_external_id`,
  `board_id`, `background`, `ephemeral` (`:527-536`). `MAX_WORK_ITEMS = 64` (`:60`).
- **Éphémère déjà sur main** : `EPHEMERAL_WORK_STATUSES` (`:104`), drapeau `ephemeral` sur
  observation/élément, rabaissé sur échec/arrêt/interruption/blocage.
- Magasin `WorkStateStore` (`jarvis/core/work_state.py:142`) : **mémoire seule, rien persisté**
  (`docs/ARCHITECTURE.md:1692-1695`) ; redémarrage de Core = magasin vide, nouveau `store_id`, le
  Control Center renvoie son état (30 dernières tâches finies) (`docs/ARCHITECTURE.md:1700`).
- Ingress Control Center → Core : `TrackerWorkObserver` (`jarvis/runtime/work_ingress.py:134`)
  — le handoff le place sans chemin ; il vit dans `jarvis/runtime/work_ingress.py`.
- Contexte cerveau : `BrainWorkContext` (`jarvis/domain/brain_context.py:255`), Core
  `jarvis/core/brain_context.py`, résumé `jarvis/runtime/work_brief.py` (et non `jarvis/core/`).

### 1.2 Suivi des agents (diagnostic fournisseur)

- `AgentTaskTracker` (`jarvis/runtime/agent_tasks.py`) reconstruit les sous-tâches du flux
  `stream-json` du CLI ; profondeur d'imbrication lue sur `spawn_depth` (`:613-615`) : les
  sous-agents imbriqués sont déjà observés.
- Snapshot de tâche : champ `role` lu par `routing_hook.read_role` sur la description
  (`agent_tasks.py:1011`, commit `e05d931d`). Ce rôle n'atteint **pas** Work State (absent de
  `WorkObservation`) : il n'existe que dans `/api/agent/tasks`.
- Marqueur éphémère `EPHEMERAL_MARKER = "[éphémère]"` (`agent_tasks.py:72`), grammaire exacte en
  tête de description (`parse_ephemeral_description`, `:184-198`, regex `:73`).
- Routes Control Center : `GET /api/work` (`control_center.py:1538`, lecture de l'état Core, lecture
  seule) ; `GET /api/agent/tasks` et `/trace` (`:1544-1545`).
- Spawn : **Core ne lance aucun agent**. Le cerveau est un CLI Claude Code permanent qui lance ses
  sous-agents par l'outil `Agent` ; Jarvis ne construit jamais ce lancement
  (`docs/ARCHITECTURE.md:4297-4300`). Le seul point contraignant est le hook `PreToolUse`
  (`jarvis/runtime/routing_hook.py`) qui voit chaque appel `Agent`/`Task` et peut réécrire
  `model` et la consigne. Outils de délégation autorisés au cerveau : `DELEGATION_TOOLS`
  (`claude_local.py:477-480`, dont `SendMessage`). Codex : `subtasks_supported` faux
  (`control_center.py:6048-6049`).
- Conversation Events : spans `subagent.started|finished|failed|stopped`
  (`jarvis/domain/conversation_events.py:123-126`, `:209-212`) ; un sous-agent non attribué à une
  conversation n'enregistre rien (`jarvis/runtime/subagent_conversation.py:22`). Attribut booléen
  `ephemeral` déjà autorisé (`conversation_events.py:298`).

### 1.3 Registre des rôles et mode Interview (`e05d931d`, déjà sur main)

- Module pur `jarvis/domain/subagent_roles.py` : `SubagentRole` figé (`:54-67` : `id`, `marker`,
  `name`, `description`, `mission`, `instructions`, `skills`, `tools`, `when_relevant`,
  `default_profile`, `enabled`), validation des marqueurs `[a-z][a-z_-]{1,23}` (`:50`),
  `prompt_id = "subagent_role.<id>"` (`:35`, `:89`).
- 5 rôles (`:222-283`) : `interviewer`, `research` (Recherche documentaire), `web-research`,
  `coder` (Développement, profil `code`), `concept` (Conceptualisation).
- `with_role_instructions` (`:301`) apposé par le hook après la charte (`routing_hook.py:214`) ;
  surcharges lues dans l'instantané `runtime/subagent-roles.json`
  (`jarvis/runtime/subagent_roles_snapshot.py`, `routing_hook.py:515-540`) ; journal
  `agent.role_applied` (`routing_hook.py:542-570`).
- Prompt cerveau : section « TYPE DE DEMANDE » générée par `brain_rules()` (`subagent_roles.py:330`,
  insérée `claude_local.py:106`) : cas A action claire (un agent, pas d'Intervieweur), B intention
  à cadrer (dossier de mission + Intervieweur + aides en parallèle), C expertises multiples.
- **Dossier de mission déjà existant** : `<mémoire du Board>/missions/<sujet>-<AAAAMMJJ>/mission.md`
  (`subagent_roles.py:41-43`, `:108-118`), fichier partagé, éléments marqués `[dit]`/`[trouvé]`/`[déduit]`.
- **Porte d'exécution existante, décidée par l'utilisateur** : `EXECUTION_GATE_RULE`
  (`subagent_roles.py:314-318`) — sur « PRÊT : », le cerveau résume et demande l'accord oral ;
  limitée au cas B (demande cadrée par l'Intervieweur). Décision 1 du plan
  `tasks/jarvis-subagent-roles-interview/PLAN.md`.
- Édition : chaque rôle est un prompt éditable `subagent_role.<id>` (`prompt_catalog.py:250-255`,
  `apply_policy="next_invocation"`) via `POST /api/prompts/{id}` ; lecture
  `GET /api/subagent-roles` (`control_center.py:259-262`, route `:1467`, charge utile
  `_subagent_roles_payload`). Les surcharges utilisateur sont donc **déjà persistées sous les ids
  actuels**.
- Restes annoncés par le commit : onglet Settings « Sous-agents » (front) et
  `docs/subagent-roles.md` — **ce fichier n'existe pas** alors que la docstring du module y renvoie
  (`subagent_roles.py:22`). `TABS` de Settings : voix, prompts, cli, keys, shortcuts, memory
  (`control_center.html:4028-4035`), aucun onglet rôles.

### 1.4 Loadouts

- `LOADOUT_ROLES = ("coder", "reviewer", "research")` (`jarvis/domain/memory_settings.py:159`) ;
  clés `<profil>` / `<profil>:<rôle>` validées (`:164-175`).
- `LoadoutResolver.resolve(profile, role)` (`jarvis/core/loadout_resolver.py:122`),
  `ROLE_BASE_PROFILE` (`:46`). Un rôle du registre sans loadout garde celui de son profil
  (`routing_hook.py:129-136`). `ANNOUNCED_ROLES` = union loadout + registre (`routing_hook.py:75`).
- `reviewer` existe comme rôle de loadout mais **pas** dans le registre des sous-agents.

### 1.5 Scene

- Natures fermées `agent|job|artifact|attention|window|group` (`jarvis/domain/scene.py:149-157`) ;
  `RelationKind` fermé `parent_of|explains|groups` (`:236-241`).
- Autorité : `runtime` ne peut que `upsert/patch/link/unlink/attach_signal`, pas archiver
  (`ALLOWED_SCENE_OPS`, `:308`) ; `runtime` ne crée que des `parent_of` entre nœuds d'exécution
  (`_plan_link`, `:1932-1947`).
- `category` est **écrivable par le cerveau et l'utilisateur** (`_WRITABLE_FIELDS`, `:320` ;
  `scene_update_object`/`patch_selection` dans `docs/scene-model.md:197`, `:971`) : ce n'est pas un
  champ fiable pour porter un rôle (contrefaçon possible). Seuls `exec_state`, `work_ref` sont
  réservés au runtime (`EXECUTION_FIELDS`, `:317`).
- Projecteur : étoiles depuis Work State, lien parent `parent_of` (`scene_projector.py:1238-1257`).
- Persistance `scene.sqlite3` : `_SCHEMA_VERSION = 1`, `_MIGRATIONS = {}`
  (`jarvis/adapters/sqlite_scene.py:129-135`), charge utile versionnée `SCENE_SCHEMA_VERSION = 1`
  (`scene.py:75`), refus d'une charge plus récente (`sqlite_scene.py:604-612`).
- **Éphémère côté scène sur main** : l'étoile est créée et **persistée** comme les autres ; elle est
  seulement masquée par le modèle de vue de la page 6 s après la réussite
  (`EPHEMERAL_LINGER_MS`, `showEphemeral` local au navigateur) ; « the scene star is skipped by the
  view model only (it stays in the scene state) » (`docs/ARCHITECTURE.md:3513-3563`).

### 1.6 Migrations SQLite

- `jarvis.sqlite3` : `_SCHEMA_VERSION = 9` (`jarvis/adapters/sqlite_state.py:32`), `_MIGRATIONS`
  (`:45`) jusqu'à 9 (`:279`, données seules) ; instantanés `tests/schema/jarvis_state.v3..v9.sql`.
- Patron des domaines persistants : tables créées par une étape de `sqlite_state._MIGRATIONS`,
  adaptateur dédié qui partage connexion, verrou et thread via `run_serialized`
  (`jarvis/adapters/sqlite_artifacts.py:1-8`, de même `sqlite_captures.py`,
  `sqlite_board_artifact_links.py`, `sqlite_conversation_events.py`).
- `scene.sqlite3` : v1, aucune migration publiée ; `tests/schema/scene.v1.sql`.

### 1.7 Prefabs, Settings, conventions

- Prefabs de base `jarvis.browser|checklist|document|table|window` (`jarvis/prefabs/base/`),
  `PrefabService` (`jarvis/core/prefab_service.py:250`), outils agent `jarvis-display`
  (`docs/prefabs.md:1014`), section « Consumers » (`docs/prefabs.md:1598`).
- Modules Settings : `control_center_memory_settings.js`, `control_center_scene_settings.js` ;
  index `docs/settings/INDEX.md`.
- Conventions de tâche : `tasks/<slug>/` avec `slices/NN-*/{SLICE.md,metadata.json,human-validation.json}`,
  `LOG.md`, `Issues/`. Aucun vocabulaire Workspace Task Type dans le dépôt.

---

## 2. Réconciliation avec le handoff

### 2.1 Ce que le handoff a raté (contexte périmé)

`references/repository-audit.md` et le README décrivent le seam rôle comme
« `LoadoutResolver.resolve(profile, role)` avec `coder`, `reviewer`, `research` ». C'est incomplet :
au moment même de la base, main contenait déjà **un registre de rôles, un Intervieweur, un dossier
de mission, une porte d'exécution, des instructions de rôle éditables et persistées, une route de
lecture** (§1.3), et **une fonctionnalité éphémère complète** (§1.1, §1.5). Les Slices 01, 04, 07 et
10 auraient recréé ces éléments en parallèle. Les amendements du §5 corrigent cela.

### 2.2 Recoupement avec `jarvis-subagent-roles-interview`

**Décision : absorber le reste de cette tâche dans celle-ci ; ne rien recréer.**

| Élément existant (main) | Slice qui le réutilise | Règle |
| --- | --- | --- |
| `SubagentRole` / `ROLES` / `role_for` | 01 (contrat) puis 04 (registre) | **Étendre** ce module : il devient le registre canonique (visuel, capacités `can_own_mission`/`can_spawn`, méthodes, alias de loadout). Pas de second module de rôles. |
| Ids `interviewer`, `research`, `web-research`, `coder`, `concept` | 01 | **Ids conservés tels quels** : ils sont la clé `subagent_role.<id>` des surcharges déjà enregistrées chez l'utilisateur ; renommer les rendrait orphelines. Correspondance handoff → id : Developer = `coder`, Document Research = `research`, Web Research = `web-research`, Conceptualizer = `concept`, Interviewer = `interviewer`. Nouveaux ids additifs : Research Lead, QA (et Finalizer seulement si la Slice 01 en prouve l'utilité). `reviewer` (loadout) devient l'alias de compatibilité du rôle QA. Libellés affichés en français. |
| Marqueurs `[profil] [rôle]` + hook | 01/04/05 | Restent la voie de déclaration d'un rôle par le cerveau ; le rôle n'est pas « deviné » d'un libellé, il est lu d'un marqueur à grammaire fermée (compatible avec la règle « pas d'inférence »). La Slice 03 le fait voyager jusqu'à Work State. |
| `with_role_instructions`, `subagent-roles.json`, `agent.role_applied` | 04 | Couche prompt du rôle = ce mécanisme ; la Slice 04 y rattache méthodes et loadout. |
| `brain_rules()` cas A/B/C | 07 | La Slice 07 **amende** cette section générée ; elle n'ajoute pas un routage concurrent. |
| Dossier de mission `missions/<…>/mission.md` | 01/03/07 | Le contexte partagé lisible d'une mission existe : l'entité Mission de la Slice 01 le **référence** (chemin) au lieu d'inventer un second support ; l'historique structuré (Slice 03) vit en base, le dossier reste la prose partagée. |
| `EXECUTION_GATE_RULE` | 07 | Règle d'autorité **existante**, choisie par l'utilisateur, limitée au cas B : la préserver telle quelle (voir §2.4). |
| `GET /api/subagent-roles` + `POST /api/prompts/subagent_role.<id>` | 04/10 | API de lecture/écriture sûre déjà en place : la Slice 04 étend la charge utile (`schema_version` 2 si les champs changent), la Slice 10 construit l'onglet dessus, **avec édition des instructions** (décision 3 de l'utilisateur : instructions modifiables et persistées). |
| Onglet Settings « Sous-agents » (non fait) | 10 | La Slice 10 **est** cet onglet (un seul onglet rôles, pas deux). Plan de référence : `tasks/jarvis-subagent-roles-interview/PLAN.md` §6 (module `control_center_subagents_settings.js`, patron `control_center_memory_settings.js`, instances actives à part). |
| `docs/subagent-roles.md` (manquant) | 01 crée, 04/07/10 complètent | Page canonique rôles + missions (§4). |
| Essai réel en bac à sable (non fait) | 07 (scénarios A/B) et 13 | Repris tels quels : « corrige ce bug » → un seul `[code] [coder]` ; « belle vidéo » → dossier + Intervieweur + recherche parallèle + « PRÊT » + demande d'accord. |

Conséquence pour l'autre tâche : son worktree `subag` est propre et son HEAD est dans main ; elle
n'a plus de travail propre. Le classement Drive (déplacement vers done, ou mention « absorbée »)
reste au Human (voir §6, Q2).

### 2.3 Worktree `eph` (lecture seule, non modifié)

- Branche `task/jarvis-ephemeral-tasks`, HEAD `39ea9909` (ancêtre de main), modifications non
  commitées datées du 2026-10-07, `docs/ephemeral-tasks.md` non suivi.
- Ce qu'il fait : marque `EPHEMERAL_MARK = "[éphémère]"` + `split_ephemeral` dans `agent_tasks.py`,
  catégorie de scène `EPHEMERAL_CATEGORY = "ephemere"`, et **une exception à la Décision 12 de la
  scène** : `runtime` reçoit `SceneOp.ARCHIVE` pour archiver l'étoile d'une éphémère réussie
  (`_plan_archive`), journal `core.scene.ephemeral_retired`, et le projecteur ne crée pas l'étoile
  d'une éphémère déjà réussie.
- Rapport à main : c'est un **prototype antérieur et supplanté**. Main a fusionné une autre version
  le même jour (`3bc7acf2`, « Fusion de feat/ephemeral-tasks ») : marqueur `EPHEMERAL_MARKER`,
  `parse_ephemeral_description`, silence décidé par le code, masquage côté page, **sans** archivage
  runtime ni catégorie dédiée. Les deux diffèrent (noms de symboles, grammaire, autorité de scène) ;
  `eph` ne se fusionne plus proprement.
- Rapport à l'exigence D08 « pas d'étoile persistante pour une éphémère terminée » : main **ne la
  satisfait pas** (étoile persistée, seulement masquée par la vue) ; `eph` s'en approchait par
  archivage, mais un archivage laisse une ligne d'historique/tombstone dans `scene.sqlite3`, ce que
  `docs/02-architecture.md` §4 déconseille. Ni l'un ni l'autre n'est à reprendre tel quel ; la
  Slice 08 choisit la voie (§5, Slice 08).
- Ce worktree contient du travail non commité : ne pas le supprimer sans accord (Q3).

### 2.4 Conflits réels avec les décisions verrouillées

Aucun conflit qui rende une décision impossible. Trois tensions, traitées sans changer les décisions :

1. **D21 / I-003 et `EXECUTION_GATE_RULE`.** D21 interdit d'inventer une *nouvelle* porte
   *universelle* et demande de préserver les règles d'autorité actuelles. La porte existante n'est
   ni nouvelle (sur main avant la base) ni universelle (cas B seulement) : elle **fait partie** des
   règles actuelles. Lecture retenue : la Slice 07 la préserve, ne la généralise pas, ne la
   supprime pas. I-003 est mis à jour en ce sens.
2. **D08 et le comportement éphémère de main.** Main garde l'étoile en base ; D08 demande qu'elle
   ne reste pas. C'est un écart d'implémentation, pas une contradiction : la Slice 08 le comble.
3. **Sens du mot « éphémère » (Q1).** Sur main, « éphémère » = travail rapide *dont l'utilisateur
   n'attend aucun compte rendu* : la réussite est **silencieuse** et le prompt l'interdit pour un
   travail dont on attend le résultat (`claude_local.py:101`). Le handoff l'emploie pour « une
   correction de fichier, une note, un renommage » qui ne doit pas encombrer l'historique (D07/D08,
   1er critère d'acceptation). Une correction déclarée éphémère serait donc tue à la réussite. Les
   deux sens ne s'excluent pas mais ne coïncident pas ; trancher avant la Slice 05 (§6, Q1).

### 2.5 Incompatibilité technique trouvée : marqueurs éphémère + profil + rôle

La grammaire éphémère exige `[éphémère]` **en tête** (`agent_tasks.py:73`, `:196`), alors que le hook
lit le profil puis le rôle **en tête** (`routing_hook.py:88-117`) : `[éphémère] [code] [coder] …`
fait perdre profil et rôle (le premier crochet est consommé comme profil inconnu → `general`, rôle
`None`), et `[code] [coder] [éphémère] …` fait perdre le drapeau éphémère. Aujourd'hui une tâche
éphémère ne peut donc pas porter de rôle. La Slice 01 doit définir **une seule grammaire composée**
(ou un champ structuré équivalent) lue par le tracker et le hook, testée dans les deux sens.

---

## 3. I-001 Task Type et I-002 persistance

### I-001 — Task Type : résolu par levée (précédent de l'agent 0)

Aucun vocabulaire Workspace Task Type n'existe dans le dépôt ni dans les autres handoffs (tous
`null`/`waived`). Précédent appliqué :
`C:/Projects/jarvis/boqa/tasks/jarvis-unified-chat-and-board-drop/slices/00-project-manager/metadata.json`
(`"task_type": "waived-by-agent-0"` + `task_type_blocker`). Aucun libellé inventé. Les
`metadata.json` des Slices 00 à 13 et `task.json` sont mis à jour (blocker retiré, résolution
notée).

### I-002 — Seam de persistance de l'historique de mission : `jarvis.sqlite3` v10

Domaines persistants examinés et écartés :

| Candidat | Pourquoi pas |
| --- | --- |
| Work State | mémoire seule par conception (`ARCHITECTURE.md:1692`), borné à 64 éléments ; D16 lui garde le seul statut vivant |
| `scene.sqlite3` | projection (D17) ; `category` écrivable par le cerveau/l'utilisateur ; l'utilisateur peut archiver ; ne doit pas devenir source |
| Conversation Events | registre d'une *conversation*, append-only, attributs sur liste blanche ; un sous-agent non attribué n'y écrit rien (`subagent_conversation.py:22`) ; pas de relations ni de tableaux de messages |
| `artifacts` / `artifact_relations` (v6) | relations de provenance entre artefacts, refus des cycles, pas des instances d'agent |
| `jobs` | jobs Core, pas les sous-agents CLI |
| Dossier `mission.md` | prose partagée éditable par plusieurs agents, sans transaction ni schéma ; reste le contexte lisible, référencé par la mission |

**Choix :** nouvelles tables additives dans `jarvis.sqlite3` par l'étape `_MIGRATIONS[10]` de
`jarvis/adapters/sqlite_state.py` (`_SCHEMA_VERSION` 9 → 10, sauvegarde automatique
`jarvis.sqlite3.v9.bak`, instantané `tests/schema/jarvis_state.v10.sql`), adaptateur dédié
`jarvis/adapters/sqlite_mission_history.py` sur la connexion partagée (`run_serialized`, patron
`sqlite_artifacts.py`), port `jarvis/ports/mission_history.py`, service Core
`jarvis/core/mission_history.py`. Tables indicatives : missions, instances d'agent (rôle figé,
éphémère figé, mission, parent, `(source, external_id)` / `work_key` stable), relations typées et
participants, messages de relation, paquets de handoff. Aucune colonne de statut d'exécution,
aucune colonne de blob fournisseur. Si une autre tâche publie une v10 avant la Slice 03, la
migration prend le numéro suivant (contrôle de fraîcheur).

Points d'attention pour la Slice 03 :
- l'identifiant `AgentTask.id` passe de `tool_use_id` à `task_id` en cours de vie
  (`subagent_conversation.py:24-25`) : lier sur le `work_key` stable, pas sur l'id brut ;
- au redémarrage de Core, Work State est vide puis rejoué : l'historique ne doit rien en déduire
  (rôle figé non réécrit) ;
- éphémère : ne jamais écrire de ligne durable pour une instance éphémère tant qu'elle n'a pas
  perdu le drapeau (échec ⇒ devient ordinaire et peut alors être retenue).

Une Scene v2 sera probablement nécessaire à la Slice 08 (nouvelles natures de relation et champ de
rôle réservé au runtime) : un binaire v1 refuserait de décoder ; même règle de migration
(`sqlite_scene._MIGRATIONS[2]`, `tests/schema/scene.v2.sql`).

---

## 4. Placement des docs canoniques (décision de la Slice 00)

| Sujet | Page |
| --- | --- |
| Rôles, Mission Owner, missions, éphémère | `docs/subagent-roles.md` (créée par la Slice 01 ; déjà promise par `subagent_roles.py:22`) |
| Relations, messages, handoff, frontière de raisonnement | `docs/agent-relations.md` (Slice 02) |
| Historique de mission vs Work State | `docs/mission-history.md` (Slice 03) + renvoi depuis `docs/ARCHITECTURE.md` « Core work state » |
| Work Methods et candidats | `docs/work-methods.md` (Slices 01/04/12) |
| Graphe de tâches | `docs/scene-model.md` + `docs/ARCHITECTURE.md` « Scene renderer » + `docs/control-center-shell.md` (Slices 08/09) |
| Onglet Settings rôles | `docs/settings/INDEX.md` + section de `docs/subagent-roles.md` (Slice 10) ; renvoi depuis `docs/skills-and-loadouts.md` |
| Qualité de livraison | section de `docs/subagent-roles.md` + `docs/prefabs.md` « Consumers » (Slice 11) |

---

## 5. Amendements des Slices (résumé ; texte complet dans chaque `SLICE.md`)

- **01** : étendre `jarvis/domain/subagent_roles.py` (pas de nouveau module de rôles) ; ids actuels
  conservés ; alias `reviewer` ; grammaire composée éphémère + profil + rôle ; Mission référence le
  dossier `mission.md` ; crée `docs/subagent-roles.md`.
- **02** : inchangée sur le fond ; rappel que `RelationKind` de Scene ne sert pas de modèle canonique.
- **03** : seam fixé (`sqlite_state` v10 + adaptateur dédié) ; chemins corrigés (`work_ingress.py`,
  `jarvis/domain/brain_context.py`, `jarvis/runtime/work_brief.py`) ; rôle porté jusqu'à
  `WorkObservation` ; `work_key` stable.
- **04** : le registre canonique **est** `subagent_roles` étendu ; `GET /api/subagent-roles` étendu ;
  `LOADOUT_ROLES` étendu additivement si un rôle reçoit un loadout ; le prompt d'édition reste
  `subagent_role.<id>`.
- **05** : spawn réel = outil `Agent` du CLI + hook `PreToolUse` ; Core ne lance rien ; vérifier le
  spawn imbriqué et la présence des outils MCP Core dans les sous-agents ; Codex sans sous-tâches.
  Q1 tranchée avant dispatch.
- **06** : rien de spécifique hors chemins.
- **07** : amender `brain_rules()` et les instructions de l'Intervieweur existantes ; préserver
  `EXECUTION_GATE_RULE` ; reprendre l'essai en bac à sable du plan `subag`.
- **08** : rôle dans un champ réservé au runtime, pas dans `category` ; voie D08 à choisir
  (recommandée : ne jamais projeter une éphémère dans la scène persistée ; visibilité vivante par le
  panneau Agents / la table de travail déjà branchés) ; ne pas reprendre l'archivage runtime d'`eph` ;
  Scene v2 probable.
- **09** : partir du rendu éphémère existant (`control_center_scene_page.js`, `showEphemeral`) ;
  surveiller `bor` et `3351ef59`.
- **10** : c'est l'onglet « Sous-agents » de l'autre tâche ; édition des instructions via
  `/api/prompts` incluse ; instances actives à part.
- **11, 12** : chemins confirmés ; 12 persiste ses candidats dans la même base (migration suivante).
- **13** : inclut l'essai réel en bac à sable et la clôture de l'absorption.

---

## 6. Questions pour le Human (aucune ne bloque les Slices 01 à 04)

- **Q1 — sens d'« éphémère » (avant la Slice 05).** Aujourd'hui une éphémère réussit en silence et
  ne sert jamais à un travail dont vous attendez le résultat. Le handoff veut qu'une petite
  correction puisse être éphémère pour ne pas encombrer l'historique.
  *Recommandation :* garder **un seul** drapeau, avec son silence actuel, et élargir la règle du
  cerveau aux petites corrections dont le changement visible suffit comme compte rendu (renommer,
  corriger une coquille) ; un correctif de bug dont vous attendez la confirmation reste une tâche
  ordinaire, à un seul agent, qui reste dans l'historique. Un échec reste toujours annoncé.
  Alternative : séparer « ne pas garder dans l'historique » de « ne pas annoncer » (deux drapeaux).
- **Q2 — tâche `jarvis-subagent-roles-interview`.** *Recommandation :* la considérer absorbée par
  celle-ci (Slices 10, 01/04, 07/13), la déplacer sur Drive vers done avec cette mention, et
  supprimer le worktree `subag` (propre, intégré) à la clôture.
- **Q3 — worktree `eph`.** Prototype supplanté avec 13 fichiers non commités. *Recommandation :*
  le garder intact jusqu'à votre décision ; s'il n'a plus de valeur pour vous, le mettre de côté
  (copie du diff) puis le supprimer.

---

## 7. Contrôle de fraîcheur avant chaque dispatch de Slice

À exécuter par le PM dans `C:/Projects/jarvis/orch`, résultat consigné dans `LOG.md` :

1. `git fetch` ; `git log --oneline HEAD..origin/main`. Si non vide : merger `origin/main` dans la
   branche de tâche avant dispatch, puis relancer un balayage large des tests touchés.
2. `git diff --stat <dernier contrôle>..origin/main -- <chemins de la Slice>` (liste
   `freshness_paths` du `metadata.json`). Tout changement sur ces chemins ⇒ relire et amender la
   `SLICE.md` avant dispatch.
3. Versions de schéma : `grep -n "^_SCHEMA_VERSION" jarvis/adapters/sqlite_state.py
   jarvis/adapters/sqlite_scene.py` (référence au 2026-10-20 : state 9, scene 1). Si elles ont
   bougé, renuméroter la migration prévue.
4. Recoupements vivants : `git worktree list`, puis pour chaque worktree actif
   `git -C <wt> status --short -- <chemins de la Slice>` et
   `git log --oneline main..<branche> -- <chemins>` (au minimum `bor`, `eph`, `subag`). Un writer
   concurrent sur les mêmes fichiers ⇒ attendre ou réordonner.
5. Lot de tests de référence de la Slice en avant-plan (petits lots,
   `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest`) ; noter à part les échecs déjà
   présents sur main (`test_brain_capability_parity`, `test_brain_delegation`).
6. Vérifier que la Q bloquante éventuelle de la Slice est tranchée (Q1 pour 05/07).
