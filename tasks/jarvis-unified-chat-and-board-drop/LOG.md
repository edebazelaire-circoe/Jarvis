# Journal d'exécution

Réservé au Project Manager et aux Work Agents. Aucun progrès, verdict QA ou résultat humain n'a été prérempli lors de la création de cette tâche.

## Reprise (pour une nouvelle session)

- **Où travailler :** worktree de tâche `C:/Projects/jarvis/bucd`, branche `task/jarvis-unified-chat-and-board-drop`, basée sur `origin/main` 664d767b. Le checkout principal `C:/Projects/jarvis/jarvis` (le Jarvis vivant de l'Humain) n'est pas touché.
- **Baseline :** worktree détaché `C:/Projects/jarvis/bucq` à 664d767b.
- **Python :** `C:/Projects/jarvis/sub-agents/jarvis-agent-01/.venv/Scripts/python.exe`, avec `PYTHONPATH=<worktree>`.
- **Repli documenté :** il n'existe ni `docs/workflows/AGENT_TASK_LIFECYCLE.md` ni branche `dev`. On utilise donc les identifiants des files Drive de la mémoire du projet et `main` comme base.
- **Drive :** dossier `1ejymDktJTejJDk52RvqTwr1SQkNdSd9T`, dans `to-do`. Son déplacement vers `current` est demandé à l'Humain, faute d'outil de déplacement.

## 2026-10-14 — Slice 00

- **S0 `5ec4997a` :** miroir octet pour octet du handoff Drive (45 fichiers, tailles vérifiées, JSON valides).
- **Audit aveugle :** fait par un agent Explore sans lire ce dossier.
- **Architecture et contrats :** `docs/06-resolved-architecture.md` et un « Contrat Slice 00 » par Slice, rédigés par un agent planificateur à partir de l'audit et des décisions de l'agent 0, puis relus par l'agent 0.
- **S0 `4bcc2902` :** commit de ce travail.
- **Verdict :** `READY` (`slices/00-project-manager/READINESS.md`).
- **Issue :** ISSUE-01, la limite de 8192 caractères des événements.

## 2026-10-14 — Slice 01

- **Livrables :** N `docs/chat.md` (contrat L2 : projection, lecture `projection=chat`, envoi texte et ordre des gardes, idempotence, `text_channel`, canal vocal, pièces jointes, dépôt Board, panneau, codes, bornes, limites) ; M `docs/conversation-events.md` (paramètre `projection`, clé `attachment_count`), `docs/interaction-mode.md` (*Voice channel and Chat*), `docs/artifacts.md` (natures `upload` / `link`, provenance en métadonnée), `docs/boards.md` (renvoi dépôt) ; N `tests/fixtures/chat_projection/cases.json` (13 cas, 47 événements stockés).
- **Fixture :** événements construits par `build_conversation_event` et encodés par `encode_stored_event` (`jarvis/domain/conversation_event_query.py`, pas `conversation_events.py`). Vérifié : `python -c "import json; json.load(open('tests/fixtures/chat_projection/cases.json', encoding='utf-8'))"` OK ; script jetable (JSON strict, `decode_stored_event` → `encode_stored_event` identique pour les 47 lignes, projection d'esquisse égale à `expected`) OK.
- **Tests docs :** fichier par fichier, tous verts (conversation_events 142, conversation_transcript 27, artifact_payloads 24, workspace_board_contract 72, documented_routes 3, wake_word_docs 30, interaction_mode_hud_js 48, presentation_*_docs, published_benchmark_figures 22, knowledge_wiki 28+1 skip).
- **Écart code / 06 (remonté à l'agent 0) :** `session_not_found` / `binding_not_found` ne sont pas des 503 de `_sessions_unavailable` : celui-ci rend 503 `core_unavailable` ; les deux codes viennent de `SessionManager.current()` (`BoardError`, 404 par `HTTP_STATUS`). Noté en *Open points* de `docs/chat.md`, à trancher avant 03.
- **Choix d'écriture :** `attachment_count` absent quand nul (sinon les événements utilisateur existants changeraient d'octets au rejeu de backfill) ; forme `ChatItem` fixée (9 champs) pour 02.
- **Agent 0, `52e0c162` :** écart tranché. Le garde `brain-turns` réutilise les codes existants : 404 `session_not_found` / `binding_not_found` (`BoardError`) et 503 `core_unavailable`. La section *Open points* de `docs/chat.md` est retirée, `06` est corrigé.
- **QA S1 (`qa-verification` standard, agent Explore) :** `PASS_WITH_POLISH`. Aucun écart avec `06`, 10 faits de code vérifiés, les 13 cas du fixture rejoués par une projection indépendante, ajouts seulement aux docs existantes. Polish reporté :
  - ajouter au fixture un cas `brain.turn.failed` d'une autre conversation **de même corrélation** (confié à 02) ;
  - `chat.md:405` contre `conversation-events.md:2011` sur les ids dans les événements, et `artifacts.md:50` « eleven kinds » (confiés à 07) ;
  - niveaux de `05-documentation-levels.md` à mettre à jour en 10.

## 2026-10-14 — Slice 02

- **Livrables :** N `jarvis/domain/chat_projection.py` (`CHAT_PROJECTION`, `CHAT_EVENT_TYPES`, `is_chat_event`, `ChatItem` à 9 champs, `project_chat` de référence ; repli par import de `collapse_published_messages`, sans copie) ; N `jarvis/runtime/control_center_chat_model.js` (pur, sans DOM : `createChatModel`, `applyPage`, `items`, `markPending`, `isPending`, `reset`) ; N `tests/unit/test_chat_projection.py`, `tests/unit/test_control_center_chat_model_js.py` ; M `tests/fixtures/chat_projection/cases.json` (cas 14 ajouté, 13 premiers inchangés) ; M `docs/chat.md` (signatures, 14 cas).
- **Polish QA S1 traité :** cas `turn_failed_other_conversation_same_correlation` : une publication identique et un `brain.turn.failed` de B partagent la corrélation d'un tour de A ; la bulle de A n'a ni statut d'échec ni repli.
- **Écarts au contrat :** `project_chat(stored_events, *, conversation_id)` (le fixture exige la portée par conversation) ; `brain.turn.failed` sans `attributes.code` → `failure_code = "brain_turn_failed"` ; plusieurs échecs d'une corrélation → le dernier par séquence ; `isPending` ajouté à côté de `markPending` (aucun champ hors des 9 dans `items`).
- **Tests (fichier par fichier) :** chat_projection 31, control_center_chat_model_js 13 (parité Python/JS sur chaque découpage de page de chaque cas), conversation_transcript 27, control_center_timeline_js 72, conversation_events 142 : tous verts. Aucune lecture de `RuntimeJournal`, aucun stockage.
- **QA S2 (`qa-verification` + `code-review` standard) :** `PASS_WITH_POLISH` sur `9987acad`, 375 séquences adverses Python contre JS concordantes (la seule divergence est un cas que le store SQLite ne peut pas produire). Fusionné en avance rapide dans la branche de tâche. Polish reporté à 05 :
  - (a) `ConversationItem` construit par mots-clés (`chat_projection.py:72`) ;
  - (b) commentaire marquant la copie volontaire de `collapseMessages` (`control_center_chat_model.js:111`) ;
  - (c) **décision agent 0** : un `brain.message.published` de séquence supérieure à l'échec efface `failure_code` sur la bulle (une réponse arrivée après l'échec prime). Cas à ajouter au fixture et à `docs/chat.md`.
