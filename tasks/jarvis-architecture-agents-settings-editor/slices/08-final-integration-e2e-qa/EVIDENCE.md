# Slice 08 - preuves (suite complète, bac à sable, vrai CLI ; jamais le JARVIS vivant)

Worktree `C:\Projects\jarvis\arch-s08`, branche `task/jarvis-architecture-agents-settings-editor-s08`, 2026-10-23/24.
Interpréteur : `C:\Projects\jarvis\jarvis\.venv\Scripts\python.exe`, lancé depuis le worktree, variables `JARVIS_*`
héritées retirées. Base de comparaison : `main` = `ad1e7f4d` (aucune dérive de `main` local pendant la Slice), extraite
en worktree détaché **en lecture** dans le scratchpad (`base-ad1e`) pour relancer les échecs et le Control Center de
`main` ; aucune bascule de branche du worktree de travail.

Tous les scripts et journaux sont dans [`evidence/`](evidence/). `<scratchpad>` =
`C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\05b93d8a-1916-4b86-866a-f10f71884561\scratchpad`.

## 1. Suite complète, une fois, par lots

Détail lot par lot : [`evidence/suite-lots.txt`](evidence/suite-lots.txt) ; échecs du premier passage :
[`evidence/suite-failures-first-run.txt`](evidence/suite-failures-first-run.txt).

| Lot | Contenu | Résultat | Durée |
| --- | --- | --- | --- |
| u01-u13 | `tests/unit/test_*.py` hors navigateur (841 fichiers, 13 lots de 35 à 100 fichiers) | **22 672 passed, 16 failed, 68 skipped** | 5 225 s |
| b01-b22 | `tests/unit/test_*browser*.py` (68 fichiers, 733 tests, lots par rang de test ; 6 lots coupés au délai de 570 s puis repris au test suivant, rien n'est sauté) | **662 passed, 9 failed, 62 skipped** | ≈ 8 900 s |
| i01-i02 | `tests/integration` (81 fichiers) | **678 passed, 27 skipped** | 777 s |
| e2e | `tests/e2e` | **1 passed** | 3 s |

### Attribution des 25 échecs du premier passage

Chaque échec a été relancé sur `main` (`ad1e7f4d`, worktree de base) : 21 y échouent à l'identique, 4 viennent de
cette tâche et sont corrigés.

| Échec | Sur `main` | Attribution | Sort |
| --- | --- | --- | --- |
| `test_barehands_palette_js::…puts_the_tools_on_the_palette…`, `test_barehands_tools_settings_js::…serves_configuration_only…` | passent | **S05** : le module de la fenêtre du cerveau, inséré dans la page, dessine des `role="radiogroup"` que ces absences Bare Hands interdisaient partout | **corrigé** `317b0f56` (absence vérifiée hors du module), 63 passed |
| `test_control_center_shell_layers::test_every_rank_in_css_matches_the_registry` | passe | **S04/S05** : z-index du canevas (`.arch-*` 2-5) et de la fenêtre (`.bcp-layer` 60) absents du registre | **corrigé** `d9a3034f` (rangs contenus dans `.overlay`), 12 passed |
| `test_settings_message_destinations_browser::…named_in_messages_exists` | échoue (16 destinations) | 16 destinations périmées par le hub du 2026-10-23 (`ad1e7f4d`, hors tâche) ; **une 17ᵉ venait de S02** (`routing_hook.DELEGATION_NEVER_REASON`, catégorie coupée en fin de ligne) | la nôtre **corrigée** `ecd681dd` (liste relevée : 17 → 16, identique à `main` hors celle de `settings_mcp.py` que S07 avait déjà réparée) ; le test reste rouge pour les 16 préexistantes |
| `test_app::…tools_gateway_target…` | échoue | préexistant (`SimpleNamespace` sans `data_root`) | hors tâche |
| `test_barehands_interaction_js` ×2 | échouent | préexistant (géométrie du cadre d'exercice) | hors tâche |
| `test_brain_capability_parity::…documented_in_the_brain_prompt` | échoue | préexistant connu (`ui_intent_publish`) | hors tâche |
| `test_control_center_mcp_api` ×6 | échouent | préexistant (21 natifs servis au lieu de 20) | hors tâche |
| `test_memory_context::test_recall_over_2000_notes…` | échoue | préexistant / sensible à la charge (passe seul sur la branche) | hors tâche |
| `test_scene_group_drag_js::…group_drag…`, `test_tool_brain_choices::…single_metadata_copy` | échouent | préexistants | hors tâche |
| `test_connections_settings_browser` ×3 (`add_bind_replace…`, `late_response…[section]`, `[close]`) | échouent | préexistants (hub du 2026-10-23 : `.conn-add>summary` introuvable) | hors tâche |
| `test_control_center_shell_browser::test_one_geometry_and_one_rank_set_for_both_themes` ×4, `::test_reduced_motion` | échouent | préexistants (rang de `#boardsPanel` 58 au lieu de 39, sélecteur de Board du 2026-10-19) | hors tâche |

`test_brain_delegation` (échec connu sur `main` d'après la mémoire projet) **passe** sur la branche.

### Relances ciblées après les corrections de cette Slice

| Lot | Résultat |
| --- | --- |
| `test_routing_hook`, `test_routing_hook_orchestration`, `test_brain_config_delegation` (après `ecd681dd`) | 84 passed |
| `test_architecture_settings_mount`, `test_control_center_mvp`, `test_agent_cli_settings_ui` (après `S8: fix (S07)` bascules sérialisées) | 46 passed |
| `test_brain_config_panel_js` (I-002 point 2) | 24 passed |
| `test_architecture_agents_settings_browser`, `test_brain_config_panel_browser`, `test_control_center_shell_layers` | 28 passed |
| `test_back_brain_delegation`, `test_architecture_graph`, `test_unified_interruption`, `test_back_brain_tasks` (I-001 S01-3, S01-4) | 13 + 89 passed |
| fichiers qui touchent `RealtimeFrontendSession` / preuves de prompt (12 fichiers) | 255 passed, 1 failed (`test_app`, préexistant) |
| tout fichier qui cite `routing_hook` (24 fichiers, unit + integration) après la traduction en famille | 664 passed |
| `test_brain_config`, `test_brain_config_delegation`, `test_architecture_settings_mount` (CLI détecté légal) | 65 passed |
| `test_settings_shell_browser` + `test_control_center_settings_shell_js` ; `test_settings_accessibility_browser` (après le correctif Échap) | 13 passed ; 17 passed |
| `test_brain_config_panel_browser`, `test_subagent_settings_browser`, `test_architecture_settings_browser` | 25 passed |
| réglages hors navigateur (10 fichiers `test_control_center_*settings*`, `test_routing_settings_screen`, `test_settings_endpoints`…) + `integration/test_settings_redesign_migration` | 242 passed |
| navigateur Échap / raccourcis : `test_global_launcher_browser`, `test_jarvis_wheel_browser`, `test_tool_wheel_browser`, `test_interface_settings_browser`, `test_status_centre_browser` | 6 + 4 + 13 + 14 + 30 passed |

Trois tests ajoutés échouent sans leur correctif (mutation vérifiée) : `syncCoreCliDraft` retiré → le test de I-002
point 1 échoue ; garde `defaultPrevented` de `ui_close` retirée → le test Échap du menu échoue ; ancienne bascule
non sérialisée → le test des deux PATCH rapprochés échoue (raisonnement consigné dans le test, `log == []`).

## 2. Scénarios runtime en bac à sable (`docs/04-testing-and-quality.md`, les 12)

Script : [`evidence/sandbox_proof_s08.py`](evidence/sandbox_proof_s08.py) (phases `prep`, `graph`, `brain1`, `brain2`,
`roles`, `browser`, `migrate`) ; sortie intégrale : [`evidence/sandbox_evidence.log`](evidence/sandbox_evidence.log).

- `python -m jarvis control-center` lancé depuis le worktree par le script (`Popen`), `JARVIS_DATA_ROOT` et
  `JARVIS_RUNTIME_DIR` sous `<scratchpad>\s08-sandbox\`, `JARVIS_CORE_PORT=27653`, `JARVIS_UI_PORT=27654`,
  `JARVIS_VISUALIZER_ENABLED=0`, toutes les autres variables `JARVIS_*` retirées ; ports vérifiés libres avant chaque
  lancement. Arrêt : `POST /api/agent/kill` (le CLI cerveau que **ce** Control Center a lancé), puis `terminate()` sur
  le PID lancé, sans arbre ni `/T`. Core n'est pas lancé. Le JARVIS vivant (17653/17654, checkout principal) n'a
  jamais été touché.
- Réglages initiaux : un **ancien** `control-center-settings.json` (forme de `main` : `agent_cli`,
  `agent_cli_settings`, `agent_routing` en Dupliqué, `agent_behavior`, `agenda_reminders`, architecture vocale Duplex
  `gpt-live-1`), copié en `settings-before.json`.
- **Fixture de catalogue** (pour la sélection effective par rôle) : `model-catalog.json` avec deux modèles anthropic
  (`claude-haiku-4-5`, `claude-sonnet-4-5`) et l'empreinte d'une **clé fictive** (`sk-ant-s08-fixture-not-a-real-key`,
  posée dans les réglages du bac à sable, jamais envoyée à un fournisseur : le catalogue frais se lit sans réseau ;
  le CLI `claude` n'en hérite pas, il garde le compte de l'utilisateur).
- Le CLI cerveau est le **vrai** `claude` 2.1.309 (`~\.local\bin\claude.exe`), lancé par le Control Center du bac à
  sable avec son hook de routage ; ce que le processus a reçu est lu dans sa ligne de commande Windows
  (`Win32_Process.CommandLine`) et dans `trace.jsonl`.

| # | Scénario | Preuve machine | Verdict |
| --- | --- | --- | --- |
| 1 | Le snapshot correspond aux nœuds réels | `GET /api/architecture` → duplex, nœuds `mic, voice, core, tool_brain, subagents, speakers` = composition runtime `DuplexVoiceConfig` ; états vivants (Core `unavailable` : non lancé ; sous-agents `active`) | OK |
| 2 | Liaison basculable coupée → chemin runtime réellement abandonné | `voice.delegate->core.request` coupée (200) : `LiveDelegationController` construit depuis les réglages relus par `load_voice_architecture` passe de `brain_turn` à `speculative` ; demande de bascule de Voice déposée. `core.events->tool_brain.wake` : `tool_brain_wiring.resolve_mode` (lecture du démarrage de Core) `off → shadow` | OK |
| 3 | Remise → comportement rétabli | remise 200 → `brain_turn` ; Tool Brain `shadow → off` ; journal `architecture.connection.updated`×4, `voice.switch.requested`×2 | OK |
| 4 | Verrouillée refusée, runtime intact | `mic->voice` → **423** `connection_locked` « La surface vocale ne fonctionne pas sans micro. », fichier de réglages octet-identique, révision inchangée ; gouvernée `core->subagents` → 422 `connection_governed` ; révision périmée → 409 | OK |
| 5 | Création invalide refusée, rien de stocké | `POST /api/architecture/connections` (sens inversé ; canaux speech→event) → 422 `connection_incompatible`, nombre de liaisons et fichier inchangés | OK |
| 6 | Modèle / CLI de Core persistés et effectifs | `PATCH model=claude-haiku-4-5` → `agent_cli_settings.claude.model` ; CLI relancé : `--model claude-haiku-4-5` dans sa ligne de commande, `agent.start model=claude-haiku-4-5`, **l'init du CLI annonce `claude-haiku-4-5`**. Bascule réelle `provider=codex` puis `claude` : `agent.stop → agent.switch codex → agent.start`, puis retour (après le correctif S02 ci-dessous) | OK |
| 7 | `never` empêche la délégation | (a) au lancement : ligne de commande `--disallowedTools Agent Task`, `brain-delegation-launched.json {delegation: never, pid}`, `agent.start spawn_tools_removed=true`, **init du CLI sans `Agent` ni `Task`** ; demandé de lancer un sous-agent, le cerveau répond « L'outil Agent n'existe pas dans ma liste d'outils disponibles », aucun appel. (b) à chaud : CLI lancé en `standard` (init avec `Task`), `never` posé, vrai appel `Agent` → `agent.spawn_refused code=brain_delegation_never tool_use_id=toolu_01FSHM…`, réponse « L'outil Agent est refusé car la délégation est désactivée… » | OK |
| 8 | Niveau supérieur : délègue, toujours sous la politique globale des rôles | `proactive` / `exploratory` : consigne lancée ≠ standard, **une seule phrase remplacée** ([`evidence/prompt-diffs.txt`](evidence/prompt-diffs.txt)). En `proactive`, vrai appel `[general] [qa]` routé par la politique du rôle (ligne 9) ; « Le sous-agent a répondu : 4 » | OK |
| — | `standard` octet-identique | consigne du lancement réel `standard` (23 500 car.) = rendu par `main` `ad1e7f4d` sans variable (même programme `backend.claude.conversation.tools_barehands_session`, même modèle, même contexte global) : SHA-256 `1c79ca51…5212c` identiques ([`evidence/prompt_compare.py`](evidence/prompt_compare.py)) | OK |
| 9 | La politique d'un rôle change la sélection de CE rôle seulement | `PUT qa=[claude/claude-sonnet-4-5]` → seul `qa` change dans la vue des 7 rôles ; hook hors ligne : `[qa]` `preferred claude-sonnet-4-5` (`agent_model: sonnet`), `[coder]` inchangé avant/après. **Vrai CLI** (cerveau sur haiku) : `agent.routing.decided role_id=qa provenance=explicit reason=preferred model=claude-sonnet-4-5 agent_model=sonnet`, `agent.role_applied qa`, sous-agent `jarvis-no-spawn` terminé avec **`resolvedModel: claude-sonnet-5-5`** (≠ cerveau `claude-haiku-4-5-20251001`). Révision périmée → 409 | OK après correctif (voir 3.) |
| 10 | Candidat indisponible visible avec sa raison | `PUT research=[claude-retired-9, claude-sonnet-4-5]` → `claude-retired-9` `available=false` « Ce modèle n'est plus proposé par le fournisseur. » ; `DELETE` → `inherited:general` | OK |
| 11 | Révision / conflit des instructions de rôle | couvert par la suite (`test_subagent_settings_browser`, `test_subagent_role_routing*`, `test_brain_config_panel_js::…instructions_conflict…`), tous verts | OK (tests) |
| 12 | Pas d'onglet Brains, ni personnalité, ni CLI technique | vrai Chrome contre le bac à sable (`TOUR` du test de S07) : onglets `['Architecture', 'Sous-agents']`, sélecteurs et libellés interdits `[]` sur les deux onglets ; « Brains », « Agent principal » absents ; commande/permission/mode/profils/inventaire présents dans Avancé › Runtime & CLI | OK |

### Migration et liens profonds

- **A/B `main` contre S08** ([`evidence/migrate_ab.py`](evidence/migrate_ab.py)) : même ancien fichier, même geste (Réglages
  ouverts, Comportement : verbosité changée, « Enregistrer »), Control Center de `main` puis de la branche. Fichiers
  obtenus **identiques** hormis l'identifiant aléatoire et l'horodatage de la clé reprise (`credentials`,
  `credential_bindings`) ; aucune clé de l'ancien fichier perdue par S08 ([`evidence/migrate-ab-result.json`](evidence/migrate-ab-result.json)).
- Ancien fichier relu par S08 : CLI `claude`, modèle défaut, délégation `standard` (store `bc-0`, aucun
  `brain-config.json` écrit), rôles `inherited:*`, révision `rr-0` ; ni `brain-config.json` ni
  `subagent-role-routing.json` écrits par l'ouverture ni par l'enregistrement à pied.
- Après toutes les phases : aucune clé perdue ; une valeur volontairement changée (modèle de Core) ; clés ajoutées par
  les écritures du graphe (`tool_brain.mode`, et `voice_architecture.config` normalisé : `brain_orchestration`,
  `client_delegation`, `idle_timeout_s`, `barge_in_decider` écrits avec leurs valeurs par défaut — voir incertitudes).
- Liens profonds en vrai Chrome : `main_agent` → `agents_models/architecture`, `subagent_models` →
  `agents_models/subagents`, `memory` → `memory_knowledge/recall` ; `cli` et `routing` ne sont plus des alias.

### Clavier, focus, menus, sept rôles (vrai Chrome, bac à sable, 1440 × 900)

14/14 attentes tenues, console vide : focus sur le nœud Core → Maj+F10 ouvre son menu, focus sur « Configurer… » ;
Échap ferme le menu, focus rendu au nœud, Réglages ouverts (**après correctif**, voir 3.) ; Maj+F10 puis Entrée ouvre la
fenêtre du cerveau, qui ne couvre pas le nœud (`overlap 0`), reste dans l'écran et dans l'overlay, 5 niveaux de
délégation ; Tab ×4 puis Maj+Tab : le focus reste dans la fenêtre ; Échap ferme la fenêtre, focus rendu au nœud, page
toujours ouverte ; clic droit (événement `contextmenu`) sur Tool Brain ouvre son menu. Onglet Sous-agents : les rôles
du DOM = `GET /api/subagent-roles` = `GET /api/subagent-role-routing`, dans l'ordre du registre
(`interviewer, research, web-research, coder, concept, research-lead, qa`).

### Comparaison visuelle avec les deux références

Captures : [`evidence/s08-architecture.png`](evidence/s08-architecture.png), [`evidence/s08-core-window.png`](evidence/s08-core-window.png),
[`evidence/s08-subagents.png`](evidence/s08-subagents.png) (bac à sable, 1440 × 900, thème par défaut).

- **Architecture** (référence `architecture-ui-reference.png`) : même ossature — en-tête « Architecture & Agents »,
  deux onglets, graphe qui occupe la page, cartes de module vitrées avec état et pastilles de ports, liaisons typées et
  étiquetées (audio, requête, parole, appel d'outil, événement), verrous visibles, fenêtre flottante de configuration
  d'un cerveau avec la tendance de délégation en curseur segmenté. Écarts assumés : pas de cartes « État du système »,
  « Règles d'architecture », « Actions rapides », ni journal ni légende (aucune donnée réelle ne les porte, décision de
  ne rien inventer) ; néon bien plus sobre que la maquette (jetons de thème des Réglages) ; la fenêtre s'ouvre contre
  le bord gauche (sur le rail des catégories) pour ne pas couvrir le nœud, là où la maquette la pose sous la Voix.
- **Sous-agents** (référence `subagents-ui-reference.png`) : liste maître-détail des 7 rôles réels au lieu du tableau
  de 5 rôles inventés ; modèles du rôle ordonnés, repli, provenance « Hérité du profil » ; ni onglet Brains, ni
  statistiques fictives (98 %, 12 outils), ni matrice de routage ni règles globales factices. Densité moindre que la
  maquette. La lisibilité et l'impression d'ensemble restent au jugement du Human (HV-ARCH-004/005).

## 3. Défauts trouvés par la campagne et corrigés (machine)

| Commit | Slice | Constat | Correctif |
| --- | --- | --- | --- |
| `bd9bf358` | S03 | **Un rôle réglé sur un modèle ne lançait plus aucun sous-agent** : le hook écrivait `updatedInput.model = "claude-haiku-4-5"`, refusé par le schéma de l'outil `Agent` du vrai CLI (`sonnet\|opus\|haiku\|fable`), « PreToolUse hook … failed schema validation ». Le mécanisme de réécriture date de `0fa690eb` (routage par profil, déjà présent sur `main` en mode Auto), mais cette tâche le rend actif pour toute politique explicite, même en Dupliqué | `routing_hook.agent_tool_model` écrit la famille (`claude-haiku-4-5` → `haiku`) ; la trace porte `model` (catalogue) et `agent_model` (écrit) ; docs `ARCHITECTURE.md`, `subagent-roles.md` § 10 |
| `502e553f` | S07 | **Échap dans le menu d'un nœud (ouvert au clavier) fermait toute la page des Réglages** : le raccourci global `ui_close` (écoute `window`) ignorait la touche déjà consommée par le canevas ([`evidence/escape_menu_repro.py`](evidence/escape_menu_repro.py)) | `ui_close` respecte `defaultPrevented` ; test navigateur ; doc `settings-shell.md` |
| `f2bbe305` | S02 | **Impossible de passer Core à Codex installé**, et le CLI qui tourne affiché « Claude Code — indisponible » : avec la forme réelle du catalogue, le défaut d'un CLI détecté est `configured_unverified`, jamais `selectable` → 422 `brain_config_model_unavailable` ([`evidence/core_cli_choices_check.py`](evidence/core_cli_choices_check.py)) | un CLI détecté et « défaut du CLI » sont des choix légaux (raison « se vérifient qu'à l'usage ») ; bascule réelle codex ↔ claude prouvée ; doc `brain-config.md` |
| `317b0f56`, `d9a3034f`, `ecd681dd` | S05, S04/S05, S02 | tests de la suite (voir § 1) | voir § 1 |

## 4. Points I-002 et reports d'I-001

Sort de chaque point : [`../../Issues/I-002-polish-for-s08.md`](../../Issues/I-002-polish-for-s08.md).

## 5. Incertitudes

- **Famille plutôt que version.** L'outil `Agent` n'accepte qu'une famille : un rôle réglé sur `claude-sonnet-4-5`
  s'exécute sur la version **courante** de la famille sonnet du CLI (constaté : `claude-sonnet-5-5`). La trace le dit
  (`model` / `agent_model` / `resolvedModel`), l'interface ne le dit pas encore ; épingler une version exacte par rôle
  n'est pas possible par ce mécanisme (décision produit si besoin).
- Le bac à sable n'a pas lancé Core ni Voice : l'effet des liaisons vocales est prouvé sur le code qui lit les réglages
  au démarrage de Voice et de Core (mêmes fonctions), pas sur une session vocale réelle ; l'essai réel est un check humain.
- Les écritures du graphe normalisent `voice_architecture.config` (valeurs par défaut écrites dans le fichier) ; aucun
  réglage n'est perdu, mais un défaut futur du code ne s'appliquera plus à ces champs pour ce poste.
- `test_memory_context::test_recall_over_2000_notes…` est sensible à la charge (échoue aussi sur `main`).
