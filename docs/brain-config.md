# Configuration des cerveaux : contrat runtime

La configuration d'un cerveau s'ouvre depuis le graphe d'architecture (clic droit sur un cerveau, fenêtre
flottante : Réglages › Architecture & Agents). Ce n'est pas un onglet. Ce contrat dit ce que la fenêtre lit et
écrit, et **qui est propriétaire** de chaque valeur.

Règle produit : **le graphe décide de ce qui peut parler à quoi ; un cerveau décide quand il délègue ; la
configuration globale des sous-agents décide quel agent ou modèle exécute un rôle délégué.** La configuration
d'un cerveau ne choisit donc jamais le modèle d'un rôle de sous-agent ([subagent-roles.md](subagent-roles.md)
§ 10), et ne porte aucune personnalité (ton, politesse, longueur, humour : page Personnalisation).

## 1. Modules

| Module | Rôle |
| --- | --- |
| `jarvis/domain/brain_config.py` | Vocabulaire pur : `DelegationTendency`, libellés, consigne par niveau, missions, codes d'erreur et statuts |
| `jarvis/runtime/brain_config_store.py` | `<runtime>/brain-config.json` : la tendance de délégation, révisée ; lecteurs à froid (hook, CLI, graphe) |
| `jarvis/runtime/brain_config.py` | `BrainConfigService` : descripteur par cerveau, écriture chez chaque propriétaire |
| `jarvis/runtime/brain_config_http.py` | `BrainConfigRoutes.routes()`, montées par le Control Center (`_install_architecture_services`, Slice 07) ; catalogue = `ControlCenter._catalog_view_dict` (le calcul de `GET /api/catalog`) |
| `tests/fixtures/brain_config_{core,voice}.json` | Fixtures de la fenêtre du cerveau (Slice 05), produites par le service (`JARVIS_WRITE_BRAIN_CONFIG_FIXTURES=1 pytest tests/unit/test_brain_config.py`) |

Les identifiants de cerveau sont ceux des nœuds du graphe ([architecture-graph.md](architecture-graph.md)) :
`voice`, `luna` (Front Brain seulement), `core`, `tool_brain`. Il n'y a pas de second registre.

## 2. Champs et propriétaires

Un descripteur ne montre que les champs que le cerveau supporte. Chaque champ porte `value`, `editable`, `reason`,
`applies` (`live` | `next_turn` | `voice_restart` | `core_restart`, comme le graphe) et `owner` (le réglage qui
porte la valeur). Aucune valeur n'est copiée : on lit et on écrit chez le propriétaire.

| Cerveau | Champ | Propriétaire | Modifiable | `applies` |
| --- | --- | --- | --- | --- |
| `core` | `provider` | `agent_cli` | oui | `core_restart` |
| `core` | `model` | `agent_cli_settings.<cli>.model` | oui | `core_restart` |
| `core` | `instructions` | surcharge `backend.system.addition` | oui | `core_restart` |
| `core` | `delegation` | `brain-config.json` (`brain_config.core.delegation`) | oui | voir § 3 |
| `core` | `activation` | - | non (« Core porte la conversation… ») | - |
| `voice` | `model` | `voice_architecture.config.conversation_model` (`reflex_model` en Front Brain) | oui, hors compatibilité | `voice_restart` |
| `voice` | `model` (legacy, cerveau continu) | `voice_stack` | non, Avancé › Architecture & compatibilité | - |
| `voice` | `instructions` | `live.duplex.addition` (Duplex), sinon `voice.conversation.addition` | oui | `voice_restart` |
| `luna` | `model` | `voice_architecture.config.analysis_model` | oui | `voice_restart` |
| `luna` | `instructions` | `front_brain.analysis.addition` | oui | `voice_restart` |
| `tool_brain` | `model` | `tool_brain.model` ; `JARVIS_TOOL_BRAIN_MODEL` posée : prioritaire, champ verrouillé | oui sauf env | `next_turn` (relu à chaque décision) |
| `tool_brain` | `activation` | `tool_brain.mode`, écrit par le service du graphe | oui sauf `JARVIS_TOOL_BRAIN` posée | `core_restart` |
| `tool_brain` | `instructions` | - | non (consigne hors catalogue des prompts) | - |
| tous | `mission` | texte du code (`BRAIN_MISSIONS`) | non (aucune mission de cerveau n'est enregistrée) | - |
| `voice`, `luna`, `tool_brain` | `delegation` | - | `not_applicable`, avec la raison | - |

Hors contrat, et jamais dans le descripteur : commande, chemin et autorisations du CLI (Avancé), modèle d'un rôle
de sous-agent (onglet Sous-agents), `voice.persona`.

- **Choix de modèle** : seulement ceux du catalogue serveur (`(surface, role)` → la même vue que
  `GET /api/catalog`, injectée). Core : surface `subagents`, rôle `text`, filtrés sur le CLI choisi. Voix : surface
  `voice`, rôle `duplex` ou `realtime`, même fournisseur que l'architecture. Luna : `voice`/`analysis`. Tool Brain :
  `subagents`/`text`, CLI Claude. Chaque choix dit `available` et sa raison ; un élément indisponible reste visible.
  Une valeur enregistrée absente du catalogue est montrée `available: false`, `state: "unlisted"`, et reste
  appliquée. Le choix « défaut » (valeur vide) est toujours légal. Un CLI détecté dont le catalogue ne vérifie ni
  le modèle par défaut ni l'authentification (`state: "configured_unverified"`, jamais `selectable` dans le
  catalogue) est un choix légal pour le CLI de Core et pour « défaut du CLI » (`available: true`, raison « se
  vérifient qu'à l'usage ») : sans cela, Codex installé ne pouvait pas être choisi (constat de la Slice 08).
- **Modèle vocal** : validé par le registre vocal **et** la composition (`resolve_voice_composition`) avant
  écriture ; un modèle listé par le fournisseur sans adaptateur prêt est refusé sans rien écrire. L'écriture
  réutilise la transaction du graphe (`ArchitectureGraphService.write_settings`) : écriture atomique, demande de
  bascule de Voice, réglage précédent rétabli si la bascule ne peut pas être demandée.
- **Instructions** : mécanisme `prompt_overrides` existant (`PromptOverrideStore.edit`), avec sa révision
  `effective_revision` : refus `prompt_override_stale` ou `prompt_override_concurrent` (409). Rien n'est dupliqué.
- **Activation du Tool Brain** : `ArchitectureGraphService.set_tool_brain_mode`, seul autre écrivain du bloc
  `tool_brain.mode` avec la liaison `core.events->tool_brain.wake` du graphe.

## 3. Tendance de délégation

Enum neutre et stable sur le fil : `never` | `rare` | `standard` | `proactive` | `exploratory` (libellés : Jamais,
Rare, Standard, Proactive, Exploratoire). **Défaut `standard` = comportement d'avant, exactement** : aucune
migration n'écrit rien, le prompt est identique octet pour octet.

Seul `core` porte une tendance : c'est le seul cerveau qui lance des sous-agents (CLI cerveau du Board et jobs
Back Brain, outil `Agent`). Avec le CLI Codex, le réglage est enregistré mais sans effet (Codex ne lance pas de
sous-agents dans JARVIS) ; le descripteur le dit.

| Mécanisme | Niveaux | Effet | Quand |
| --- | --- | --- | --- |
| Hook `PreToolUse` (`routing_hook._delegation_guard`) | `never` | refuse tout appel `Agent`/`Task` **du cerveau** (`agent_id` absent) ; un sous-agent déjà lancé finit sa mission | `live` : fichier relu à chaque appel |
| `--disallowedTools Agent Task` (`ClaudeLocalAgent.start`) | `never` | l'outil n'existe plus pour le cerveau ni pour un job Back Brain | au lancement du CLI : redémarrage de JARVIS pour le cerveau du Board, job suivant pour le Back Brain |
| Consigne du prompt (`backend.claude.conversation.system`) | tous | la phrase « Dans le doute, délègue. » de `BRAIN_SYSTEM_PROMPT` est remplacée par la consigne du niveau (`DELEGATION_RULES`) ; `standard` la garde | conversation neuve : une conversation reprise (`--resume`) garde son prompt |

Le champ déclare donc `applies: "core_restart"` et détaille chaque mécanisme dans `enforcement`. Passer à `never`
coupe la délégation dès l'appel suivant (hook) ; revenir de `never` ne rend l'outil qu'au prochain lancement du
CLI cerveau.

Le prompt est rendu par le descripteur dynamique `backend.claude.conversation.system` (`prompt_catalog._brain_system`,
variable `brain_delegation` posée par `ClaudeLocalAgent.start`). Sans variable, ou avec une valeur inattendue, le
rendu est `standard`. `apply_delegation_rule` refuse un prompt où la phrase ne figure pas exactement une fois : une
réécriture du prompt qui la perdrait casse le test au lieu de perdre la tendance en silence.

Ce passage du descripteur en dynamique a changé **une fois** le `static_fingerprint` des programmes
`backend.claude.conversation.*` (la `default_revision` du descripteur inclut le drapeau `dynamic`). Le texte rendu,
lui, n'a pas changé : `render_fingerprint` est identique en `standard`. Une preuve de prompt antérieure à la
Slice 02 ne se compare donc pas par `static_fingerprint`, seulement par le rendu.

Graphe : la liaison gouvernée `core.agents->subagents.spawn` dit l'état du CLI **vivant**. `ClaudeLocalAgent.start`
(profil `conversation`) publie ce que le CLI cerveau a reçu dans `<runtime>/brain-delegation-launched.json`
(`{delegation, pid, launched_at}`, écriture atomique ; un échec est journalisé `agent.delegation.publish_failed`).

| Enregistré | Dernier lancement | `enabled` | `pending` |
| --- | --- | --- | --- |
| `never` | quelconque | `false` (le hook refuse dès l'appel suivant) | `null` |
| autre | `never` | `false` (le CLI vivant n'a pas l'outil) | `{"enabled": true, "applies": "core_restart"}` |
| autre | autre, ou inconnu | `true` | `null` |

Le descripteur du cerveau Core ajoute `launched` et `pending_relaunch` au champ `delegation` (la consigne et l'outil
attendent la relance). Limite : c'est le **dernier** lancement d'un CLI cerveau du poste ; avec plusieurs Boards,
un autre CLI encore vivant peut avoir reçu une valeur plus ancienne. Une publication illisible ou absente : valeur
enregistrée, sans `pending`. La tendance entre dans la révision de topologie seulement hors du défaut ; le dernier
lancement n'y entre pas (état vivant).

Trace : un refus est journalisé `agent.spawn_refused`, `code: "brain_delegation_never"`, avec le `tool_use_id`
(aucun texte de consigne) ; le lancement du CLI journalise `agent.start` avec `delegation` et
`spawn_tools_removed`. Un fichier illisible (JSON invalide, UTF-16 écrit par `Out-File` de PowerShell 5.1,
octets abîmés) se lit `standard` et se dit `agent.delegation.unreadable`, côté hook comme au lancement du CLI : ni
le hook, ni le lancement, ni le graphe ne lèvent sur une panne. Même règle pour `subagent-role-routing.json`.

### Pourquoi un fichier dédié

`<runtime>/brain-config.json` et non une clé de `control-center-settings.json` : `POST /api/settings` relit ce
fichier, applique son corps puis le réécrit entier, sans révision ni verrou partagé. Une clé à l'intérieur pourrait
être perdue par un enregistrement concurrent de la page Réglages, et la révision de ce réglage ne protégerait rien
(même choix que `subagent-role-routing.json`). Le fichier a un seul écrivain (`BrainConfigStore`, révision
`bc-<n>`, écriture atomique), et trois lecteurs à froid hors du Control Center (hook, lancement du CLI, graphe).

Forme : `{"schema_version": 1, "revision": 2, "brains": {"core": {"delegation": "never", "updated_at": "…"}}}`.
Absent : `standard` partout, révision `bc-0`. Une valeur inconnue est rapportée (`stored_invalid`) et le cerveau
garde `standard` jusqu'à un nouveau choix ; un fichier illisible n'est jamais réécrit
(`brain_config_store_unreadable`).

## 4. Lecture : `GET /api/brains/{brain_id}/config`

Le descripteur, sans enveloppe :

```json
{
  "schema_version": 1, "brain_id": "core", "revision": "c-15d1d0af96ae621e",
  "label": "Core Brain", "brain_type": "core", "process": "core", "system": true,
  "state": {"state": "active", "reason": ""},
  "voice_architecture": {"id": "duplex", "label": "Duplex", "settings_target": "architecture_compat", "source": "settings"},
  "fields": {
    "delegation": {"value": "standard", "editable": true, "reason": "", "applies": "core_restart",
                   "owner": "brain_config.core.delegation", "choices": [{"value": "never", "label": "Jamais", "description": "…"}],
                   "stored_invalid": null, "store_revision": "bc-0", "enforcement": [{"mechanism": "routing_hook", "applies": "live", "detail": "…"}]},
    "model": {"value": "claude-opus-5-5", "editable": true, "applies": "core_restart",
              "owner": "agent_cli_settings.claude.model",
              "choices": [{"value": "", "label": "Modèle par défaut du CLI", "available": true, "reason": ""}]},
    "instructions": {"value": "", "editable": true, "prompt_id": "backend.system.addition",
                     "effective_revision": "…", "default_revision": "…", "max_length": 8192}
  },
  "out_of_scope": {"personality": "…", "subagent_models": "…", "cli_technical": "…"},
  "connections": {"graph_revision": "t-…", "edit_on": "graph", "incoming": [], "outgoing": []},
  "catalog": {"status": "ok", "reason": ""},
  "store": {"status": "ok", "code": "", "reason": ""}
}
```

`revision` : `c-<empreinte>` **calculée** à partir de ce qui porte les champs du cerveau (réglages, variables
d'environnement, révision de `brain-config.json`). Une écriture faite ailleurs (`/api/settings`, graphe) la périme.
`connections` : résumé en lecture seule tiré du snapshot du graphe ; l'édition d'une liaison reste sur le graphe.

## 5. Écriture : `PATCH /api/brains/{brain_id}/config`

Corps : `{"base_revision": "c-…", <un champ>}` ; seul le couple `provider` + `model` de Core va ensemble (un même
fichier, une seule écriture atomique). Valeurs : `delegation: "never"`, `model: "<id>"` (vide = défaut),
`provider: "claude" | "codex"`, `activation: "off" | "shadow" | "active"`,
`instructions: {"text", "effective_revision"}` (révision lue dans le descripteur, obligatoire).

Succès : `200 {"ok": true, "changed", "applies", "config": {…}}` (descripteur relu). Refus : `{"ok": false, "code",
"reason", "field", "config"}`.

| Code | Statut | Quand |
| --- | --- | --- |
| `brain_config_unknown_brain` | 404 | identifiant hors `voice`, `luna`, `core`, `tool_brain` |
| `brain_config_brain_absent` | 409 | cerveau absent de l'architecture vocale courante (Luna hors Front Brain) |
| `brain_config_revision_stale` | 409 | `base_revision` périmée, ou réglages modifiés pendant l'écriture |
| `prompt_override_stale`, `prompt_override_concurrent` | 409 | instructions : défaut changé, ou modifiées ailleurs |
| `brain_config_request_invalid` | 400 | corps illisible, champ inconnu, plusieurs champs, `effective_revision` absente |
| `brain_config_field_unsupported` | 422 | champ que ce cerveau ne règle pas (p. ex. `delegation` sur la voix) |
| `brain_config_delegation_invalid` | 422 | niveau inconnu |
| `brain_config_model_unavailable` | 422 | modèle ou CLI non sélectionnable, ou refusé par la composition vocale |
| `brain_config_activation_invalid` | 422 | mode du Tool Brain inconnu |
| `brain_config_field_locked` | 423 | champ imposé par l'environnement ou non modifiable |
| `brain_config_catalog_unavailable` | 503 | catalogue indisponible : aucun choix vérifiable (le défaut reste permis) |
| `brain_config_store_unreadable`, `brain_config_write_failed`, `brain_config_snapshot_failed` | 500 | rien n'a changé |

Journal : `brain_config.read` | `saved` | `unchanged` | `rejected` | `apply_failed`, plus ceux du graphe
(`architecture.tool_brain.updated`, `voice.switch.requested`) et des surcharges (`prompt.override.*`).

## 6. Limites connues

- Les écritures de `control-center-settings.json` faites par ce service prennent le verrou du graphe
  (`ArchitectureGraphService.write_lock`) ; `/api/settings` n'en prend aucun : une écriture concurrente est
  détectée par la révision calculée (relue sous le verrou), pas empêchée.
- Le crochet `after_settings_write` est branché depuis la Slice 07 (`ControlCenter._after_brain_settings_write`) :
  un changement de modèle de Core vaut au prochain lancement du CLI cerveau (`_apply_agent_settings`), un changement
  de CLI arrête l'ancien et démarre le nouveau (`_switch_agent`), comme `POST /api/settings`. Les instructions de Core
  (voie des prompts) n'appellent pas le crochet : elles valent au prochain démarrage (`core_restart`).
- `applies` des instructions vocales est déclaré `voice_restart` par prudence (relecture au démarrage de Voice).
- Une trace réelle d'un CLI cerveau en `never` (outil absent, refus du hook) reste à faire en bac à sable
  (Slice 08) ; la Slice 02 la prouve par l'argv simulé et par le hook exécuté hors ligne.
