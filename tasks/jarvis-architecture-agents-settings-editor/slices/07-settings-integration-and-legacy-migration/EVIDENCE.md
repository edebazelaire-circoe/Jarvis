# Slice 07 - preuves (bac à sable, jamais le JARVIS vivant)

Worktree `C:\Projects\jarvis\arch-s07`, branche `task/jarvis-architecture-agents-settings-editor-s07`, 2026-10-23.
Contrat de la page : `docs/settings/architecture-agents.md`.

## 1. Bac à sable

Script : [`evidence/sandbox_proof.py`](evidence/sandbox_proof.py) (copie du script lancé depuis le scratchpad), sortie
complète : [`evidence/sandbox_proof.log`](evidence/sandbox_proof.log).

- `python -m jarvis control-center` lancé depuis le worktree par le script (`Popen`, PID 32936), variables
  `JARVIS_DATA_ROOT` et `JARVIS_RUNTIME_DIR` sous
  `C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\05b93d8a-1916-4b86-866a-f10f71884561\scratchpad\s07-sandbox\`,
  `JARVIS_CORE_PORT=27653`, `JARVIS_UI_PORT=27654`, `JARVIS_VISUALIZER_ENABLED=0`, toutes les autres variables
  `JARVIS_*` retirées, pas de `.env` dans le worktree. Core n'est pas lancé (pas nécessaire).
- Ports 27653/27654 libres avant le lancement (`netstat`). Arrêt : `terminate()` sur ce PID seul (pas d'arbre, pas de
  `/T`) ; aucun processus du JARVIS vivant touché.
- Réglages initiaux : architecture vocale Duplex (`gpt-live-1`), comme le poste de l'utilisateur d'après l'audit S00.

Commande : `C:\Projects\jarvis\jarvis\.venv\Scripts\python.exe -I <scratchpad>\s07_sandbox.py`

### (a) Graphe réel, une liaison basculable réelle, un refus verrouillé

```
(a) GET /api/architecture -> 200 ; voix duplex ; nœuds ['mic', 'voice', 'core', 'tool_brain', 'subagents', 'speakers']
(a) liaison voice.delegate->core.request : enabled=True mutability=toggleable binding=voice_architecture.config.brain_orchestration applies=voice_restart
(a) POST coupure -> 200 ok=True changed=True ; réglage persisté brain_orchestration=False ; lu par le runtime (load_voice_architecture) brain_orchestration=False ; demande de bascule Voice écrite=True
(a) POST liaison verrouillée mic->voice -> 423 code=connection_locked raison=« La surface vocale ne fonctionne pas sans micro. »
(a) POST révision périmée -> 409 code=architecture_revision_stale
(a) POST remise -> 200 changed=True ; brain_orchestration=True
```

La coupure écrit le réglage que Voice relit à son démarrage (`load_voice_architecture`, le lecteur du runtime) et
dépose la demande de bascule `.voice_switch_request` par la règle commune `plan_voice_switch` (journal
`voice.switch.requested` ×2 : coupure et remise).

### (b) Cerveau Core : délégation `never` puis `standard`, graphe cohérent

```
(b) GET /api/brains/core/config -> 200 ; provider=claude model=(défaut) delegation=standard catalog=ok ; choix de modèle servis=1
(b) PATCH delegation=never -> 200 changed=True applies=core_restart ; brain-config.json core=never ; graphe spawn enabled=False mutability=governed governed_by={'kind': 'brain_config', 'node': 'core', 'field': 'delegation'}
(b) PATCH delegation=standard -> 200 ; graphe spawn enabled=True
(b) PATCH révision périmée -> 409 code=brain_config_revision_stale
```

`catalog=ok` : le fournisseur réel du Control Center (`_catalog_view_dict`, le calcul de `GET /api/catalog`) a répondu ;
sans clé Anthropic dans le bac à sable, seul le choix « défaut du CLI » est servi.

### (c) Politique d'un rôle, puis décision du hook hors ligne

```
(c) GET /api/subagent-role-routing -> 200 ; révision rr-0 ; qa provenance=inherited:general ; harnesses servis=['claude', 'codex']
(c) PUT /api/subagent-role-routing/qa -> 200 ok=True code=None ; provenance=explicit candidats=[('claude', 'claude-haiku-4-5', False)]
(c) routing-hook -> code 0 ; sortie : {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", ...
(c) trace agent.routing.decided : level=warning role_id=qa provenance=explicit reason=role_passthrough message=« Sous-agent « Relire le diff de la Slice 07 » : profil general, rôle qa (explicit), aucun candidat du rôle utilisable : le CLI garde la main (Dupliqué) »
```

Hook lancé hors ligne : `python -m jarvis routing-hook --runtime-root <sandbox>\runtime`, événement `PreToolUse` réaliste
(`tool_name: Agent`, description `[general] [qa] Relire le diff de la Slice 07`, `subagent_type: general-purpose`).
La décision porte `role_id=qa` et `provenance=explicit`. Le candidat est indisponible (aucun catalogue de modèles en
cache dans le bac à sable, aucune clé) : le hook laisse passer en Dupliqué (`role_passthrough`, niveau `warning`),
comportement documenté au § 10 de `docs/subagent-roles.md`. Une sélection effective d'un candidat disponible n'est pas
prouvée ici (Slice 08, avec un catalogue réel).

Journal du Control Center et du hook (`trace.jsonl`) : `architecture.connection.updated`×2,
`architecture.write.refused`×2, `brain_config.read`×1, `brain_config.saved`×2, `brain_config.rejected`×1,
`subagent_role_routing.read`×1, `subagent_role_routing.saved`×1, `voice.switch.requested`×2, `agent.routing.decided`×1,
`agent.role_applied`×1.

### (d) La page dans un Chrome sans tête

Harnais `tests/unit/_wake_word_settings_browser.mjs` (garde `assertSafeTarget` de `_cdp_profile.mjs` contre les ports et
le dossier d'exécution du JARVIS vivant), contre `http://127.0.0.1:27654/`, 1440 × 900 :

```
(d) attentes tenues : 9/9
(d) tabs = ['Architecture', 'Sous-agents']
(d) nodes = ['mic', 'voice', 'core', 'tool_brain', 'subagents', 'speakers']
(d) after_escape = [True, 'architecture']        # Échap ferme la fenêtre du cerveau, pas les Réglages
(d) subagents = ['subagents', 7, True]            # sept rôles, bloc « Modèles du rôle » servi
(d) requêtes : … /api/architecture, /api/architecture/layout, /api/brains/core/config, /api/subagent-role-routing, /api/subagent-roles …
(d) erreurs console : []
```

Captures (`C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\05b93d8a-1916-4b86-866a-f10f71884561\scratchpad\s07-shots\`) :
`sandbox-architecture.png` (canevas), `sandbox-core-window.png` (fenêtre ouverte depuis le menu « … › Configurer… »),
`sandbox-subagents.png` (onglet Sous-agents, `qa` réglé explicitement). Captures du test navigateur (Control Center
isolé de pytest) dans le même dossier : `architecture-canvas.png`, `architecture-core-window.png`,
`architecture-after-never.png`, `subagents-tab.png`.

## 2. Tests lancés (ciblés, en avant-plan, par petits lots)

Interpréteur : `C:\Projects\jarvis\jarvis\.venv\Scripts\python.exe -m pytest`.

| Lot | Résultat |
| --- | --- |
| `test_architecture_settings_mount.py` (nouveau) | 7 passed |
| `test_architecture_graph.py`, `test_brain_config.py`, `test_control_center_voice_architecture.py`, `test_control_center_voice_architecture_review.py`, `test_interaction_mode_control_plane.py`, `test_subagent_role_routing.py` | 193 passed |
| `test_voice_switch.py`, `test_control_center_mvp.py`, `test_routing_settings_screen.py`, `test_agent_cli_settings_ui.py` | 68 passed (avant migration des tests front) |
| `test_control_center_mvp.py`, `test_agent_cli_settings_ui.py`, `test_control_center_settings_registry_js.py`, `integration/test_settings_redesign_migration.py`, `test_voice_settings_ui.py`, `test_control_center_voice_architecture.py` | 91 passed |
| `test_control_center_subagents_settings_js.py`, `test_subagent_role_routing_ui_js.py`, `test_brain_config_panel_js.py`, `test_control_center_architecture_settings_js.py`, `test_control_center_settings_shell_js.py`, `test_voice_settings_surface.py` | 109 passed |
| navigateur : `test_architecture_agents_settings_browser.py` (nouveau contrat, 7 tests) | 7 passed |
| navigateur : `test_architecture_settings_browser.py`, `test_subagent_settings_browser.py` | 17 passed (lot de 25 avec la fenêtre) |
| navigateur : `test_brain_config_panel_browser.py` | 8 passed (après mise à jour du placement) |
| navigateur : `test_interface_settings_browser.py` | 14 passed |
| navigateur : `test_settings_accessibility_browser.py` | 17 passed (13 + 4 relancés après correction) |
| navigateur : `test_settings_shell_browser.py` | 9 passed |
| navigateur : `test_connections_settings_browser.py -k category_cards`, `test_status_centre_browser.py -k settings_hub` | 1 + 1 passed |
| `test_architecture_graph.py -k resolve_mode` (I-001 S01-5) | 1 passed |

Quatre tests navigateur étaient déjà en retard sur `main` (`ad1e7f4d`, hub du 2026-10-23 : « Plugins MCP » précède
« Fournisseurs » dans `connections`) : `test_category_cards_alias_environment_fallback_and_links`,
`test_changing_category_from_the_content_keeps_the_focus_in_the_shell`, `test_connections_live_regions_are_stable_nodes`,
`test_a_connections_error_stays_at_the_top_while_scrolling` ; corrigés au passage (ils visent `providers`). La suite
complète reste à la Slice 08.
