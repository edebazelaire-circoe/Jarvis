# Slice 03 — Preuves (reprise de Session, Context actif, hydratation de l'agent)

Date : 2026-10-01. Branche `task/jarvis-session-context-recording-runtime`, worktree `bsc`.
Artefacts bruts (non versionnés) : `<s3>` = dossier de travail de la session de l'implémenteur
(`scratchpad/s3/`) — `rt.py` (pilote), `out/summary.json`, `runtime/trace.jsonl`, `tr.py`.

## 1. Instance isolée

- Core `python -m jarvis core` (127.77.0.1:18753) et Control Center `python -m jarvis control-center`
  (127.0.0.1:18754), lancés depuis `bsc`.
- `JARVIS_DATA_ROOT=<s3>/data`, `JARVIS_RUNTIME_DIR=<s3>/runtime`, effacés avant chaque phase.
- Jamais les ports 17653/17654, jamais la base réelle.
- Chaque processus est lancé et arrêté par le pilote (`taskkill /T /F` : arrêt brutal, arbre compris).
  - PID phase A : Core 42404, puis Core 35172.
  - PID phase B : Core 16772 et CC 42788, puis Core 23096 et CC 2432.
- Après le pilote, aucun processus `python` ni `claude` ne porte `scratchpad\s3` ni les ports 18753/18754 dans sa ligne de commande (vérifié par `Get-CimInstance Win32_Process`).

## 2. Phase A — Core seul : arrêt brutal, puis redémarrage

| Lecture `GET /v1/sessions/current` | `jarvis_session_id` | `conversation_id` | Context actif |
| --- | --- | --- | --- |
| 1er démarrage | `jsess_fbf0cc7d…` | `1dab5de9…` | `jctx_9e9e4dc4…` |
| après arrêt brutal et redémarrage | `jsess_fbf0cc7d…` | `1dab5de9…` | `jctx_9e9e4dc4…` |

Trace :

- 1er démarrage : `core.session.opened` (`origin: core_start`, `context_id`), puis `core.context.workspace_ready` (`created: true`).
- Après le redémarrage : `core.session.resumed` (`reconciled_bindings: 0`, `has_agent_session_id: false`). Aucun `core.session.closed`, aucune nouvelle conversation.
- Table `session_contexts` : une seule ligne, `active` / `created`. Le dossier existe.

Sans Control Center, `POST /v1/sessions/new` répond 502 `board_activation_failed` et rien n'est écrit. C'est le comportement existant : Core a un hôte, et il est injoignable. La nouvelle Session est donc prouvée en phase B.

## 3. Phase B — Core, Control Center et vrai `claude`

### 3.1 Premier démarrage (`trace.jsonl`)

| t (UTC) | Événement |
| --- | --- |
| 12:12:56.216 | `core.session.opened` (core_start, `jctx_3bf7bce4…`), puis `core.context.workspace_ready` |
| 12:12:58.284 | `agent.start` : CLI de démarrage du CC, `add_dirs: []` (Core encore inconnu) |
| 12:12:58.292 | `agent.workspace_root_learned` (`source: sessions_current`) |
| 12:12:58.293 | `board_brain.adopted` (`resumable: false`) |
| 12:12:58.332 | `agent.start` pid 4388, `add_dirs: ["<s3>\\data\\sessions"]` (relance avant tout tour) |
| 12:13:02.338 | `board_brain.relaunched` (`reason: session_resume`) |
| 12:13:02.785 | `core.board.host_aligned` |

### 3.2 Un tour réel — voie canonique de Core

- Requête : `POST /v1/conversations/{conv}/brain-turns`, puis BrainOrchestrator, puis `/api/agent/ask`, puis CLI.
- Demande : « Note dans ton espace de travail du Context actif, dans un fichier notes.md, la phrase : « essai Slice 03 : reprise de session ». Puis réponds en une seule phrase courte. »
- Accusé : 202.

Le brief réellement reçu par le CLI est le message utilisateur de la session Claude `ef17fd25-367b-4a88-b02d-371ce996cdee` (`~/.claude/projects/C--Projects-jarvis-bsc/…jsonl`), en extrait :

```text
[Contexte Jarvis — lis-le avant de répondre]
Adressage : direct. La demande t'est adressée.
Board : « Board principal ». C'est ton espace de travail pour ce tour : …
[Contexte actif]
Session : jsess_f4ca232e8d674c57bda11761a22690bc — Context : jctx_3bf7bce4477e4d8a84eb1be9adb757c3.
Dossier de travail : <s3>\data\sessions\jsess_f4ca232e…\contexts\jctx_3bf7bce4…
C'est ton seul espace de travail implicite ; ne modifie pas les Contexts dormants sauf demande explicite.
Tiens-y `summary.md` (court) : il t'est relu à chaque tour et après un redémarrage.
…
[Demande]
Note dans ton espace de travail du Context actif, …
```

Appels d'outils, dans l'ordre : un seul.

```text
Bash: cd "<s3>/data/sessions/jsess_f4ca232e…/contexts/jctx_3bf7bce4…" && echo "essai Slice 03 : reprise de session" >> notes.md && cat notes.md
```

- Réponse : « C'est noté dans ton espace de travail. »
- Résultat CLI : 2 tours modèle, environ 32 s, **0,2273 $**.
- Effet sur disque : le seul fichier créé sous `sessions/` est `sessions/jsess_f4ca232e…/contexts/jctx_3bf7bce4…/notes.md`, qui contient « essai Slice 03 : reprise de session ». Le diff de l'arborescence est fait avant et après le tour.
- Après le tour, la liaison porte `agent_cli: claude` et `agent_session_id: ef17fd25…` (rapportés à Core).

### 3.3 Redémarrage complet (Core et CC), puis nouvelle Session

| t (UTC) | Événement |
| --- | --- |
| 12:13:47.438 | `core.session.resumed` : même conversation `496a0e99…`, `has_agent_session_id: true` |
| 12:13:49.612 | `core.board.host_align_deferred` (warning, existant) : le CC n'écoute pas encore, il se réaligne lui-même |
| 12:13:49.734 | `agent.start` : CLI de démarrage, `add_dirs: []` |
| 12:13:49.751 | `board_brain.adopted` (`resumable: true`) |
| 12:13:49.934 | `agent.start` pid 42772, **`resumed: true`**, `add_dirs: ["<s3>\\data\\sessions"]` |
| 12:13:53.957 | `board_brain.relaunched` (`agent_session_id: ef17fd25…`) : même fil Claude repris |
| 12:13:57.901 | `POST /v1/sessions/new` : CLI neuf pour la liaison neuve, `add_dirs` déjà présent (aucune relance) |
| 12:14:02.131 | `core.context.created` (`origin: new_session`, `dormanted: [jctx_3bf7bce4…]`) |
| 12:14:02.204 | `core.context.workspace_ready` |
| 12:14:02.205 | `core.session.closed` (`new_session`) |
| 12:14:02.206 | `core.session.opened` |

Résultats :

- `GET /v1/sessions/current` après le redémarrage : `jsess_f4ca232e…`, conversation `496a0e99…`, `jctx_3bf7bce4…` (identiques).
- Après `POST /v1/sessions/new` (201) : `jsess_5f77c4f6…`, conversation `59ef5c8d…`, `jctx_683d4aaa…`.
- `session_contexts` contient deux lignes :
  - `(jsess_f4ca…, jctx_3bf7…, dormant, created)` ;
  - `(jsess_5f77…, jctx_683d…, active, created)`.

La trace ne contient aucune ligne `error`. Une seule ligne est illisible : écriture concurrente de trois processus dans `trace.jsonl` (`RuntimeJournal`, défaut préexistant, ce n'est pas un écrit de cette Slice).

**Coût total : 0,2273 $** (1 tour réel, sur un plafond de 3).

## 4. Tests

| Commande | Résultat |
| --- | --- |
| `test_session_manager.py`, `test_workspace_board_contract.py`, `test_v2_architecture.py`, `test_session_context.py`, `test_session_context_store.py`, `test_session_context_service.py` (nouveau) | verts (1 ignoré : lien symbolique sans privilège) |
| `test_board_*.py` et `test_boards_*.py` (tous) | 256 verts |
| `test_voice_session_binding.py`, `test_voice_board_rebind.py`, `test_session_protocol.py`, `test_codex_agent.py`, `test_claude_tools_gateway_args.py`, `test_control_center_prompts.py`, `test_prompt_*`, `test_schema_migrations.py`, `test_board_store_sqlite.py` | 178 verts, puis 20 (`test_session_protocol` avec la route `context`) |
| Fichiers qui touchent `ClaudeLocalAgent`, `build_agent_brief`, `_turn_context`, `/sessions/current` ou `core_restart` (34 fichiers, en deux tranches) | 1 435 verts, 1 échec connu (`test_brain_delegation.py`, non imputable) |
| Fichiers qui touchent `JarvisCoreApplication`, `BrainOrchestrator` ou `control_center_brain` (35 autres) | 1 027 verts |
| `test_session_context_hydration.py` (nouveau) | 14 verts |
| `tests/integration/test_board_session_e2e.py` | 7 verts |
| `test_conversation_event_timeline`, `test_mcp_plugin_restart`, `test_scene_restart_protocol`, `test_v2_core_recovery` | 13 verts |
