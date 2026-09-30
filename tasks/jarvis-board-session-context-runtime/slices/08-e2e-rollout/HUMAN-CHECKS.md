# Vérifications humaines — Boards et Sessions

Quatre vérifications, dans cet ordre. Toute la validation machine est passée
avant (voir `EVIDENCE.md`) : ici on juge ce qu'une machine ne sait pas juger
(clarté, voix réelle, sensation « Board ≠ Session »).

## Préparation (une fois)

1. Arrêter tout JARVIS en cours (fermer la fenêtre de `dev_start.py`, ou
   `taskkill /T /F /PID <pid>` sur les processus `python -m jarvis …`).
2. Dans `C:\Projects\jarvis\jarvis`, être sur la branche
   `task/jarvis-board-session-context-runtime`.
3. **Sauvegarde automatique :** au premier démarrage, la base
   `data\state\jarvis.sqlite3` (aujourd'hui schéma 2) passe au schéma 3 et une
   copie `data\state\jarvis.sqlite3.v2.bak` est écrite à côté. Pour revenir à
   `main` plus tard : arrêter JARVIS, remettre ce `.v2.bak` à la place de
   `jarvis.sqlite3` (supprimer les `-wal`/`-shm`).
4. Lancer comme d'habitude : `.\.venv\Scripts\python.exe scripts\dev_start.py`
   (voix `continuous_brain` via `.env`). Ouvrir `http://127.0.0.1:17654/`.
5. Où regarder si quelque chose cloche :
   - trace : `runtime\trace.jsonl` —
     `Get-Content runtime\trace.jsonl -Tail 300 | Select-String "core.board|core.session|board_brain|board.request|speech_withheld|notice_relayed"` ;
   - erreurs : `runtime\errors.jsonl` et le badge Erreurs du Control Center ;
   - état : `Invoke-RestMethod http://127.0.0.1:17654/api/status | Select -Expand boards`
     (Board actif, Session, agents par Board et leur état `foreground` /
     `background_running` / `suspended`).

---

## HV-BOARD-E2E-001 — Board et Session de bout en bout

1. Au premier écran, le bouton en haut à droite affiche **Board · Board
   principal**. Attendu : c'est votre état d'avant (même conversation vocale,
   même mode d'interaction).
2. Dites à JARVIS : « Retiens que sur ce Board on prépare la démo de vendredi. »
   puis ouvrez le panneau Boards : **Nouveau Board** → `Recherche` → Créer.
   Attendu : Recherche apparaît dans la liste, le Board actif ne change pas.
3. Cliquez **Recherche**, parlez-lui (« Sur ce Board on étudie les agents
   vocaux. »), puis revenez sur **Board principal** et demandez « On en était
   où ? ». Attendu : il parle de la démo de vendredi, pas des agents vocaux
   (A → B → A dans la même Session : chaque Board retrouve **sa** conversation).
4. Panneau Boards → **Nouvelle session** → confirmer. Demandez « De quoi
   parlait-on ? ». Attendu : conversation propre (il ne se souvient pas de
   l'échange précédent), mais toujours sur Board principal ; le résumé et les
   tâches du Board sont intacts (ouvrir le panneau).
5. Passez sur Recherche, choisissez le mode **Présentation**, revenez sur
   Board principal. Attendu : Board principal reprend son mode, Recherche
   garde Présentation quand on y retourne.
6. Alertes : voir HV-BOARD-ALERT-001 (même séance).

Attendu global : « Session » et « Board » se distinguent sans effort ; une
conversation ne repart à zéro que sur demande ; rien d'un Board ne fuit dans
l'autre.

En cas d'échec : `core.board.switched` doit apparaître à chaque bascule avec le
bon `board_id` ; `core.session.opened` (`origin: protocol`) à la nouvelle
session ; si un Board « se souvient » d'un autre, noter l'heure et chercher la
ligne `agent.input` du tour (champ `board_id`).

## HV-BOARDS-UI-001 — Le contrôle Boards est utilisable

1. Le bouton Boards (haut à droite) : le titre du Board actif est toujours
   lisible.
2. Créer un Board (titre vide refusé, sous le champ), basculer entre deux
   Boards, renommer l'un (crayon, Entrée).
3. Refus sûr : sur le Board **actif**, l'icône d'archivage doit être
   désactivée ; cliquer dessus explique pourquoi, rien n'est envoyé. Archiver
   un Board **inactif** : confirmation « irréversible », puis il disparaît.
4. Pendant une bascule : le bouton affiche **Bascule · N s** avec un compteur
   (≈ 4 s quand l'agent du Board doit démarrer).

Attendu : on sait toujours quel Board est actif ; chaque transition se
comprend ; pas de carte / galaxie.

En cas d'échec : console du navigateur (F12), lignes `[boards] …` ; côté
serveur `board.request.*` et `core.board.*` dans la trace.

## HV-BOARD-ALERT-001 — Alerte d'un autre Board et navigation

1. Sur **Recherche**, dites : « Lance un sous-agent en arrière-plan qui compte
   lentement jusqu'à 60, une seconde par nombre, et réponds-moi tout de
   suite. » Attendre sa réponse courte.
2. Dans les 60 s, basculer sur **Board principal** (panneau Boards) et y
   parler normalement.
3. Quand le comptage finit : **aucune voix** ne l'annonce ; une pastille
   d'alerte montre un point « satellite » et « dont N sur « Recherche » ». Le
   popover indique `Board « Recherche »` et propose d'aller sur ce Board.
4. Cliquer l'action d'aller sur Recherche : bascule normale (même compteur que
   le panneau), puis l'alerte y reste visible (marquée `Ce Board`) jusqu'à
   l'acquittement.
5. Si possible : refaire l'étape 1–2, puis **Nouvelle session**, puis fermer
   et relancer JARVIS avant la fin du sous-agent : l'alerte (ou « interrompu »,
   limite V1 : un sous-agent CLI ne survit pas au redémarrage) est toujours là,
   attribuée à Recherche.

Attendu : notification globale et attribuée ; le Board inactif ne parle
jamais ; la navigation passe par la bascule ordinaire.

En cas d'échec : `agent.subagent.finished` et `agent.unsolicited_result` doivent
porter `board_id` de Recherche et `spoken: false` ; **aucune**
`core.brain.notice_relayed` pour la conversation de Recherche pendant qu'on est
ailleurs ; une parole retenue apparaît en `core.brain.speech_withheld_inactive_board`.

## HV-BOARD-VOICE-001 — La voix pendant une bascule

1. Voix ouverte (continuous_brain). Sur **Recherche**, lancer le sous-agent de
   HV-BOARD-ALERT-001 étape 1 (60 s).
2. Pendant qu'il tourne, dites : « Bascule sur le Board principal. » Attendu :
   une phrase courte (« Passage sur « Board principal » à la fin de ta
   réponse. »), puis la voix continue **sans redémarrer** ; parlez sur Board
   principal, il répond normalement.
3. Pendant tout ce temps, Recherche ne prend jamais la parole, même quand son
   sous-agent finit (l'alerte apparaît seulement à l'écran).
4. Dites : « Reviens sur Recherche. » Attendu : il reprend le fil de
   Recherche ; il peut vous parler du résultat du comptage si vous le
   demandez.

Attendu : un seul Board parle ; le travail de fond survit ; aucune fuite de
conversation.

En cas d'échec : après chaque bascule, `voice.board.rebind_requested` puis
`voice.board.rebound` (voix) ; `board.request.deferred_applied` (bascule
demandée par le cerveau, appliquée après sa phrase) ; si deux voix se
chevauchent, noter l'heure et relever les `brain.speech`/`core.brain.*` autour.
