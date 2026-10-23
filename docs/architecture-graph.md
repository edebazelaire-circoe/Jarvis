# Graphe d'architecture : contrat runtime

Le graphe d'architecture est la vue **opérationnelle** des cerveaux de JARVIS et de leurs liaisons audio et
système : Réglages › Architecture & Agents › onglet Architecture. Ce n'est pas un schéma décoratif : chaque
liaison basculable correspond à un réglage runtime réel, et la basculer change le chemin d'appel réel.

Règle produit : **le graphe décide de ce qui peut parler à quoi ; un cerveau décide quand il délègue ; la
configuration globale des sous-agents décide quel agent ou modèle exécute un rôle délégué.**

## 1. Modules

| Module | Rôle |
| --- | --- |
| `jarvis/domain/architecture_graph.py` | Types purs (nœud, port, liaison, snapshot, disposition), compatibilité des ports, codes d'erreur stables |
| `jarvis/runtime/architecture_graph.py` | Projection du runtime vivant, service de mutation transactionnelle, `FileSettingsStore`, observations |
| `jarvis/runtime/architecture_layout.py` | Store de disposition (positions), séparé de la topologie |
| `jarvis/runtime/architecture_graph_routes.py` | Routes aiohttp `ArchitectureGraphRoutes.routes()`, **non montées** : le Control Center les monte (Slice 07) |
| `tests/fixtures/architecture_snapshot_{duplex,simple}.json` | Fixtures de l'interface, produites par la projection (`JARVIS_WRITE_ARCHITECTURE_FIXTURES=1 pytest tests/unit/test_architecture_graph.py`) |

Le graphe n'a **pas d'état propre**. Il projette des réglages qui existent ailleurs (`binding`) et observe ce qui
tourne d'après les publications des processus :

- battement `<runtime>/.voice_runtime` de Voice (identité de configuration chargée, frais = moins de 5 s) ;
- publication `<runtime>/tool-brain-ownership.json` du Tool Brain (mode vivant, propriété de l'écran) ;
- jeton `<runtime>/core.token` (Core démarré).

## 2. Forme JSON (`GET /api/architecture`)

Le snapshot lui-même, sans enveloppe. `schema_version: 1`. Champs fixés par le contrat de la tâche
(`tasks/jarvis-architecture-agents-settings-editor/docs/11-graph-wire-contract.md`) ; les ajouts sont marqués *ajout*.

- `revision` : `t-<empreinte>`, **calculée** à partir des réglages persistés qui portent la topologie
  (`voice_architecture`, `voice_arch`, `voice_stack`, `voice_surface`, `tool_brain`) et des variables
  `JARVIS_TOOL_BRAIN`, `JARVIS_VOICE_ARCH`, `JARVIS_VOICE_STACK`. Toute écriture d'un de ces réglages, par le
  graphe ou par une autre page, la périme. L'état vivant n'y entre pas : un battement manqué ne refuse pas une
  écriture.
- `voice_architecture` : `{id, label, settings_target: "architecture_compat", source}` (*ajout* : `source` =
  `settings` | `env` | `default`). `id` ∈ `simple`, `front_brain`, `duplex`, `legacy`, `continuous_brain`,
  `unknown`. Le choix de l'architecture reste dans Avancé ; le graphe l'affiche en lecture seule.
- `nodes[]` : `id`, `kind` (`brain` | `endpoint` | `pool`), `label`, `brain_type` ou `endpoint_type`,
  `process`, `system`, `state` (`active` | `inactive` | `shadow` | `unavailable`), `state_reason`,
  `activation {mutable, reason}`, `configurable`, `ports[]`, *ajout* `details` (lecture seule, propre au nœud).
- `ports[]` : `id`, `direction` (`in` | `out`), `channel`, `family`. Deux ports se relient seulement d'une
  sortie vers une entrée, de même canal et de même famille (`port_incompatibility`).
- `connections[]` : `id` (`<nœud>.<port>-><nœud>.<port>`), `source`, `target`, `channel` (`audio` | `request` |
  `response` | `tool_call` | `event` | `speech`), `purpose`, `enabled`, `mutability`, `locked_reason`,
  `impact_when_disabled`, `applies`, `pending`, `governed_by`, `binding`.

### Nœuds réels par architecture

Seuls les nœuds qui existent dans l'architecture vocale effective sont projetés. Aucun cerveau spéculatif.

| Nœud | `id` | Présent |
| --- | --- | --- |
| Micro (entrée audio) | `mic` | toujours |
| Surface vocale (Realtime, GPT-Live ou Gemini Live) | `voice` | toujours |
| Front Brain « Luna » | `luna` | `front_brain` seulement |
| Core Brain (BrainOrchestrator, CLI cerveau, Back Brain worker) | `core` | toujours |
| Tool Brain | `tool_brain` | toujours, `inactive` quand il est coupé |
| Sous-agents (pool CLI, outil `Agent`) | `subagents` | toujours |
| Haut-parleurs (sortie audio) | `speakers` | toujours |

Les identifiants de nœud sont stables ; la configuration des cerveaux les réutilise ([brain-config.md](brain-config.md)).

## 3. Liaisons et mutabilité

| Liaison | Canal | Mutabilité | `binding` | `applies` |
| --- | --- | --- | --- | --- |
| `mic.audio_out->voice.audio_in` | audio | `required_locked` | `fixed:voice.capture` | `voice_restart` |
| `voice.audio_out->speakers.audio_in` | audio | `required_locked` | `fixed:voice.playback` | `voice_restart` |
| `voice.delegate->core.request` (Duplex) | request | `toggleable` | `voice_architecture.config.brain_orchestration` | `voice_restart` |
| `voice.delegate->core.job` (Simple, Front Brain) | tool_call | `toggleable` | `voice_surface.back_brain_delegation` | `voice_restart` |
| `voice.delegate->core.request` (cerveau continu) | request | `required_locked` | `voice_architecture` | `voice_restart` |
| `voice.delegate->core.job` (legacy, `claude_task`) | tool_call | `required_locked` | `voice_architecture` | `voice_restart` |
| `voice.transcripts->luna.transcripts`, `luna.hints->voice.hints` | event | `required_locked` | `voice_architecture` | `voice_restart` |
| `core.speech->voice.speech_in` | speech | `required_locked` | `fixed:brain.speech.requested` | `live` |
| `core.events->tool_brain.wake` | event | `toggleable`, `required_locked` si `JARVIS_TOOL_BRAIN` est posée | `tool_brain.mode` | `core_restart` |
| `core.agents->subagents.spawn` | tool_call | `governed` | `brain_config.core.delegation` | `null` |

`binding` préfixé `fixed:` : chemin du code sans interrupteur. Une liaison `required_locked` porte toujours son
`locked_reason`.

- **Duplex** : désactivée, la délégation Live retombe sur l'analyse spéculative de Core, sans outils ni
  sous-agents (`live_delegation.py`).
- **Simple / Front Brain** : nouveau réglage `voice_surface.back_brain_delegation` (bloc de
  `control-center-settings.json`, absent = `true`). À `false`, `RealtimeFrontendSession.connect` retire
  `back_brain_delegate` du catalogue de la session, ne construit pas le contrôleur de délégation (un appel
  halluciné répond `unavailable`) et ajoute la consigne `VOICE_ALONE_RULE` (déclarée dans les preuves de prompt,
  `voice.back_brain_delegation.disabled.v1`) : la voix traite seule. Le réglage entre dans l'identité de
  configuration de Voice (`VoiceComposition.configuration_id`, seulement quand il est coupé).
- **Tool Brain** : nouveau réglage persistant `tool_brain.mode` (`off` | `shadow` | `active`), lu par
  `tool_brain_wiring.resolve_mode` au démarrage de Core. `JARVIS_TOOL_BRAIN` posée (non vide) garde la priorité et
  verrouille la liaison avec la raison « imposé par l'environnement ». Activer la liaison écrit `shadow`, ou
  `active` si c'était la valeur persistée ; la désactiver écrit `off`.
- **Sous-agents** : lecture seule sur le graphe, `governed_by = {"kind": "brain_config", "node": "core",
  "field": "delegation"}`. Son seul écrivain est le champ de délégation de la configuration du cerveau
  (`<runtime>/brain-config.json`, [brain-config.md](brain-config.md) § 3) ; `applies` est alors celui de ce champ.
  `enabled = delegation != never` : `never` retire l'outil `Agent` au lancement du CLI cerveau et le hook refuse
  l'appel du cerveau dès l'appel suivant. La tendance n'entre dans la révision de topologie que hors du défaut
  `standard`.
- **Mode du Tool Brain** (`off` | `shadow` | `active`) : réglage du nœud, écrit par
  `ArchitectureGraphService.set_tool_brain_mode` (fenêtre du cerveau), même bloc `tool_brain.mode` et même
  révision que la liaison.

## 4. Écritures

| Route | Corps |
| --- | --- |
| `POST /api/architecture/connections/{id}` | `{"base_revision", "enabled"}` |
| `POST /api/architecture/connections` | `{"base_revision", "source": {node, port}, "target": {node, port}, "channel"}` |
| `DELETE /api/architecture/connections/{id}?base_revision=` | - |

Succès : `200 {"ok": true, "changed": bool, "snapshot": {…}}`. Refus : `{"ok": false, "code", "reason",
"snapshot"}`, `reason` en français.

| Code | Statut | Quand |
| --- | --- | --- |
| `architecture_revision_stale` | 409 | `base_revision` différente de la révision courante |
| `connection_locked` | 423 | liaison `required_locked` |
| `connection_governed` | 422 | liaison `governed` : se règle dans la fenêtre du cerveau |
| `connection_unknown` | 422 | liaison ou nœud absent de l'architecture courante |
| `connection_incompatible` | 422 | ports de sens, canal ou famille incompatibles |
| `connection_unbindable` | 422 | *ajout* : ports compatibles mais aucun mécanisme du runtime ne porte la liaison |
| `connection_not_removable` | 422 | *ajout* : suppression d'une liaison basculable (la désactiver) |
| `architecture_request_invalid` | 400 | *ajout* : corps illisible ou champ mal typé |
| `architecture_apply_failed` | 500 | configuration cible refusée, écriture impossible, ou bascule de Voice impossible |
| `architecture_snapshot_failed` | 500 | *ajout* : lecture du snapshot impossible (`GET`) |

Aucune liaison `creatable_removable` n'existe dans le runtime actuel : création et suppression sont refusées avec
une raison. La valeur reste au contrat pour un futur cerveau.

**Transaction.** Sous un verrou du processus : relecture des réglages, révision, mutabilité ; calcul des
réglages cibles et validation complète (projection cohérente, composition vocale cible démarrable) **avant**
toute écriture ; écriture atomique (temporaire puis remplacement) ; pour une liaison vocale, demande de bascule
de Voice (`voice_switch`, même règle que `POST /api/settings`). Si la bascule ne peut pas être demandée, les
réglages précédents sont réécrits et la réponse est `500 architecture_apply_failed`. Écrire la valeur déjà en
place est un succès sans écriture (`changed: false`). Le retour porte toujours le snapshot relu après coup.

Journal (`RuntimeJournal`) : `architecture.connection.updated` | `unchanged` | `rejected` | `write_failed` |
`rolled_back` | `rollback_failed`, `architecture.write.refused`, `voice.switch.requested`.

## 5. Application différée (`applies`, `pending`)

- `live` : effet immédiat (aucune liaison basculable ne l'est aujourd'hui).
- `next_turn` : relu au tour suivant (réservé ; aucune liaison actuelle).
- `voice_restart` (*ajout*) : relu au démarrage de Voice. L'écriture demande la bascule de Voice, qui ferme la
  surface au point sûr et la relance sur la nouvelle configuration, la conversation continuant.
- `core_restart` : relu au démarrage de Core (Tool Brain). L'écriture est acceptée et persistée ; elle vaut au
  prochain démarrage de Core. Aucun agent ne redémarre JARVIS (CLAUDE.md).

`enabled` est l'état du runtime **vivant** ; `pending = {"enabled", "applies"}` signale une valeur persistée qui
attend son redémarrage :

- Voice : si l'identité publiée par Voice diffère de celle des réglages et que la valeur opposée de **cette**
  liaison l'explique, `enabled` = ancienne valeur, `pending` = nouvelle. Voice arrêté ou écart dû à un autre
  réglage : valeur persistée, sans `pending`.
- Tool Brain : mode vivant = mode publié s'il est frais, `off` sans publication fraîche (un Tool Brain coupé ne
  publie rien) ; inconnu si Core est arrêté ou la publication illisible (valeur persistée, sans `pending`).

## 6. Disposition (interface seule)

`GET /api/architecture/layout` → `{"ok", "schema_version", "revision": "l-<n>", "positions": {nœud: {x, y}}}` ;
`PUT` avec `{"base_revision", "positions"}`. Fichier `<runtime>/architecture-layout.json`, révision compteur
propre, `409 layout_revision_stale`, `400 layout_invalid` (coordonnées finies, bornées), `500
layout_write_failed`. Aucun module du runtime ne le lit et il n'entre pas dans la révision de la topologie.
Une disposition illisible est signalée (`architecture.layout.unreadable`) puis traitée comme vide.

## 7. Limites connues

- L'environnement consulté pour « imposé par l'environnement » et pour l'architecture vocale est celui du
  processus du Control Center, qui héberge le service ; Core et Voice sont lancés avec le même `.env`.
- Le verrou (`write_lock`) sérialise les écritures du graphe et celles de la configuration des cerveaux
  ([brain-config.md](brain-config.md), qui réutilise `write_settings` pour l'écriture et la bascule de Voice) ;
  une écriture concurrente de `/api/settings` est détectée par la révision calculée, pas empêchée.
- La règle de bascule de Voice existe aussi en ligne dans `ControlCenter` ; elle sera mise en commun au
  branchement des routes (Slice 07).
