# Implementation log

Implementation agents append durable execution notes here. Do not use this file as a substitute for Slice evidence, QA reports, repository history, or canonical runtime traces.

## 2026-10-01 — Slice 00 (agent 0)

- `main` avancé en avance rapide jusqu'à `11fcdc2` (fin de `task/jarvis-generic-mcp-plugin-runtime`), sur instruction du Human. Branche créée depuis `main`. S0 `91de79a` : miroir Drive, 48 fichiers, JSON valides.
- Le checkout principal repasse sur `main`, car le Jarvis habituel du Human en tourne. Le travail se fait dans le worktree `C:/Projects/jarvis/bsc`.
- Audit à l'aveugle (trois agents Explore), puis réconciliation : `slices/00-project-manager/READINESS.md`. Décisions D-TT, D-SESS, D-CTX, D-ART, D-CAP, D-AUDIO, D-SCREEN, D-MCP, D-UI. Schéma : v5 (contexts), v6 (artefacts et activité), v7 (captures).
- Task Types : gate levé et consigné dans chaque `metadata.json`.

## 2026-10-01 — Slice 01 (implémenteur)

- Livré : `jarvis/domain/session_context.py` (`SessionContext`, `jctx_…`, statut `active|dormant`, origine `created|adopted`, sources de relais ≤ 8, métadonnées bornées, codecs stricts, `SessionContextError` : `invalid_context` 400, `context_not_found` 404, `context_conflict` / `context_dormant` / `session_closed` 409). Transitions pures : `create_context`, `activate_context`, `adopt_context`, `touch_context`, `ensure_active`, `dormant_contexts_of_closed_session`, `check_contexts` ; résultat `ContextTransition` (`changed` à écrire en une transaction). Chemin dérivé `context_workspace_path` → `sessions/<jsess>/contexts/<jctx>`, ids validés comme segments sûrs. Aucune clé `board_id`.
- Cycle de vie : `close_session` / `close_session_with_bindings` n'acceptent plus que `new_session` (`invalid_session` sinon). `CORE_RESTART` reste décodable, l'historique n'est pas réécrit.
- Décision (chemin legacy) : fonction nommée `legacy_close_on_core_restart`, seul appelant `SessionManager._open_at_start`. Le démarrage est inchangé. Un test fige la liste des appelants. Fiche `docs/legacy/core-restart-session-close.md`, retrait en Slice 03. Choix préféré à un paramètre, qui aurait laissé n'importe quel appelant produire `core_restart`.
- Décision (owner, D-CTX) : `SessionManager` appliquera les transitions de Context sous son verrou, dans la même transaction que la Session (Slice 03). Fermer une Session endort son Context actif (`dormant_contexts_of_closed_session`).
- Docs : nouveau `docs/session-context.md` (Level 2), `docs/boards.md` (Lifecycle, Session, démarrage).
- Tests : `test_session_context.py` 82, `test_workspace_board_contract.py` 69, `test_session_manager.py` 14, `test_session_protocol.py` 19, `test_v2_architecture.py` 8, `test_board_store_sqlite.py` 17, `test_voice_session_binding.py` 10, `test_voice_board_rebind.py` 6, `test_settings_mcp.py` 63, et les 19 fichiers `test_board*.py` / `test_boards*.py` : tous verts, 0 échec.
