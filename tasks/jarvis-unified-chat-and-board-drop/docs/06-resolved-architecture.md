# 06 — Architecture résolue (Slice 00, agent 0, 2026-10-14)

**Statut :** contrat de réalisation **contraignant** pour les Slices 01 à 10. Il précise et, là où le code l'impose, corrige `02-architecture.md`. Rédigé après audit aveugle puis vérification dans le code à `664d767b` (branche `task/jarvis-unified-chat-and-board-drop`, worktree `C:/Projects/jarvis/bucd`). Chaque fait cité porte son `chemin:ligne` ; un Work Agent revérifie ce dont il dépend avant de coder (fraîcheur).

Principes tenus partout :

- **Une seule vérité de conversation** : `ConversationEventStore` (`conversation_events` dans `<data_root>/state/jarvis.sqlite3`, ouvert par Core seul). Aucune table, aucun JSONL, aucun cache durable de messages de chat.
- **Zéro migration SQLite** visée et atteinte par ce plan : `_SCHEMA_VERSION` reste `8` (`jarvis/adapters/sqlite_state.py:31`) et `1` pour la scène (`jarvis/adapters/sqlite_scene.py:106`). Les seuls ajouts persistés passent par des colonnes JSON existantes (`turns.data.metadata`, `artifacts.data`) ou par l'ensemble fermé `ArtifactKind`, sans `CHECK` SQL (`sqlite_state.py:173-176`, `docs/artifacts.md` « A new kind is a new `ArtifactKind` value plus this table; no migration »). Si un Work Agent découvre qu'un changement exige malgré tout une migration, il s'arrête et le dit : la règle de `CLAUDE.md` (migration versionnée, snapshot `tests/schema/`) s'applique alors, avec accord de l'agent 0.
- **Aucun agent ne lance, relance ni arrête le JARVIS vivant** (`CLAUDE.md`). Toute preuve runtime se fait sur un worktree avec ses ports et sa racine `JARVIS_DATA_ROOT`.

---

## D-TT — Task Type et affectation

Aucun vocabulaire Workspace Task Type n'existe dans le dépôt ; les handoffs précédents l'ont levé (précédent : `tasks/jarvis-bare-hands-ui-calibration-refinement/slices/00-project-manager/READINESS.md`). Chaque `metadata.json` porte `"task_type": "waived-by-agent-0"`. Chaque Slice reçoit **un** Work Agent (sous-agent Claude), seul implémenteur de son worktree (pas deux implémenteurs dans un même checkout, jamais `git stash`). Les Slices frontend (06, 07b, 08) exécutent en plus `/impeccable`. Compétences QA disponibles : `qa-verification`, `code-review`, `runtime-validation`, `agent-trace-analysis` (`C:/DevTools/skills-lib`).

**Paliers QA.** Critiques : **03, 04, 07** (sécurité et course) — tests de mutation autorisés **uniquement** là, au plus 10 mutants par Slice, sur les gardes listées dans leur contrat. Toutes les autres : palier standard (sans mutation).

---

## Ordre et découpage révisés

| Slice | Dépend de |
| --- | --- |
| 01 | 00 |
| 02 | 01 |
| 04 | 01 |
| 03 | 01, 04 |
| 05 | 02 |
| 06 | 03, 04, 05 |
| 07 | 01, 03 |
| 07b | 06, 07 |
| 08 | 01, 07 (+ 06 pour le séquencement de la page) |
| 09 | 02 à 08, 07b |
| 10 | 09 |

Séquencement imposé en plus des dépendances (fichiers partagés `jarvis/protocol/server.py`, `jarvis/runtime/control_center.py`, `control_center.html`) : 04 → 03 → 05 → 07 côté serveur ; 06 → 07b → 08 côté page. Seule 02 peut tourner en parallèle (de 04).

- **04 passe avant 03** : la garde serveur de l'ingress texte (03) lit l'état du canal vocal (04). Coder 03 avant 04 imposerait un faux état « voix absente » ; on l'évite.
- **05 ne dépend plus de 03** : la lecture ne dépend que du filtre de projection (02).
- **07 est scindé** : `07-chat-attachments` devient le **backend critique** (ingestion, sécurité, référence au Brain) ; la nouvelle Slice **`07b-chat-attachments-ui`** porte le bouton, le glisser-déposer et les états dans le panneau. `08` dépend fonctionnellement de `07` (ingestion), pas de `07b` ; elle passe après 06/07b seulement pour ne pas éditer `control_center.html` en même temps.

---

## D-PROJ — Projection Chat

### Ce que le chat montre

| Événement canonique | Affichage | Règle |
| --- | --- | --- |
| `user.transcript.accepted`, `attributes.addressing` absent ou `addressed` | bulle Utilisateur | immédiate |
| `user.transcript.accepted`, `attributes.addressing = uncertain` | bulle Utilisateur **seulement après promotion** | promue quand un `brain.message.published` de **même `correlation_id`** existe ; affichée à **sa propre** séquence |
| `brain.message.published` | bulle Brain | toutes `kind` (`turn_result`, `work_result`, `speech_result`) et `status` (`failed` stylé comme réponse d'échec rédigée par le Brain) ; doublons repliés |
| `brain.turn.failed` | **statut** (pas une bulle) sur la bulle Utilisateur de même `correlation_id` | `attributes.code` traduit en phrase ; ignoré s'il n'y a pas de bulle Utilisateur (tour système) |
| tout autre type (`mouth.*`, `brain.speech.requested`, `brain.work.*`, `subagent.*`, `tool.*`, `tool_brain.*`, `system.*`, `brain.ui_intent.published`, `brain.turn.accepted`) | jamais | — |

Pourquoi `uncertain` est retenu puis promu : c'est **exactement** la règle durable de Core pour décider qu'un tour incertain a été pris par le cerveau — `_derive_state` garde un tour `uncertain` « en attente jusqu'à trouver, plus loin dans le journal, une parole du cerveau portant sa corrélation » (`jarvis/core/brain_service.py:575-620`), et `submit` ne révise l'intention qu'à la promotion (`brain_service.py:718-727`, `_promote_uncertain_turn` `:1617`). Un tour récusé par `[pas-pour-moi]` (`jarvis/domain/v2.py:104`) ne produit aucun résumé public (`brain_service.py:2087-2092`), donc aucun `brain.message.published` : il reste invisible. `ambient` n'existe pas dans le journal (refusé par `BrainTurnInput`, `v2.py:680-681`, et par la requête d'admission directe, `jarvis/domain/voice_admission.py:152`). Les tours `source=system` ne sont jamais enregistrés (`jarvis/core/voice_admission.py:67`).

Pourquoi `brain.turn.failed` (diagnostique) est admis : `02-architecture.md` exige un état d'échec borné « sans fabriquer une réponse ». Ce type n'a **jamais** de contenu (`docs/conversation-events.md`, note 2) ; seul `attributes.code` est lu. C'est un écart assumé avec « deux types seulement », listé plus bas.

Repli des doublons : règle **existante et testée en parité** Python/JS, « une publication égale à la publication précédente de sa corrélation est fusionnée » (`jarvis/domain/conversation_transcript.py:150-161`, `collapseMessages` dans `control_center_timeline.js:220`). A, B, A reste trois messages.

### Où vit chaque règle

1. **Filtre sans état côté Core** (prédicat pur) : `jarvis/domain/chat_projection.py` (nouveau) expose `CHAT_PROJECTION = "chat"`, `CHAT_EVENT_TYPES` et `is_chat_event(event) -> bool` (les trois types ci-dessus ; un `user.transcript.accepted` dont `addressing` vaut autre chose que absent/`addressed`/`uncertain` est exclu par prudence).
2. **Pas de nouvelle route** : un paramètre `projection` (valeur unique admise `chat`) s'ajoute à `GET /v1/conversation-events` et à son relais `GET /api/conversations/events`. Il entre dans `EVENTS_PARAMS` (`jarvis/domain/conversation_event_query.py:64`), `events_query` (`:141`) et un `filter_projection` frère de `filter_visibility` (`:177`), appliqué au même endroit de la boucle de long-poll (`jarvis/core/conversation_event_query.py:201`). Conséquences gratuites et déjà testées : `next_cursor` avance sur les lignes filtrées, un long-poll filtré attend au-delà des événements cachés (`docs/conversation-events.md` « Cursor, reconnect and live »), le décodeur strict reste valable (séquences croissantes). `projection` et `visibility` ensemble → 400 `invalid_request`. Le Control Center relaie déjà les paramètres via `events_query` → `ConversationEventView.events` (`jarvis/runtime/control_center.py:6545-6550`, `jarvis/runtime/conversation_event_view.py:277-292`) : il faut seulement y faire passer `projection` jusqu'à `LocalCoreClient.list_conversation_events` (`jarvis/protocol/client.py:454`).
3. **Règles avec état côté client** (promotion `uncertain`, repli, statut d'échec, clé par `event_id`) : module **pur** `jarvis/runtime/control_center_chat_model.js` (nouveau, sans DOM), avec une **implémentation de référence Python** dans `jarvis/domain/chat_projection.py` (`project_chat(stored_events) -> tuple[ChatItem, ...]`) et un **fixture partagé** `tests/fixtures/chat_projection/cases.json` joué par pytest et par node (même pratique que la parité du repli). La séparation est imposée par le flux : une promotion arrive après que le curseur a dépassé le tour incertain.

### Portée

La conversation affichée est `binding.conversation_id` de la Session ouverte et de son Board actif (`SessionManager.current()`, `jarvis/core/session_manager.py:397-416`, `GET /v1/sessions/current`, `jarvis/protocol/server.py:1293-1318`). Le `session_id` des événements utilisateur est la session vocale, **pas** `jarvis_session_id` : il n'est jamais utilisé pour filtrer. Changement de Board → le client relit `GET /api/chat/state`, vide son modèle et réhydrate depuis `after_sequence=0` pour la nouvelle conversation. Jamais de fusion de plusieurs Boards.

### Lecture live

**Révisé après la QA bloquante de la Slice 06 (décision agent 0, 2026-10-14) : aucun long-poll pour le Chat.** Chrome partage **six** connexions HTTP/1.1 par origine entre tous les onglets ; chaque onglet du Control Center tient déjà ses propres attentes longues (commandes plein écran, explorateur du Studio, chronologie). Un long-poll de 25 s par onglet affamait `/api/status`, `/api/chat/state` et l'envoi (> 9 s) dès deux onglets.

- Une boucle par onglet, **séquentielle** (jamais deux requêtes du Chat en vol) : `GET /api/chat/state` puis la lecture des événements, toutes les **1,5 s** ; toutes les **0,5 s** pendant **20 s** après un envoi (le sien ou celui d'un suiveur) ou un changement d'état.
- Événements : lecture **courte** (jamais `wait_ms`), `projection=chat`, `limit=500`, depuis le **dernier `next_cursor` reçu** (hydratation depuis `after_sequence=0`), suivie tant que `has_more`.
- **Un seul lecteur par profil** : le détenteur du verrou Web Locks `jarvis.chat.<conversation_id>` lit les événements et les diffuse sur `BroadcastChannel('jarvis.chat.<conversation_id>')` ; les suiveurs ne lisent aucun événement (demande d'historique `hello`, envoi signalé `poke`) et reprennent le verrou quand le meneur part. Sans Web Locks ou sans BroadcastChannel : solo, même cadence.
- Panneau fermé ou onglet caché : **aucune** requête, verrou rendu.
- Preuve : `tests/unit/test_control_center_chat_tabs_browser.py` (vrai serveur HTTP qui tient les attentes de la page). Limite constatée hors du Chat : trois onglets visibles plus la chronologie dépassent déjà les six connexions **Chat fermé** (attentes de la page elle-même) ; le Chat n'y ajoute aucune attente. Mesure réelle (Core + Control Center isolés, 2026-10-15) : deux onglets Chat, `/api/status` 23 / 13 ms et envoi d'un suiveur reçu dans les deux en 0,7 s ; trois onglets quelconques, Chat ouvert ou fermé, `/api/status` ≈ 8,3 s / 8,6 s, car chaque onglet tient deux attentes de 25 s (`/api/fullscreen/commands`, `/api/presentation-studio/explorer/commands`).

### Limite connue (non corrigée ici)

Un contenu d'événement est borné à `MAX_CONTENT_CHARS = 8192` (`jarvis/domain/conversation_events.py:40`) ; un résultat plus long **n'est pas enregistré** (`docs/conversation-events.md`, « Text above the content bound (8192) is not truncated: the event is not recorded »). Le chat ne peut donc pas afficher une réponse Brain de plus de 8192 caractères. Mesures : la saisie texte est bornée à 8192 (`chat_text_too_long`) ; le brief du canal texte (D-INGRESS) demande une réponse écrite de 6000 caractères au plus et, au-delà, un fichier dans le dossier du Context ; la bulle Utilisateur sans réponse après 120 s affiche « Toujours en cours, ou réponse non affichable ici — voir la chronologie complète » avec un lien vers la chronologie, jamais un faux message. Relever la borne est un changement de contrat d'événements, hors de cette tâche (Issue à ouvrir par l'agent 0).

---

## D-INGRESS — Envoi texte

### Routes

**Control Center** `POST /api/chat/turns` (nouveau, dans `jarvis/runtime/chat_relay.py` créé par 04) :

```json
{"conversation_id": "conv-…", "client_request_id": "<uuid v4>", "content": "texte", "attachments": ["jart_…"]}
```

- Garde : le préfixe `/api/chat` entre dans `READ_GUARDED_ROUTES` (`jarvis/runtime/control_center.py:300-304`) ; `_origin_guard` (`:2061-2081`) applique alors à **toutes** les méthodes Host de bouclage, Origin de bouclage s'il est présent, refus de `Sec-Fetch-Site: cross-site` et, pour une mutation, de `same-site` (`_loopback_refusal`, `:360-383`). En plus : `Content-Type: application/json` exigé (415 `invalid_content_type`), corps borné à 64 Kio (413 `request_too_large`).
- Relais vers Core `POST /v1/conversations/{conversation_id}/brain-turns` (`jarvis/protocol/server.py:174`, handler `:585-667`) avec `{"content", "correlation_id": "chat:" + client_request_id, "source": "text", "addressing": "addressed", "attachments": [...]}`. Délai 15 s ; un délai dépassé rend 504 `core_timeout` avec « issue inconnue : renvoyer le même `client_request_id` ».
- Journal Control Center : `chat.turn.relayed` (statut, code, `correlation_id`, nombre de pièces), jamais le texte.

**Core** — même route `brain-turns`, aucune route parallèle. Pour `source = "text"` uniquement, le handler applique dans cet ordre :

1. Validation : `content` non vide et `len(content) ≤ 8192` (sinon 400 `chat_text_too_long`) ; `attachments` liste d'au plus `JARVIS_CHAT_MAX_ATTACHMENTS` (défaut 10) ids d'Artifact distincts (400 `too_many_attachments`).
2. **Rejeu d'abord** : si le tour durable `brain-turn-<stable_identity(conversation, correlation)>` existe déjà (`voice_admission.py:119-121`), la garde est sautée et `submit` rend le doublon (200, `duplicate: true`). Un renvoi après bascule de voix ne doit pas devenir un 409.
3. **Liaison au premier plan** : `SessionManager.current().binding.conversation_id` doit égaler `{conversation_id}` ; sinon 409 `chat_conversation_not_foreground` (le corps donne la conversation courante, pour que l'UI se recale). Session ou binding absent : codes `BoardError` existants de `SessionManager.current()`, 404 `session_not_found` / `binding_not_found` ; service de Session non câblé : 503 `core_unavailable` existant (`_sessions_unavailable`). Corrigé par l'agent 0 après la Slice 01.
4. **Canal vocal** (D-VOICE) : lecture **synchrone** de l'état en mémoire, sans `await` entre cette lecture et l'appel de `self.core.brain.submit(turn)`. Si l'écriture n'est pas permise : 409 `chat_input_locked`, `reason` ∈ `voice_active`, `voice_connecting`, `voice_switching`, `voice_error`, `voice_unknown`.
5. **Pièces jointes** (Slice 07) : pour chaque id, dans l'ordre du message, comme `UploadService.attachment_refusal` (`jarvis/core/upload_service.py`) et `docs/chat.md` : il existe (404 `attachment_not_found`) ; il est de nature `upload`, provenance `chat_attachment`, et appartient à la Session ouverte (400 `attachment_not_allowed`) ; il est lié au Board du binding visé (409 `attachment_other_board`, reprise post-Slice 09 ; liens Board non câblés : 503 `core_unavailable`) ; enfin il est `complete` (409 `attachment_not_ready`). Le premier refus l'emporte.
6. `BrainOrchestrator.submit` (inchangé dans son principe) : persistance unique, `user.transcript.accepted`, dépêche au cerveau du binding.

Point de linéarisation de la course « envoi / réveil vocal » : l'étape 4. Un rapport vocal traité après elle n'annule pas le tour : il a été admis légalement, son résultat reste écrit (D-NOTTS) et l'UI le montre.

### Idempotence

`client_request_id` (UUID v4 généré par le navigateur **par message composé**, réutilisé à chaque nouvelle tentative) devient `correlation_id = "chat:" + client_request_id`. La déduplication existe déjà, en mémoire (`_find_duplicate`, `brain_service.py:1278`) **et durable** : `persist_turn` dérive `turn_id` de `(conversation, correlation)` et reconnaît la source durable (`voice_admission.py:119-124`), puis `claim_backend_dispatch` refuse de redépêcher un doublon sans admission directe (`:154-166`). Même `client_request_id` avec un autre texte ou d'autres pièces → `ValueError("admission identity conflicts…")` (`:134-140`), rendu **409 `chat_request_conflict`** pour `source=text` (au lieu du 400 générique). `persist_turn` ajoute `attachments` à la liste des clés comparées.

### Ce que le Brain reçoit

- `BrainTurnInput` gagne `attachments: tuple[str, ...] = ()` (ids d'Artifact), persisté dans `turns.data.metadata.attachments` **seulement s'il est non vide** (métadonnée JSON : pas de migration ; les tours existants restent identiques octet pour octet).
- `_turn_context` (`jarvis/adapters/control_center_brain.py:101-170`) ajoute `"channel": "text"` pour `source=text` et, pour les pièces, le bloc `attachments` (D-ATT). Absents sinon : contexte inchangé octet pour octet, comme les blocs précédents.
- `build_agent_brief` (`jarvis/runtime/control_center.py:1019-1075`) rend, pour `channel=text`, une ligne : « Canal : écrit (chat). Ta réponse sera lue, pas dite : texte simple, 6000 caractères au plus ; au-delà, écris un fichier dans le dossier du Context et donne son chemin. »
- Même cerveau, même binding, mêmes outils, mêmes sous-agents : le tour suit `run_turn_with_context` (`brain_service.py:1845`) → `POST /api/agent/ask` **interne** Core → Control Center (`control_center_brain.py:704-708`). Le navigateur n'appelle **jamais** `/api/agent/ask` ni `/api/agent/send` (`control_center.py:1485-1486`) pour le chat : ces routes contournent les événements canoniques.

### Réponse de `POST /api/chat/turns`

202 (nouveau) ou 200 (doublon) : `{"ok": true, "correlation_id", "turn_id", "duplicate"}`. Le client garde un **état d'attente** local (pas une bulle) jusqu'à l'arrivée du `user.transcript.accepted` de même `correlation_id`, puis attend la réponse.

---

## D-NOTTS — Aucun TTS pour un tour texte

Constat : chaque résultat retenu part aussi en `brain.speech.requested` (`_emit_speech`, `brain_service.py:2612-2715` : rétention `:2638-2645`, porte Board `:2646-2651`, publication `:2707-2715`). Il n'existe aucune disposition par tour.

Décision : une **disposition de sortie par corrélation**, décidée dans `_emit_speech` **juste après la rétention** (`:2645`) et **avant** `_speech_gate` :

- `BrainOrchestrator._text_only(conversation_id, correlation_id) -> bool` : vrai si le tour d'origine a `metadata.source == "text"`. Cache mémoire alimenté par `submit` pour `source=text` ; repli **durable** par `repository.get_turn("brain-turn-" + stable_identity(conversation_id, correlation_id))`, pour qu'un résultat de sous-agent qui arrive des heures plus tard, ou après un redémarrage de Core, reste muet.
- Si vrai : diagnostic `core.brain.speech_withheld_text_channel` (`conversation_id`, `correlation_id`, `speech_id`, `kind`), retour `_SpeechEmission(False, None, SPEECH_WITHHELD_TEXT_CHANNEL)` avec `SPEECH_WITHHELD_TEXT_CHANNEL = "text_channel"`. Le résultat est déjà retenu, donc `brain.message.published` existe ; aucun `brain.speech.requested`.
- Les questions et accusés (`SpeechKind.QUESTION/ACK/PROGRESS`) ne sont pas retenus comme issues (`:2641`) : sur un tour texte ils deviennent muets **et** invisibles. Ce n'est pas une perte de réponse : l'adaptateur publie toujours la réponse en `work_result` (`control_center_brain.py:604-612` → rétention `brain_service.py:2332`).
- Les notices spontanées (tours `source=system`) gardent leur politique : retenues, donc visibles au chat, et dites seulement si la voix est active.
- `InteractionMode` et `OutputDisposition` (`docs/interaction-mode.md` « Output disposition ») ne sont **pas** réutilisés : ils gouvernent la présentation selon le mode, pas le canal d'un tour.

---

## D-VOICE — État du canal vocal possédé par Core

### Constats

- L'état réel vit dans le processus Voice : `VoiceLifecycleState{background, active, connecting, error}` (`jarvis/domain/v2.py:81-85`), porté par `PersistentVoiceRuntime.runtime.state` (`jarvis/runtime/voice_v2.py:109-121`) ; il est publié chaque seconde dans `runtime/.voice_runtime` (`voice_runtime_report`, `voice_v2.py:1584-1593` ; boucle `_voice_timeout_loop`, `jarvis/app.py:1767-1813`) et `.voice_state` / `.voice_heartbeat` (`jarvis/runtime/visual_signals.py:23-30`), lus par le Control Center (`control_center.py:2445-2491`, `VOICE_HEARTBEAT_MAX_AGE_S = 5.0`, `:212`). Core n'en sait rien.
- `mute()` (`voice_v2.py:1345-1416`) arrête la parole, ferme la session fournisseur et l'audio, repasse en `background` et **ne touche ni Core, ni le Brain, ni les sous-agents** ; une fermeture non confirmée laisse `error`.
- Précédent de commande Control Center → Voice : `.voice_live_stop_request` / `.voice_live_stop_receipt` (`visual_signals.py:105-131`), consommé à la seconde par `_handle_live_ui_supervision` (`app.py:1835-1878`) qui appelle `voice.mute(VoiceStopReason.USER)` et rend un reçu `accepted` / `failed`, idempotent par `request_id`.
- Core possède déjà un cycle de vie **Live** durable (`/v1/live/sessions/*`, `jarvis/domain/live_lifecycle.py:15-21`), mais seulement pour les architectures GPT-Live (`jarvis/runtime/live_primary_owner.py`, `live_frontend_session.py`) : c'est un bail de facturation, pas l'état d'écoute de toutes les architectures. Il n'est **pas** réutilisé.

### Décision

Un service Core **en mémoire** `VoiceChannelService` (`jarvis/core/voice_channel.py`, nouveau ; domaine pur `jarvis/domain/voice_channel.py`), nourri par les **rapports** du processus Voice, qui reçoit en retour la demande de désactivation éventuelle. C'est le précédent « reçu idempotent à la seconde » du Live stop, déplacé du fichier vers Core pour que **Core**, qui admet les tours, soit juge. Pas de nouvel abonnement WebSocket : `CoreEventBus` ne rejoue rien et la boucle d'une seconde existe déjà.

**Rapport Voice → Core** `POST /v1/voice/channel/report` (jeton Core comme toute route `/v1`) :

```json
{"schema_version": 1, "voice_incarnation_id": "voice-<uuid>", "seq": 42,
 "lifecycle_state": "background|active|connecting|error", "conversation_id": "conv-…|null",
 "ack": {"request_id": "vcr-…", "result": "accepted|failed", "code": "voice_disable_failed|null"} }
```

Envoyé (a) à chaque tic de `_voice_timeout_loop` (1 s), (b) **immédiatement** à l'entrée en `connecting` (avant l'ouverture du micro, attente bornée à 0,5 s, un échec n'empêche pas l'activation et est journalisé), (c) juste après un `mute()` déclenché par une demande, avec `ack`. `voice_incarnation_id` est tiré au démarrage du processus ; `seq` croît strictement par incarnation. Core ignore un rapport de `seq` inférieur ou égal pour la même incarnation ; une incarnation nouvelle remplace l'ancienne. Réponse : `{"epoch", "revision", "disable_request": {"request_id", "requested_at"} | null}`.

**Commande Control Center → Core** `POST /v1/voice/channel/disable` `{"client_request_id": "<uuid>"}` : crée (ou rend, si même `client_request_id`) une demande `vcr-…`, revision+1 ; rend 202 `{"request_id", "state": "switching"}`. Voix `absent` ou déjà `background` sans demande : 200 `{"state": …, "request_id": null}` (rien à faire). Le Voice prend la demande dans la réponse de son prochain rapport (≤ 1 s), appelle `voice.mute(VoiceStopReason.USER)` comme le Live stop, puis rapporte `background` avec `ack.result = accepted` (ou `failed` + code si `mute()` lève ou laisse `error`). Une demande non acquittée en `VOICE_DISABLE_TIMEOUT_S = 10` s expire (`expired`).

**Lecture** `GET /v1/chat/state` (Core) relayée par `GET /api/chat/state` :

```json
{"schema_version": 1, "jarvis_session_id": "…", "board_id": "…", "conversation_id": "…",
 "voice": {"state": "absent|background|connecting|active|error|switching|unknown",
           "epoch": "…", "revision": 7, "report_age_ms": 400,
           "request": {"request_id": "vcr-…", "status": "pending|accepted|failed|expired", "code": null} },
 "chat_writable": true, "locked_reason": null}
```

### Machine d'état (vue Core)

| État | Condition | Écriture chat |
| --- | --- | --- |
| `unknown` | Core démarré depuis moins de `VOICE_CHANNEL_FRESH_S` (5 s, aligné sur `VOICE_HEARTBEAT_MAX_AGE_S`) sans rapport ; ou rapport frais d'état illisible | refusée `voice_unknown` |
| `absent` | aucun rapport, ou dernier rapport plus vieux que 5 s, après la période de grâce | **permise** (chat sans runtime vocal) |
| `background` | rapport frais `background`, pas de demande en cours | **permise** |
| `connecting` | rapport frais `connecting` | refusée `voice_connecting` |
| `active` | rapport frais `active` | refusée `voice_active` |
| `error` | rapport frais `error` (fermeture non confirmée, audio pendant) | refusée `voice_error` |
| `switching` | demande `pending` non expirée et dernier rapport ≠ `background` | refusée `voice_switching` |

Transitions : `active|connecting|error --disable--> switching` ; `switching --rapport background + ack accepted--> background` ; `switching --ack failed | expiration--> état du dernier rapport` (la demande garde `failed`/`expired` et son code pour l'UI) ; `background --rapport connecting (réveil, touche, mot de réveil)--> connecting` (le chat se reverrouille) ; tout état `--5 s sans rapport--> absent`. Un réveil pendant `switching` : le dernier rapport gagne ; si le Voice a déjà vu la demande, il l'exécute (le choix explicite de l'utilisateur est le plus récent), sinon la demande expire et l'UI propose de réessayer.

Ce que la bascule **ne fait jamais** : fermer la Session, changer de Board ou de binding, annuler `BrainOrchestrator`, arrêter un CLI du pool ou un sous-agent, toucher `InteractionMode`. `mute()` n'en fait rien (`voice_v2.py:1352-1416`), et Core n'appelle que son propre service en mémoire. Redémarrage de Core : état perdu, période `unknown` de 5 s, puis le premier rapport rétablit la vérité.

`InteractionMode` (`docs/interaction-mode.md`, SIMPLE / PRESENTATION / REUNION) est un autre axe et n'est pas lu pour ce verrou.

---

## D-ATT — Pièces jointes du chat

### Constats

Aucune route de téléversement n'existe ; `ClaudeLocalAgent.send(images=…)` lève hors profil `speculative_analysis` (`jarvis/runtime/claude_local.py:1558-1562`) ; les Artifacts ont une nature fermée sans `CHECK` SQL, des payloads `<data_root>/artifacts/<id>/<nom>` aux noms `[a-z0-9_.-]`, écrits en `.partial` puis renommés, et sont liés **automatiquement** au Board actif de la Session ouverte dans la transaction de création (`link_to_active_board`, `jarvis/adapters/sqlite_board_artifact_links.py:53-70`, appelé par `sqlite_artifacts.py:171`). Le cerveau reçoit `--add-dir <data_root>/sessions` (`control_center.py:1552-1555`, appris par `_learn_sessions_root` `:1805-1816` depuis `sessions_root` que Core met dans `GET /v1/sessions/current`, `jarvis/core/session_manager.py:836`) et le dossier des Boards ; **pas** `<data_root>/artifacts`. Le mode par défaut du CLI est `bypassPermissions` (`claude_local.py:42`). Le corps HTTP de Core est borné à 6 Mio pour `read()` (`server.py:166`, `MAX_CONVERSATION_EVENT_BATCH_BODY_BYTES`) et celui du Control Center à 1 Mio par défaut ; un flux lu par morceaux (`request.content`, `request.multipart()`) n'est pas soumis à ces bornes.

### Chaîne

```text
navigateur --multipart, 1 fichier par requête--> CC POST /api/chat/uploads
  CC (garde /api/chat, flux en morceaux, aucune copie disque) --PUT flux--> Core PUT /v1/uploads/{client_upload_id}
  Core: Artifact kind=upload pending -> spool .partial -> borne -> renifle -> finalize complete|failed
navigateur <-- {artifact_id, original_name, mime_type, size_bytes, brain_readable, state}
POST /api/chat/turns {..., attachments:[artifact_id]} -> Core -> BrainContext.attachments -> brief -> Read par le CLI
```

**Core** `PUT /v1/uploads/{client_upload_id}` (nouveau, `jarvis/protocol/upload_routes.py`, façade `jarvis/core/upload_service.py`, règles pures `jarvis/domain/uploads.py`) :

- Paramètres : `purpose=chat|board` ; `board_id` requis pour `board` ; en-têtes `Content-Length` (requis), `Content-Type` (déclaré), `X-Jarvis-Upload-Name` (nom d'origine en UTF-8 encodé pourcent, ≤ 255 caractères après décodage).
- Identité rejouable : `artifact_id = "jart_up_" + sha256(client_upload_id)[:40]`. Même `client_upload_id` déjà `complete` avec même taille et même empreinte → 200 avec l'Artifact (rejeu) ; différent → 409 `upload_conflict`. Encore `pending` (requête concurrente) → 409 `upload_in_progress`.
- Artifact : `kind = upload` (nouvelle valeur d'`ArtifactKind`, `jarvis/domain/artifacts.py:136`), `source = "chat"` ou `"board_drop"`, `jarvis_session_id` et `context_id` de la Session et du Context actifs, `payload_name = "upload" + ext`, `ext` = extension d'origine en minuscules si elle respecte `[a-z0-9]{1,8}` (Claude lit images et PDF d'après l'extension), sinon `upload.bin`. Métadonnées : `original_name`, `declared_mime`, `sha256`, `provenance` (`chat_attachment` | `board_drop`), `client_upload_id`, `brain_readable` (bool).
- Flux : lecture par morceaux de 64 Kio dans `ArtifactService.open_spool`, refus dès que l'on dépasse `JARVIS_UPLOAD_MAX_BYTES` (défaut 64 Mio, configurable ; la borne est technique et dite à l'utilisateur) → spool fermé, Artifact `failed` code `upload_too_large`, 413. Corps plus court que `Content-Length` → `failed` `upload_incomplete`, 400. Vide → 400 `upload_empty`.
- Type : reniflage des octets de tête (PNG, JPEG, GIF, WebP, PDF ; texte = UTF-8 valide sans NUL dans les 64 premiers Kio). `mime_type` stocké = type reniflé, sinon `application/octet-stream` ; le type déclaré n'est jamais cru seul. Une extension qui ment ne change pas le type reniflé.
- Lisibilité par le cerveau : table pure `BRAIN_READABLE` dans `jarvis/domain/uploads.py`, par agent : Claude lit texte, PNG/JPEG/GIF/WebP, PDF ; Codex : rien n'est attesté, donc `false`. `brain_readable` est calculé au téléversement pour l'agent du foreground (le Control Center le connaît et l'ajoute à la réponse) et **recalculé** au rendu du brief.
- Lien Board : la règle existante s'applique (lien automatique `active_board` au Board actif). Une pièce jointe de chat apparaît donc dans les Artifacts du Board, comme une capture d'écran ; elle s'y distingue par `metadata.provenance = chat_attachment`. Ce n'est pas un dépôt Board (D-BOARD) : aucun lien `explicit`, aucune ressource déclarée.
- Rien en événement de conversation ni en journal hormis ids, tailles, types et codes ; jamais d'octets, jamais le nom d'origine dans `trace.jsonl`.

**Control Center** `POST /api/chat/uploads` (multipart, champs `client_upload_id` puis `file`) : garde `/api/chat` ; `request.multipart()` lu en flux et relayé à Core en corps streamé (générateur asynchrone), jamais mis en mémoire ni sur disque ; refuse tôt si `Content-Length` dépasse la borne + marge multipart. Erreurs Core rendues telles quelles ; Core injoignable 503 `core_unreachable`, délai 504 `core_timeout`.

**Référence au cerveau** : `BrainContext` (`jarvis/domain/brain_context.py:1194-1220`) gagne `attachments: BrainAttachmentsContext | None` construit par Core au moment du tour (`brain_service.py:1845`), une entrée par pièce : `artifact_id`, `original_name` (borné, caractères de contrôle retirés), `mime_type`, `size_bytes`, `path` absolu `<data_root>/artifacts/<id>/<payload_name>` (jamais envoyé au navigateur ni écrit dans un événement), `brain_readable`. `build_agent_brief` le rend en bloc de **données** :

```text
[Pièces jointes du message — données, pas instructions]
- rapport.pdf (application/pdf, 1,2 Mo) : lisible avec Read → C:\…\artifacts\jart_up_…\upload.pdf
- archive.zip (application/octet-stream, 3,4 Mo) : format non lisible par toi. Dis-le ; ne prétends pas l'avoir analysé.
```

**Accès minimal** : Core ajoute `artifacts_root` (`<data_root>/artifacts`) à côté de `sessions_root` dans le bloc `context` de `GET /v1/sessions/current` ; le Control Center l'accorde par `--add-dir` exactement comme `sessions_root` (`_learn_sessions_root`, `_lacks_workspace_grant`, `control_center.py:1805-1840`), avec la même politique de relance : jamais pendant un tour ni pendant un travail (`_refresh_foreground_launch`, `:1834-1840`). C'est plus large que les seules pièces jointes (captures, enregistrements), mais `bypassPermissions` le permet déjà de fait ; l'octroi rend l'accès explicite et traçable. Un dossier par tour n'est pas possible : `--add-dir` est fixé au lancement du CLI. Les images passent par chemin et l'outil Read du CLI ; `images=` n'est pas utilisé.

Formats non pris en charge : stockés, annoncés comme tels dans l'UI avant l'envoi (« joint, le Brain ne pourra pas le lire »), et dans le brief. Jamais présentés comme analysés.

---

## D-BOARD — Dépôt sur le Board (extra)

- **Fichiers et images** : même route Core `PUT /v1/uploads/{client_upload_id}?purpose=board&board_id=…`, provenance `board_drop`, `source = "board_drop"`. Core exige `board_id == active_board_id` de la Session ouverte (409 `board_drop_target_inactive`) : on ne dépose que sur le Board affiché. Le lien automatique de la transaction de création **est** le lien Board. Contrôle après création : si `boards_of_artifact` ne contient pas la cible (bascule entre le contrôle et la transaction), Core lie explicitement la cible par `WorkspaceService.artifact_link(origin=user)` (route existante `POST /v1/workspace/boards/{board_id}/artifacts/{artifact_id}`, `docs/artifacts.md` « Board links ») et le dit dans la réponse (`relinked: true`). L'utilisateur a déposé sur la cible seule : si l'Artifact a été créé par **cette** requête (jamais sur un rejeu), Core retire ensuite le lien automatique `active_board` que la création a posé sur le Board devenu actif (`WorkspaceService.artifact_unlink(origin=user)`, même port `BoardDropSeam`), et seulement un lien de cette origine — un lien `explicit` reste. Journal `core.upload.board_auto_link_removed` (`warning`). Échec du retrait : `core.upload.board_auto_link_remove_failed` (`error`), la réponse garde la cible liée et nomme le Board resté lié dans `also_linked_board_id` (sinon `null`, ignorable par la page). `link_to_active_board` n'est pas modifié (rework Slice 08, 2026-10-15).
- **URL** : `POST /v1/uploads/links` `{client_upload_id, url, board_id}` → Artifact `kind = link` (nouvelle valeur), créé `complete` d'un coup avec `text = url` (comme `record_text`), métadonnées `provenance = board_drop`, `host`. URL acceptée : `http`/`https` seulement, ≤ 2048 caractères, sans identifiants (`user:pass@`), sans caractères de contrôle ; sinon 400 `link_invalid`. **Jamais** récupérée (pas de requête réseau, pas d'aperçu).
- **Visibilité** : inspecteur Workspace (liste des Artifacts par Board, `GET /v1/workspace/artifacts?board_id=`, déjà servie) avec libellés `upload` « Fichier déposé » / « Pièce jointe du chat » selon la provenance, `link` « Lien ». Libellés dans `control_center_workspace.js:69` et filtre `artifact_search` (`jarvis/runtime/capture_mcp.py:606`).
- **Pas d'objet de scène** dans cette tâche : les artefacts de la scène sont des explications choisies par le cerveau, liées par `explains` à l'étoile qu'elles expliquent (`docs/scene-model.md:484-490`) ; un fichier déposé n'en est pas une. En créer un tordrait le contrat de scène. Proposition à garder en Issue.
- Jamais un tour de chat, jamais un message au cerveau, jamais une conversation créée.

---

## D-UI — Interface

- Module **`jarvis/runtime/control_center_chat.js`** (vue) + **`control_center_chat_model.js`** (modèle pur, testé par node), injectés par marqueurs `/*__CONTROL_CENTER_CHAT_MODEL_JS__*/` et `/*__CONTROL_CENTER_CHAT_JS__*/` dans `control_center.html`, remplacés par `control_center.py` comme `LIVE_SCRIPT_MARKER` (`control_center.py:448-449`, `:2244`). `control_center_timeline.js` et `tests/unit/test_control_center_timeline_ui.py` ne sont **pas modifiés** (branche concurrente `task/transcription-tab-live-refresh`, non fusionnée, qui les modifie).
- Onglet **Chat** fixe en bas à droite (`right:18px; bottom:18px`), hors du dock vertical centré (`.dock`, `control_center.html:90`). Les toasts, aujourd'hui en bas à droite (`html:277`), remontent au-dessus de l'onglet (`bottom` = 18 px + hauteur de l'onglet + 10 px) ; leur décalage existant quand un panneau est ouvert (`html:294`) reste valable.
- Panneau : `<section class="panel chat-panel" id="chatPanel">` qui réutilise `.panel` (`html:95`) et ses tokens ; un seul panneau latéral ouvert à la fois (ouvrir `#panel` ferme le chat et inversement). Glissement horizontal depuis la droite, désactivé sous `prefers-reduced-motion`.
- Bulles Utilisateur et Brain en `textContent` (jamais d'HTML issu du contenu), retours à la ligne préservés. Composer multiligne : Entrée envoie, Maj+Entrée saute une ligne ; bouton Envoyer ; double envoi impossible (bouton inerte pendant la requête, même `client_request_id` en reprise).
- Voix active : historique lisible, composer `aria-disabled="true"` (pas `disabled`, pour garder le focus et l'explication), message « Désactivez le vocal pour écrire » et bouton **Passer au chat** ; pendant `switching` « Arrêt du vocal… » ; échec ou expiration : message et « Réessayer ». Un 409 `chat_input_locked` reçu malgré tout rebascule l'UI en lecture seule (la garde serveur prime).
- Lien « Voir la chronologie complète » qui ouvre la chronologie existante (`#openTimeline`).

---

## Codes d'erreur stables

Forme Core `{"error": {"code", "message", …}}` ; forme Control Center `{"ok": false, "code", "error", "core_status"}` (comme `/api/conversations`). Un code Core est relayé tel quel.

| Code | HTTP | Émetteur | Cas |
| --- | --- | --- | --- |
| `forbidden_origin` | 403 | CC | garde `/api/chat` |
| `invalid_content_type` | 415 | CC | JSON attendu |
| `request_too_large` | 413 | CC | corps JSON > 64 Kio |
| `invalid_request` | 400 | Core, CC | paramètre ou corps hors contrat |
| `chat_text_too_long` | 400 | Core | `content` > 8192 caractères |
| `too_many_attachments` | 400 | Core | > `JARVIS_CHAT_MAX_ATTACHMENTS` |
| `attachment_not_found` | 404 | Core | id inconnu |
| `attachment_not_ready` | 409 | Core | pièce non `complete` |
| `attachment_not_allowed` | 400 | Core | autre nature, provenance ou Session |
| `attachment_other_board` | 409 | Core | pièce non liée au Board de la conversation du tour (reprise post-Slice 09) |
| `chat_conversation_not_foreground` | 409 | Core | cible ≠ binding courant |
| `chat_input_locked` | 409 | Core | voix non désactivée (`reason`) |
| `chat_request_conflict` | 409 | Core | même `client_request_id`, autre contenu |
| `session_not_found`, `binding_not_found` | 404 | Core | codes `BoardError` existants |
| `core_unavailable` | 503 | Core | code existant, service de Session non câblé |
| `core_stopping` | 503 | Core | code existant (`server.py:657-664`) |
| `core_unreachable` | 503 | CC | Core injoignable |
| `core_timeout` | 504 | CC | issue inconnue, rejouer |
| `core_unauthorized`, `invalid_core_response` | 502 | CC | codes existants |
| `voice_disable_failed` | — (dans `request.code`) | Voice | `mute()` a levé ou laissé `error` |
| `voice_disable_expired` | — (dans `request.code`) | Core | pas d'acquittement en 10 s |
| `upload_too_large` | 413 | Core | borne dépassée |
| `upload_empty` | 400 | Core | corps vide |
| `upload_incomplete` | 400 | Core | moins d'octets que `Content-Length` |
| `upload_name_invalid` | 400 | Core | nom illisible ou trop long |
| `upload_conflict` | 409 | Core | même `client_upload_id`, autres octets |
| `upload_in_progress` | 409 | Core | même `client_upload_id` en cours |
| `upload_storage_failed` | 503 | Core | payload refusé (`artifact_payload_*`) |
| `board_drop_target_inactive` | 409 | Core | dépôt sur un Board non actif |
| `link_invalid` | 400 | Core | URL refusée |

---

## Emplacements de données

Tout sous la racine du poste (`docs/local-data.md`, `~/.jarvis/instances/<dépôt>-<empreinte>/data`) : événements et tours dans `state/jarvis.sqlite3` (inchangé), payloads de pièces et dépôts dans `artifacts/<artifact_id>/upload.<ext>`. L'état du canal vocal est en mémoire de Core. Les fichiers de `runtime/` (`.voice_*`) ne gagnent rien. Les tests utilisent `tmp_path` et une racine isolée, jamais une base du dépôt.

---

## Propriété des fichiers par Slice

| Slice | Fichiers (création **N**, modification **M**) |
| --- | --- |
| 01 | N `docs/chat.md` ; M `docs/conversation-events.md` (paramètre `projection`, clé `attachment_count`), `docs/interaction-mode.md` (distinction), `docs/artifacts.md` (natures `upload`, `link` : contrat), `docs/boards.md` (renvoi dépôt) ; N `tests/fixtures/chat_projection/cases.json` |
| 02 | N `jarvis/domain/chat_projection.py`, `jarvis/runtime/control_center_chat_model.js`, `tests/unit/test_chat_projection.py`, `tests/unit/test_control_center_chat_model_js.py` |
| 04 | N `jarvis/domain/voice_channel.py`, `jarvis/core/voice_channel.py`, `tests/unit/test_voice_channel_domain.py`, `tests/unit/test_voice_channel_service.py`, `tests/unit/test_voice_channel_protocol.py`, `tests/unit/test_voice_channel_reporter.py` ; M `jarvis/protocol/server.py` (3 routes), `jarvis/protocol/client.py`, `jarvis/core/v2_app.py` (câblage), `jarvis/app.py` (`_voice_timeout_loop`), `jarvis/runtime/voice_v2.py` (rapport à l'entrée en `connecting`), N `jarvis/runtime/chat_relay.py` (relais `GET /api/chat/state`, `POST /api/chat/voice/disable`) ; M `jarvis/runtime/control_center.py` (préfixe gardé, montage) |
| 03 | M `jarvis/runtime/chat_relay.py` (`POST /api/chat/turns`) ; N `tests/unit/test_chat_text_ingress.py`, `tests/unit/test_chat_relay.py`, `tests/unit/test_speech_text_channel.py` ; M `jarvis/protocol/server.py` (`submit_brain_turn`), `jarvis/domain/v2.py` (`BrainTurnInput.attachments`), `jarvis/core/voice_admission.py` (métadonnée et identité), `jarvis/core/brain_service.py` (`_text_only`, `_emit_speech`), `jarvis/adapters/control_center_brain.py` (`channel`), `jarvis/runtime/control_center.py` (brief, montage du relais) |
| 05 | M `jarvis/domain/conversation_event_query.py`, `jarvis/core/conversation_event_query.py`, `jarvis/protocol/server.py` (`list_conversation_events`), `jarvis/protocol/client.py`, `jarvis/runtime/conversation_event_view.py`, `docs/conversation-events.md` (section Query) ; N `tests/unit/test_chat_projection_query.py`, `tests/integration/test_chat_projection_protocol.py` |
| 06 | N `jarvis/runtime/control_center_chat.js`, `tests/unit/test_control_center_chat_ui.py`, `tests/unit/_chat_browser.mjs`, `tests/unit/test_control_center_chat_browser.py` ; M `jarvis/runtime/control_center.html` (marqueurs, onglet, panneau, toasts), `jarvis/runtime/control_center.py` (injection) |
| 07 | N `jarvis/domain/uploads.py`, `jarvis/core/upload_service.py`, `jarvis/protocol/upload_routes.py`, `tests/unit/test_uploads_domain.py`, `tests/unit/test_upload_service.py`, `tests/unit/test_upload_protocol.py`, `tests/unit/test_chat_attachments_brain_context.py` ; M `jarvis/domain/artifacts.py` (`UPLOAD`), `jarvis/domain/brain_context.py`, `jarvis/core/brain_service.py` (construction du bloc), `jarvis/adapters/control_center_brain.py`, `jarvis/runtime/control_center.py` (brief, `artifacts_root`), `jarvis/core/session_manager.py` (`artifacts_root`), `jarvis/runtime/chat_relay.py` (`/api/chat/uploads`), `jarvis/runtime/capture_mcp.py:606`, `jarvis/runtime/control_center_workspace.js:69` (libellé), `jarvis/domain/conversation_events.py` (`attachment_count`), `jarvis/core/voice_admission.py` (attribut), `jarvis/protocol/server.py` (étape 5), `docs/artifacts.md`, `docs/conversation-events.md` |
| 07b | M `jarvis/runtime/control_center_chat.js`, `control_center_chat_model.js`, `control_center.html` (styles) ; N `tests/unit/_chat_attachments_browser.mjs`, `tests/unit/test_control_center_chat_attachments_browser.py` |
| 08 | M `jarvis/domain/artifacts.py` (`LINK`), `jarvis/domain/uploads.py`, `jarvis/core/upload_service.py`, `jarvis/protocol/upload_routes.py`, `jarvis/runtime/control_center_scene_interact.js` ou N `jarvis/runtime/control_center_board_drop.js`, `jarvis/runtime/control_center_workspace.js` (libellés), `jarvis/runtime/capture_mcp.py:606`, `docs/artifacts.md`, `docs/boards.md` ; N `tests/unit/test_board_drop.py`, `tests/unit/_board_drop_browser.mjs` |
| 09 | N `tests/integration/test_chat_end_to_end.py` (et scripts de preuve sous la tâche) |
| 10 | M `docs/chat.md` (L3), `docs/OPERATIONS.md`, `docs/SECURITY.md`, `docs/ARCHITECTURE.md`, `docs/local-data.md` |

Deux Slices ne travaillent jamais en parallèle sur le même fichier : 03, 04, 05 et 07 touchent `jarvis/protocol/server.py` et `jarvis/runtime/control_center.py` ; elles sont donc **séquentielles** dans l'ordre 04 → 03 → 05 → 07 ; 06, 07b et 08 touchent `control_center.html` et passent dans cet ordre. 02 peut tourner en parallèle de 04 : elle ne touche que des fichiers neufs.

---

## Ce qui est réutilisé

| Besoin | Réutilisé | Où |
| --- | --- | --- |
| Historique | `ConversationEventStore`, route `GET /v1/conversation-events` et son long-poll | `server.py:246`, `core/conversation_event_query.py:186-208` |
| Relais lecture | `/api/conversations/events`, `ConversationEventView` | `control_center.py:6545-6550`, `conversation_event_view.py:277-292` |
| Repli des doublons | `collapse_published_messages` / `collapseMessages` | `conversation_transcript.py:150-161`, `control_center_timeline.js:220` (lu, pas modifié) |
| Promotion des incertains | règle `_derive_state` | `brain_service.py:575-620` |
| Envoi | `POST …/brain-turns`, `BrainOrchestrator.submit`, `persist_turn` | `server.py:585-667`, `brain_service.py:658-760`, `voice_admission.py:114-152` |
| Idempotence | `turn_id` stable, source durable, `claim_backend_dispatch` | `voice_admission.py:119-166` |
| Garde navigateur | `READ_GUARDED_ROUTES`, `_loopback_refusal` | `control_center.py:300-304`, `:360-383`, `:2061-2081` |
| Arrêt vocal | `mute(VoiceStopReason.USER)`, précédent reçu Live stop | `voice_v2.py:1345`, `app.py:1835-1878` |
| Rapport vocal | `voice_runtime_report`, boucle d'une seconde | `voice_v2.py:1584`, `app.py:1767` |
| Stockage de fichiers | `ArtifactService.create`/`open_spool`/`finalize`, défenses de chemins | `core/artifact_service.py:95-210`, `docs/artifacts.md` « Payloads » |
| Lien Board | lien automatique, `artifact_link` explicite | `sqlite_board_artifact_links.py:53-70`, `docs/artifacts.md` « Board links » |
| Accès du cerveau | `--add-dir` par `_learn_sessions_root` | `control_center.py:1552-1555`, `:1805-1835` |
| Contexte de tour | `BrainContext`, `_turn_context`, `build_agent_brief` | `brain_context.py:1194`, `control_center_brain.py:101`, `control_center.py:1019` |
| Panneau | `.panel`, toasts, marqueurs d'injection | `control_center.html:95`, `:277-294`, `control_center.py:448-449` |
| Tests navigateur | Chrome headless CDP `tests/unit/_*_browser.mjs` | ex. `tests/unit/_workspace_browser.mjs` |

---

## Écarts handoff vs dépôt

1. **« Deux types seulement »** : le chat lit aussi `brain.turn.failed` (diagnostique, sans contenu) pour un statut d'échec, jamais une bulle. Sinon un tour texte échoué resterait « en attente » pour toujours.
2. **`uncertain`** : la question n'était pas posée dans le handoff ; le dépôt la tranche (promotion par message Brain de même corrélation).
3. **Pas de nouvelle route de lecture** : `02-architecture.md` laissait « adaptateur minimal filtré » ; c'est un paramètre `projection=chat` sur la route existante, qui hérite du curseur et du long-poll.
4. **Ordre des Slices** : 04 avant 03 ; 05 ne dépend plus de 03 ; 07 scindé en 07 (backend) et 07b (UI).
5. **« Voice publie son statut au Control Center »** (Slice 04 initiale) : le juge est **Core**, nourri par Voice ; le Control Center ne fait que relayer. Sans cela la garde serveur de l'envoi n'aurait pas de source.
6. **`02-architecture.md` « ne pas exposer path absolu au navigateur »** : tenu ; mais le chemin absolu est donné au **cerveau** (bloc de pièces jointes) : c'est le seul moyen attesté pour qu'un CLI Claude lise un fichier (`images=` refusé hors `speculative_analysis`).
7. **« Une pièce jointe du chat n'est pas automatiquement un dépôt sur Board »** : vrai au sens produit (pas de provenance `board_drop`, pas de lien `explicit`), mais la règle **existante** du dépôt lie toute nouvelle Artifact au Board actif (`link_to_active_board`). La pièce jointe apparaît donc dans les Artifacts du Board, marquée `chat_attachment`. Changer cette règle globale serait une refonte hors périmètre.
8. **Objet de scène pour un dépôt Board** : non réalisé (contrat de scène incompatible sans remodelage) ; ressource visible par l'inspecteur seulement.
9. **Limite 8192 caractères des événements** : une réponse Brain plus longue n'apparaît pas au chat ; atténuée (brief, état honnête), non levée.
10. **Accès `--add-dir`** : tout `<data_root>/artifacts` est accordé (pas seulement les pièces jointes), faute d'octroi par tour.
11. **Bornes de fichiers** : l'utilisateur n'a fixé aucune limite ; des bornes **techniques** configurables sont posées (64 Mio par fichier, 10 pièces par message), dites dans l'UI et dans les erreurs.
12. **Pas d'envoi de fichiers seuls** : un message doit porter du texte (`BrainTurnInput` exige un texte, `v2.py:676-677`, et le contenu d'événement utilisateur est obligatoire) ; l'UI le dit au lieu d'inventer un texte.
13. **Task Type** : levé (`waived-by-agent-0`).
14. **Cycle de vie Live de Core** (`/v1/live/sessions`) : existe mais ne couvre que GPT-Live ; non réutilisé pour le verrou.
