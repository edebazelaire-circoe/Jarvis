# Slice 06 — Onglet bas droit, panneau et dialogue texte

## Goal
Livrer le premier parcours Chat complet sans pièces jointes, sobre et utilisable au clavier.

## Context
Le Control Center possède déjà dock, `.panel`, z-index, scène, thèmes Cosmos et chronologie plein écran ; pas de refonte parallèle.

## Canonical Concepts
- Sources : `../../docs/00-overview.md`, `../../docs/01-decision-log.md`, `../../docs/02-architecture.md`, `../../docs/05-documentation-levels.md`.
- Contrats du dépôt : `docs/conversation-events.md`, `docs/boards.md`, `docs/session-context.md`, `docs/interaction-mode.md`, `docs/artifacts.md`, `CLAUDE.md`, selon le domaine touché. Lire les **contrats courants**, ne pas copier leur texte.

## Scope
### In Scope
Livrer le premier parcours Chat complet sans pièces jointes, sobre et utilisable au clavier. Limiter les changements aux pièces nécessaires, avec tests ciblés.

### Out of Scope
- Un second transcript/pipeline Brain, la présentation/Remotion, le wake word et les refontes globales non justifiées.
- Tout redémarrage ou arrêt du Jarvis de l'utilisateur sans accord explicite.

## Dependencies
- `04-voice-chat-channel-state`
- `05-chat-read-sync-relay`

## Implementation Steps
1. Ajouter bouton Chat en bas à droite et drawer latéral horizontal compatible dock/scene, sans casser les overlays existants.
2. Rendre bulles Utilisateur et Brain uniquement, lecture vocale en direct, scroll conservé, reprise persistée, statut attente/erreur clairement distinct d'un message.
3. Saisie multiligne, envoyer Enter et Shift+Enter, bouton envoyer, focus, notification si Voice actif ; bouton « Passer au chat » avec transition et grille désactivée.
4. Relier submit exclusivement à Slice 03 et flux à Slice 05 ; ne jamais écrire un message définitif avant admission confirmée ; éviter double submit et doublons événements.
5. Tester desktop/écrans étroits, clavier/lecteur écran, JS pur si utile, navigateur automatisé, emplacement lorsque Studio/Board/Live ouvert.

## Files Likely Touched
Points de départ **à vérifier au HEAD**, pas une liste exclusive :
- `jarvis/runtime/control_center.html`
- `jarvis/runtime/control_center_live.js`
- `jarvis/runtime/control_center_timeline.js`
- `tests/unit/test_control_center_timeline_js.py`

## Architecture Constraints
- Brain et conversation sont ceux du binding Session+Board actif ; événements canoniques seuls pour Chat, jamais le journal diagnostique.
- Entrée texte sans passerelle Voice ; Voice ne possède pas la durée de vie du Brain. Ne pas fonder la sûreté sur un verrou visuel seul.
- Codes d'erreur stables, droits et racine data isolée ; migration SQLite versionnée si indispensable ; aucune fuite de prompts, sous-agents, données de fichiers ou traces privées.
- Avant code, exécuter `/caveman` et `/coding-guideline`.
- Frontend : exécuter `/impeccable`, affecter un agent Claude si cette règle est supportée par le host.

## Automated Validation
- `qa-verification` systématique.
- `code-review` systématique.
- `runtime-validation` sur composant/instance isolée si changement de comportement ou UX.
- Tests ciblés et cas adverses : Un utilisateur peut uniquement utiliser Jarvis au clavier sur la même Session.
- Exécuter en worktree/sandbox avec identifiants, ports et data root isolés, noter commandes et SHA ; pas de prétention de tests exécutés à la création.
- PM tranche sur les findings. Une régression issue de cette Slice bloque approbation et ne peut être placée dans `Issues/`.

## Acceptance Criteria
- Un utilisateur peut uniquement utiliser Jarvis au clavier sur la même Session.
- Voice actif : chat lisible, input inerte et message explicatif, action de bascule.
- Compatibilité visuelle/focus/z-index prouvée avec menus et scène existants.

## Documentation Updates
- Mettre à jour contrats canoniques des concepts réellement changés ; tester la conformité quand un L2/L3 est concerné.
- Consigner preuves dans le journal d'implémentation et liens vers QA ; mettre à jour les niveaux concernés dans `../../docs/05-documentation-levels.md` sans déclarer prématurément L3.

## Handoff Notes
- Task Type prévu : **à résoudre par PM** dans vocabulaire Workspace courant (`metadata.json` n'invente aucun type).
- Human checks sont séparés dans `human-validation.json` ; avant eux, escalader la validation automatique au maximum raisonnable.
- - Valider ergonomie du panneau bas droite, bulles, focus, menus et accès au transcript détaillé sur l'écran habituel.

## Contrat Slice 00 (agent 0, 2026-10-14)

**Dépendances révisées :** 03, 04, 05. **Palier QA :** standard (`qa-verification`, `code-review`, `runtime-validation` avec captures desktop et étroites ; `/impeccable` avant code). Work Agent Claude.

Source : `../../docs/06-resolved-architecture.md`, D-UI et D-PROJ « Lecture live ».

**Correction des fichiers pressentis :** `control_center_timeline.js` et `tests/unit/test_control_center_timeline_js.py` **ne sont pas** des cibles (branche concurrente `task/transcription-tab-live-refresh` sur `control_center_timeline.js` et `test_control_center_timeline_ui.py`).

**Fichiers :**
- N `jarvis/runtime/control_center_chat.js` : vue (onglet, panneau, liste, composer, bascule), lecture par `GET /api/chat/state` (1 s panneau ouvert et onglet visible, sinon rien) et `GET /api/conversations/events?projection=chat` (hydratation puis long-poll 25 s, une attente par profil via Web Locks `jarvis.chat.<conversation_id>`, suiveurs `wait_ms=0` toutes les 5 s, solo sans Web Locks), envoi `POST /api/chat/turns` (UUID v4 par message, réutilisé en reprise ; 504 → reprise avec le même id), bascule `POST /api/chat/voice/disable`. Modèle : `control_center_chat_model.js` (02).
- M `jarvis/runtime/control_center.html` : marqueurs `/*__CONTROL_CENTER_CHAT_MODEL_JS__*/` et `/*__CONTROL_CENTER_CHAT_JS__*/` ; onglet bas-droite ; `<section class="panel chat-panel" id="chatPanel">` sur `.panel` (`:95`) ; `.toasts` remontées au-dessus de l'onglet (`:277`), décalage panneau existant (`:294`) conservé ; un seul panneau latéral ouvert à la fois.
- M `jarvis/runtime/control_center.py` : injection des deux fichiers comme `LIVE_SCRIPT_MARKER` (`:448-449`, `:2244`).

**Comportements exigés :** bulles en `textContent` ; Entrée envoie, Maj+Entrée saute ; double envoi impossible ; état d'attente local (pas une bulle) jusqu'au `user.transcript.accepted` de même corrélation ; après 120 s sans réponse, phrase honnête + lien chronologie ; voix active → composer `aria-disabled`, message « Désactivez le vocal pour écrire », bouton **Passer au chat** ; `switching` → « Arrêt du vocal… » ; échec/expiration → message + « Réessayer » ; 409 `chat_input_locked` reçu → retour en lecture seule ; 409 `chat_conversation_not_foreground` → relecture de l'état et réhydratation ; changement de Board → modèle remis à zéro et réhydraté ; lien « Voir la chronologie complète » (`#openTimeline`).

**Tests :** `tests/unit/test_control_center_chat_ui.py` (contrat de page : marqueurs remplacés, ids, rôles ARIA, aucune occurrence de `/api/agent/ask` ni `/api/agent/send` dans `control_center_chat.js`, aucun `innerHTML` alimenté par un contenu d'événement) ; `tests/unit/_chat_browser.mjs` + `tests/unit/test_control_center_chat_browser.py` (Chrome headless CDP, serveur factice) : `opens_bottom_right_no_overlap_with_dock_and_toasts`, `keyboard_enter_shift_enter_tab_order`, `locked_when_voice_active_and_explains`, `switch_to_chat_unlocks_after_ack`, `switch_failure_stays_locked`, `server_409_overrides_ui`, `board_switch_rescopes`, `retry_reuses_client_request_id`, `narrow_viewport_480px`, `reduced_motion`. Régressions : tests de page existants (`test_control_center_mvp.py`, `test_control_center_quality.py`, `test_boards_hud_browser.py`, `test_workspace_manager_browser.py`).

**Acceptation :** parcours complet au clavier sans voix sur la même Session ; voix active : lecture à jour, saisie inerte expliquée, bascule ; captures datées (desktop, 480 px de haut, Studio/Board ouverts) jointes au LOG.

**Ne pas toucher :** `control_center_timeline.js`, `control_center_live.js` (lecture seule si besoin), routes serveur (sauf injection).
