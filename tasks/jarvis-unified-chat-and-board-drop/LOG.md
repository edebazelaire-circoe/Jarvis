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

## 2026-10-14 — Slice 04

- **Livrables :** N `jarvis/domain/voice_channel.py` (états, `VoiceChannelReport` strict, `DisableRequest`, `channel_view` pur, `VOICE_CHANNEL_FRESH_S = 5.0`, `VOICE_DISABLE_TIMEOUT_S = 10.0`) ; N `jarvis/core/voice_channel.py` (`VoiceChannelService` en mémoire, `write_gate()` synchrone, diagnostics ids/codes) ; M `server.py` (`POST /v1/voice/channel/report|disable`, `GET /v1/chat/state`), `client.py` (3 méthodes typées, préfixes relayés `/v1/chat/` et `/v1/voice/channel/disable` — jamais `.../report`), `v2_app.py` (`core.voice_channel`) ; M `app.py` (`_report_voice_channel` dans `_voice_timeout_loop`, `VoiceChannelReporting`) ; M `voice_v2.py` (`voice_incarnation_id`, `seq`, rapport `connecting` borné à 0,5 s dans `activate()` ; `mute()` et la logique de session intacts) ; N `jarvis/runtime/chat_relay.py`, M `control_center.py` (`/api/chat` dans `READ_GUARDED_ROUTES`, routes montées) ; M `docs/chat.md` (précisions ci-dessous) ; M `tests/unit/test_capture_relay.py` (liste figée des préfixes relayés).
- **Écarts au contrat (fidèles, documentés dans `docs/chat.md`) :** `channel_view(report, …)` prend le dernier rapport retenu (un seul, pas `reports`) ; réponse du rapport + `schema_version` et `accepted` (rapport ancien ignoré) ; réponse de `disable` + `status` ; un rapport `background` frais pendant une demande la conclut `accepted` (mute par la touche ou le délai) ; Voice déjà au fond acquitte sans `mute()` ; un `lifecycle_state` bien formé mais inconnu vaut `unknown` (pas 400) ; une seule demande en cours (un autre `client_request_id` reçoit la même) ; `/v1/chat/state` sans Session : 404 `session_not_found` / 503 `core_unavailable` existants ; enveloppe CC `{"ok": false, "code", "error", "core_status"}` (415/413 du contrat).
- **Tests nouveaux (fichier par fichier) :** voice_channel_domain 45, voice_channel_service 22, voice_channel_protocol 15 (chaîne réelle Core → CC, Session/Board/`InteractionMode` inchangés assertés), voice_channel_reporter 11 (vrai `PersistentVoiceRuntime`, faux Core portant le vrai service ; boucle réelle : bascule ≤ 2 s, `mute` une fois, Brain/sous-agents simulés intacts, aucun autre appel Core) : tous verts.
- **Régressions :** interaction_mode_follower 7, live_status_ui 11, live_idle_composition_review 21, wake_activation_parity 77, control_center_origin_ports 8, documented_routes 3, v2_architecture 8, capture_relay 35, app 29 + 1 hérité, v2_voice_toggle 35, v2_continuous_live 30, v2_voice_activity 11, v2_speech_scheduler 34, voice_session_binding 10, owner_input_gate 51, control_center_quality 73, interaction_mode_protocol 12, session_protocol 20 : verts. `test_device_playback_completion.py::…cannot_reopen` a échoué une fois sur quatre (délais de 0,2-0,3 s sous charge) ; le chemin ne passe pas par le code de S4 (`activate()` sort avant CONNECTING).

## 2026-10-14 — Slice 03

- **Livrables :** M `server.py` `submit_brain_turn` (pour `source=text` seulement : validation 8192 / `chat_text_too_long`, pièces jointes non vides → 400 `invalid_request` « attachments not supported yet », rejeu durable d'abord, binding courant → 409 `chat_conversation_not_foreground` + `current_conversation_id`, `write_gate()` synchrone sans `await` jusqu'à `submit` → 409 `chat_input_locked` + `reason`, conflit d'identité → 409 `chat_request_conflict`) ; M `v2.py` (`BrainTurnInput.attachments`, ids `jart_` distincts, ≤ 64) ; M `voice_admission.py` (`metadata.attachments` seulement si non vide, clé comparée) ; M `brain_service.py` (`admitted_turn`, `_text_only` avec cache borné + repli durable, retenue `text_channel` après la rétention et avant `_speech_gate`, diagnostic `core.brain.speech_withheld_text_channel`) ; M `control_center_brain.py` (`channel: "text"`) ; M `control_center.py` (`BRIEF_TEXT_CHANNEL`) ; M `chat_relay.py` (`POST /api/chat/turns`, corps fermé, 15 s, `chat.turn.relayed` sans texte) ; M `client.py` (`FORWARDABLE_PATHS`) ; M `docs/chat.md`.
- **Écarts (fidèles, dans `docs/chat.md`) :** `forward_json` n'autorisait pas `/v1/conversations/*` : ajout d'un chemin exact (`.../brain-turns`, jamais `cancel` ni `turns`) au lieu d'un préfixe ; `_find_duplicate` (mémoire) ne compare pas le texte, donc un doublon rendu par `submit` à un tour écrit est revérifié contre le tour durable (deux envois concurrents, textes différents → 202 + 409) ; un relais `announce_notice` porté par un tour écrit est retenu sans second `notice_dropped` ; `reason` / `current_conversation_id` remontés au premier niveau de l'enveloppe CC ; le relais de montage existait déjà (04) ; `test_voice_channel_protocol.py` : ensemble de routes mis à jour.
- **Tests nouveaux :** chat_text_ingress 14, speech_text_channel 4, chat_relay 15 : verts.
- **Régressions (fichier par fichier) :** v2_brain_orchestrator 24, board_speech_authority 18, conversation_event_producers 13, voice_admission_protocol 14, control_center_prompts 5, documented_routes 3, capture_relay 35, voice_channel_domain 45 / protocol 15 / reporter 11 / service 22, conversation_events 142, voice_turn_admission 58, brain_interrupted_speech 5, brain_context_prefab_events 10, v2_brain_contracts 31, conversation_event_backfill 6, brain_notice_contract 34, board_alerts 31, prefab_relay 22, presentation_response_policy 120 : verts. brain_delegation 35 + 1 hérité ; scene_artifacts / scene_query_tools : seul l'échec hérité, mêmes hachages (87c9ecec… contre 20a65470…).
- **Reprise S4 (QA bloquant) :** une demande reçue pendant `connecting` était acquittée `accepted` puis `activate()` passait ACTIVE (le `mute()` ne trouvait aucune session). Correctif (`app.py` `_report_voice_channel`) : en `connecting`, la demande reste non traitée et le tic suivant la reprend ; `mute()` et la session inchangés. Tests ajoutés : fabrique lente + demande pendant `connecting` (jamais `accepted` en ACTIVE, puis mute réel → `background` sans session → `accepted`), `connecting` au-delà de l'expiration (expirée, Chat verrouillé), ack différé renvoyé avec un état non `background` → `failed` / `voice_disable_failed` (documenté dans `docs/chat.md`). Les deux premiers échouent sans le correctif (vérifié).
- **QA S4 (palier critique, `ee92f854`) :** `BLOCKING`.
  - 10 mutants, tous tués.
  - En exécution réelle (Core en sous-processus, vrai `PersistentVoiceRuntime`), 9 scénarios sur 10 passent.
  - Bloquant : une demande traitée pendant `connecting` était acquittée `accepted` alors que la voix finissait `ACTIVE`.
- **Reprise `f8d8860d` :** la demande n'est pas traitée tant que la voix est `connecting`. Un test de régression est ajouté, plus un test d'acquittement périmé (polish).
- **Revérification par la QA :** `PASS_WITH_POLISH`.
- **Course résiduelle :** `ISSUE-02` (`activate`/`mute` sans verrou, déjà dans le code ; le Chat se reverrouille en 1 s au plus).
- **Fusion :** S4 fusionnée en avance rapide dans la branche de tâche.

## 2026-10-14 — Slice 05

- **Livrables :** M `conversation_event_query.py` (domaine : `projection` dans `EVENTS_PARAMS`, `projection_param` — seule valeur `chat`, avec `visibility` → `ValueError`, donc 400 `invalid_request` —, `filter_projection` à côté de `filter_visibility`) ; M `core/conversation_event_query.py` `events()` (`projection` appliquée au même point que la visibilité : le long-poll attend au-delà des lignes cachées) ; M `server.py`, `client.py`, `conversation_event_view.py` (passage de `projection`) ; M `docs/conversation-events.md` (table des routes, phrase « the route takes only… » corrigée), `docs/chat.md` (*Reading*). Aucune route, aucun stockage nouveaux.
- **Polish S2 :** `_entry` construit `ConversationItem` par mots-clés ; commentaire de copie voulue de `collapseMessages` dans `control_center_chat_model.js`. **Décision agent 0 :** une `brain.message.published` de séquence supérieure au dernier `brain.turn.failed` de la corrélation efface `failure_code` ; un échec après la réponse le pose toujours (Python `_failure_status` et JS `failureOf`, 2 cas ajoutés au fixture — 16 —, règle dans `docs/chat.md`).
- **Écart :** `test_conversation_event_query_contract.py` attend désormais `"projection": None` dans `events_query` (forme du dictionnaire). La réponse de la route sans `projection` est inchangée : les tests comparent le JSON décodé à celui de Core, et la QA a confirmé l'identité octet pour octet à l'exécution.
- **Tests nouveaux :** chat_projection_query 5, chat_projection_protocol 6 (Core réel en `tmp_path`, relais CC, `forbidden_origin`, plafond `MAX_LONG_POLLS` partagé avec la chronologie) : verts.
- **Régressions :** chat_projection 33, chat_model_js 13, query_contract 12, query_limits 3, conversation_events 142, timeline_js 72, documented_routes 3, capture_relay 35, query_protocol 34, cc_conversation_events 30, et tous les `tests/unit/test_conversation_event*` : verts.
- **Polish QA S5 (décision agent 0, remplace la règle « réponse postérieure ») :** `failure_code` n'est posé que si **aucune** `brain.message.published` de la corrélation n'existe (tout statut, même conversation) ; sur la panne backend, Core écrit la publication `status = failed` avant `brain.turn.failed`, une seule marque d'échec reste (la bulle du Brain). Python et JS ; fixture : les 2 cas S5 réécrits (sans `failure_code`), cas `backend_failure_published_then_turn_failed` ajouté (17) ; les 14 cas d'origine inchangés, entrées et sorties. `filter_projection` refuse toute valeur autre que `chat`.
- **QA S3 (palier critique, `a7b46f82`) :** `PASS_WITH_POLISH`.
  - **Mutation :** 8 mutants tués sur 10. Les deux survivants (`await` entre le verrou et `submit`, `FORWARDABLE_PATHS` élargi) sont confiés en tests à l'agent de 05 (commit `S3: polish`).
  - **Exécution isolée :** Core et CC isolés, sans Voice. Tous les codes et gardes sont conformes ; un seul `user.transcript.accepted` (`source=text`) par tour, zéro `brain.speech.requested`.
  - **Traces réelles (Claude CLI) :** la ligne du canal écrit est bien dans le brief. Un sous-agent lancé depuis le chat rend son résultat tardif sans parole. Les tours vocaux gardent un contexte identique à la base. Coût ≈ 0,97 USD.
  - **Polish et constats :**
    - Le Brain dépasse la consigne des 6000 caractères (7511, sous la borne de 8192) : consigne seulement, non imposée.
    - Les annonces suivent le tour courant, pas le tour d'origine : un résultat de sous-agent lancé depuis le chat et fini après le retour en vocal reste muet jusqu'à la prochaine parole (documenté dans `docs/chat.md`).
    - `select_outcome` n'a pas d'appelant en production, donc pas de fuite TTS.
    - Le texte figure dans `agent.input` comme avant pour la voix ; pas une régression.
  - **Isolation :** un Control Center isolé crée des dossiers `retours-utilisateur/<horodatage>` dans les Documents de l'utilisateur. C'est déjà le cas avant la tâche ; la QA a supprimé les 4 dossiers vides qu'elle avait créés. À noter dans 09.
- **QA S5 (standard, `90856125`) :** `PASS_WITH_POLISH`.
  - 160 contrôles d'exécution réussis, octets identiques à la base sans `projection`, parité Python/JS sur 3000 événements.
  - **Décision agent 0 :** le statut d'échec n'apparaît que si aucun `brain.message.published` n'existe pour la corrélation ; il remplace la règle (c) précédente.
  - Polish appliqué dans `b3414bf8`.

## 2026-10-14 — Slice 07 (pièces jointes, backend)

- **Livrables :** N `jarvis/domain/uploads.py` (bornes `upload_bounds(env)`, identité `jart_up_<sha256[:40]>`, `sniff_mime`, `payload_name_for`, nom d'origine nettoyé, `BRAIN_READABLE`), `jarvis/core/upload_service.py` (flux borné, rejeu/conflit, échec sans `.partial`, reprise `upload_interrupted`, garde des pièces, bloc du tour), `jarvis/protocol/upload_routes.py` (`PUT /v1/uploads/{id}`), `jarvis/runtime/attachments_brief.py` (bloc de données du brief, lisibilité recalculée par agent). M `ArtifactKind.UPLOAD`, `BrainAttachmentsContext`, `brain_service` (`attachments_context`), `_turn_context`, `build_agent_brief`, `server.py` (étape 5), `voice_admission` (`attachment_count`), `session_manager` (`artifacts_root`), `control_center.py` (`--add-dir` de `artifacts_root`, même politique de relance), `chat_relay.py` (`POST /api/chat/uploads` multipart en flux, corps `chunked` vers Core), `client.py`/`core_sessions.py` (`forward_upload`), `capture_mcp.py`, `control_center_workspace.js`, `capture_api.artifact_summary` (aperçu = nom, `provenance`). Aucune migration (pas de CHECK sur `kind`).
- **Polish S1 :** `docs/chat.md` dit maintenant que les événements ne portent que `attachment_count` (jamais ids, noms, chemins) ; `docs/artifacts.md` « All twelve kinds » ; `docs/presentation-artifacts.md` « now 12 ».
- **Écarts (forcés par le code) :**
  - L'étape 5 (pièces) passe **avant** l'étape 4 (verrou vocal) : elle lit le registre (`await`), et l'étape 4 doit rester la dernière lecture avant `submit` sans `await`.
  - Core accepte `Transfer-Encoding: chunked` à la place de `Content-Length` : le CC ne connaît pas la taille du fichier dans un multipart.
  - Le type est reniflé **avant** la création (le `payload_ref` est figé à la création) ; l'extension du payload suit le type reniflé pour image/PDF.
  - Texte = UTF-8 sans NUL **ni autre octet de contrôle C0** (tab, fins de ligne, saut de page, ESC exceptés).
  - Un essai précédent `failed` → 409 `upload_conflict` (nouvel id requis).
  - Un refus avant le premier octet (vide, `Content-Length` > borne, nom illisible) n'écrit aucun Artifact.
  - `artifacts_root` n'est accordé que si le dossier existe.
  - Le bloc du brief cite les noms entre « ».
- **Tests :** voir le commit S7 (domaine, service, protocole, contexte du cerveau). Mis à jour : `test_chat_text_ingress` (id inconnu → 404), `test_conversation_events` (clé ajoutée), `test_presentation_artifacts_docs` et `test_workspace_presentations_js` (12 natures).
- **Hérités inchangés :** empreinte de prompt `87c9ecec` ≠ `20a65470` (scene_artifacts, scene_query_tools), déjà au BASELINE.
