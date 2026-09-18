# Latence du premier son — diagnostic chiffré du 18 septembre 2026

Statut : diagnostic, aucune modification du runtime. Référence du code audité : `c4ecbf7`.
Architecture mesurée : `continuous_brain` — surface OpenAI `gpt-realtime-2.1-mini`, cerveau Claude Code CLI (`claude-opus-5`).

## Preuves et limites

Source : `runtime/trace.jsonl` (21 123 événements) et les 17 sessions de `runtime/benchmarks/voice-sessions/`.
Le budget par étape ci-dessous est corrélé événement par événement sur les sessions des **17 et 18 septembre** (n = 56 tours complets), en recoupant les traces des trois processus (voix, Control Center, Core) par horodatage et par `correlation_id`.

Deux limites. La borne de départ mesurable est `voice.brain_turn_submitted` : ce qui se passe entre la fin réelle de parole et cet instant n'est pas horodaté par tour, et la détection de fin de tour y figure comme une **constante de configuration**, pas comme une mesure. Et aucun appel au fournisseur n'a été rejoué : les chiffres sont ceux des sessions déjà enregistrées.

## Conclusion

Le premier son arrive **≈ 7,6 s** après la fin de parole en médiane, **≈ 12 s** en moyenne. Le poste dominant est le tour du cerveau lui-même (**2 741 ms médians, 6 916 ms moyens**), et à l'intérieur de ce tour, **2 337 ms s'écoulent avant même le premier bloc de réflexion** : le CLI tourne à l'effort par défaut alors que sa consigne système lui demande d'être un aiguilleur qui termine « en quelques secondes ».

Le cache de prompt Anthropic n'est **pas** en cause : il fonctionne déjà parfaitement (voir § C3). Ce n'est pas là qu'il faut chercher.

Le cerveau réflexe, lui, ne souffre ni de son modèle ni de son prompt — les deux sont déjà minimaux. Il souffre d'être **lancé trop tard** : sa génération ne démarre qu'à l'échéance de 1,2 s, et le fournisseur met encore ~1,2 s à produire le premier échantillon.

## 1. Budget de latence, étape par étape

Sessions des 17–18 septembre, n = 56 tours. Toutes les valeurs en millisecondes.

| # | Étape | médiane | moyenne | p90 | max |
|---|---|---:|---:|---:|---:|
| 0 | Détection de fin de tour (VAD, **constante**) | 1 500 | — | — | — |
| 1 | transcription → tour accepté par le cerveau | 69 | 90 | 179 | 264 |
| 2 | soumission → `agent.input` (HTTP + verrou de tour) | 7 | 1 764 | 2 640 | 23 159 |
| 3 | `agent.input` → 1er bloc de réflexion | **2 337** | 2 728 | 4 125 | 13 049 |
| 4 | réflexion → 1er bloc de texte | **1 908** | 5 614 | 17 350 | 28 329 |
| — | *(3+4 consolidé : `agent.input` → `result`)* | *2 741* | *6 916* | *20 331* | *31 309* |
| 5 | `result` → parole mise en file | 35 | 792 | 2 345 | 10 349 |
| 6 | file d'attente de parole | 1 | 1 192 | 1 | 46 840 |
| 7 | envoi → 1er PCM (la surface lit le texte) | 1 205 | 1 387 | 1 862 | 3 687 |
| | **soumission → 1er PCM (mesuré)** | **6 084** | **10 411** | **24 580** | **49 448** |
| | **fin de parole → 1er son (mesuré + VAD)** | **≈ 7 600** | **≈ 11 900** | **≈ 26 100** | — |

Répartition du médian de 7,6 s : **cerveau 36 %** (2,7 s), **VAD 20 %** (1,5 s), **restitution vocale 16 %** (1,2 s), file et transport 2 %, et le reste dans la dispersion.
Sur la **moyenne**, le cerveau seul pèse **66 %**.

L'étape 6 est saine en médiane (1 ms) : ses valeurs extrêmes viennent de `_wait_for_idle_output()` (`jarvis/runtime/speech_scheduler.py:1284`), c'est-à-dire d'une réponse précédente encore en train d'être jouée. Ce n'est pas un défaut, c'est le tour de parole.

L'étape 7 n'est pas une synthèse vocale classique : le texte du cerveau est redonné au modèle Realtime à lire mot pour mot (`VERBATIM_SPEECH_INSTRUCTION`, `jarvis/adapters/openai_realtime.py:191`). C'est un aller-retour de modèle complet, d'où les 1,2 s.

## 2. Leviers — cerveau principal

### C1. Abaisser l'effort du CLI sur le profil conversation — gain 1 à 2,5 s sur la médiane, effort : une ligne

`jarvis/runtime/claude_local.py:649-666` lance le CLI sans `--effort`. Il tourne donc au défaut (haut) sur `claude-opus-5`, avec la pensée active — les événements `system/thinking_tokens` de la trace le confirment. C'est ce que mesure l'étape 3 : **2 337 ms médians avant le premier bloc de réflexion**.

Or la consigne système de ce même agent (`claude_local.py:57-62`) dit : « Tu aiguilles, tu n'exécutes pas […] Chacun de tes tours doit donc se terminer en quelques secondes. » L'effort payé ne correspond pas au travail demandé.

Vérifié dans la référence de l'API Claude : sur Opus 5 la pensée est active par défaut et `output_config.effort` (`low` → `max`, défaut `high`) pilote la profondeur de réflexion et la dépense de jetons ; les routes conversationnelles et sensibles à la latence tiennent bien à `low`, avec `medium` comme palier intermédiaire. Le CLI expose exactement ce réglage : `--effort <low|medium|high|xhigh|max>`.

**Ne pas désactiver la pensée.** Sur Opus 5, `thinking: disabled` a deux modes de panne documentés : le modèle écrit parfois un appel d'outil dans son **texte visible** (le tour réussit, l'outil ne part jamais, aucune erreur n'est levée) et peut laisser fuir des balises `<thinking>`. Baisser l'effort en gardant la pensée active est la manœuvre correcte, et elle réduit aussi le coût.

Proposition : `--effort low` pour `execution_profile == "conversation"`, en le remontant à `medium` si la qualité d'aiguillage se dégrade. À prouver en réel sur plusieurs tours avant de figer.

### C2. Parler sur le premier bloc de texte au lieu d'attendre le `result` — gain sur la queue, pas sur la médiane

`ClaudeLocalAgent.ask()` (`jarvis/runtime/claude_local.py:773-830`) attend `event["type"] == "result"`, c'est-à-dire la **fin complète du tour**. Les événements `assistant`, qui portent le texte dès que le bloc est clos, ne servent aujourd'hui qu'à la comptabilité de `_audit_turn` (`claude_local.py:980`).

Mesure du gain réel si l'on parlait sur le premier bloc de texte (85 tours récents) :

| | valeur |
|---|---:|
| médiane | 23 ms |
| moyenne | 2 653 ms |
| tours gagnant > 500 ms | 19 / 85 (**22 %**) |
| tours gagnant > 2 s | 14 / 85 (**16 %**) |
| tours gagnant > 5 s | 10 / 85 (**12 %**) |
| maximum | 39 028 ms |

Il faut être honnête sur ce chiffre : le tour médian est un bloc de texte immédiatement suivi du `result`, donc **la médiane ne bouge presque pas**. Ce levier corrige la queue — les tours où le cerveau annonce ce qu'il lance puis continue à travailler. Sur les 85 tours, 43 émettent leur texte **avant** le premier appel d'outil : pour ceux-là, tout ce qui suit est du silence payé pour rien.

C'est aussi, littéralement, la demande « qu'il donne un peu de données pendant qu'il réfléchit ».

Pour descendre sous le bloc, jusqu'à la phrase : le CLI expose `--include-partial-messages` (« Include partial message chunks as they arrive », valable avec `--print` et `--output-format=stream-json`, tous deux déjà passés). Il devient alors possible d'émettre la première phrase complète dès qu'elle est formée.

**La chaîne d'aval est déjà prête pour du multi-morceaux**, et c'est ce qui rend ce levier réaliste : l'ordonnanceur découpe déjà la parole en spans chaînés et ordonnés (`jarvis/runtime/speech_scheduler.py:1114`, `_chain_next` en `:1166-1177`). Mais le découpeur actuel, `semantic_text_spans` (`jarvis/domain/speech_presentation.py:120-134`), ne coupe **que sur les sauts de paragraphe `\n\n`** — donc une réponse vocale normale, d'un seul paragraphe, donne un seul morceau.

Avertissement, parce que la tentation est naturelle : **découper par phrase sans streamer côté cerveau ne gagne rien et coûte.** Si le texte est déjà complet, le premier morceau part au même instant qu'aujourd'hui ; les suivants attendent que le précédent soit joué **et drainé**, ce qui ajoute ~200 ms de tampon périphérique par frontière (voir § 4 bis). Le découpage par phrase ne paie **que** couplé au streaming amont.

Note de conception : le canal de progression précoce est entièrement câblé — `mark()` en `jarvis/core/brain_service.py:1392` sur `ACCEPTED`, `measure()` en `:1422-1431` sur le premier `PROGRESS` — et la métrique `backend_first_progress_ms` (`jarvis/core/latency.py:18`, `jarvis/runtime/voice_metrics.py:57`) **n'a jamais été renseignée une seule fois** sur 17 sessions (`count = 0`). La raison est en amont : le backend n'émet la parole qu'après l'aller-retour HTTP complet (`jarvis/adapters/control_center_brain.py:266`, puis un unique `BrainEvent(SPEECH)` en `:293-309`), et les seuls `PROGRESS` existants sont des **phases sans texte** (`jarvis/runtime/back_brain_worker.py:235-239`). Le tuyau est posé ; il n'y a rien dedans.

### C3. Le cache fonctionne — c'est la croissance de la session qu'il faut borner

À vérifier avant toute autre hypothèse : **le cache de prompt Anthropic marche déjà parfaitement**. Sur tous les tours du 18 septembre, `input_tokens = 2` et tout le reste passe en `cache_read_input_tokens`. Le préfixe est stable d'un tour à l'autre, le prompt système (`--append-system-prompt`, 7 476 caractères ≈ 2 076 jetons, `claude_local.py:57-140`) est figé et le contexte volatil est bien placé **après** lui, en fin de message (`build_agent_brief`, `jarvis/runtime/control_center.py:354-391`, borné à 18 lignes de travail × 240 caractères par `jarvis/runtime/work_brief.py:23-26`). Il n'y a rien à corriger de ce côté, et le contexte injecté par tour n'est pas le problème.

Le problème est ailleurs : la session `--resume` (`claude_local.py:605`) grossit sans borne. Mesuré sur une seule session du 18/09 :

```
10:47:23  cache_read=  15 329   out=  60   dur=  2 324 ms
13:34:09  cache_read=  41 075   out=  12   dur=  1 483 ms
14:19:56  cache_read= 103 219   out=  12   dur=  1 649 ms
14:26:26  cache_read= 120 194   out= 287   dur=  5 737 ms
14:05:21  cache_read= 303 543   out= 979   dur= 13 752 ms
```

Sur les tours triviaux (`out = 12`, la réponse convenue de silence), la durée glisse de 1 483 ms à 41 k jetons lus à 2 129 ms à 112 k : **≈ 0,5 s pour 70 k jetons de cache**. Réel, mais second ordre.

Second constat du même relevé : la durée suit surtout les **jetons produits** (60 → 2,3 s ; 382 → 5,6 s ; 1 164 → 19,6 s ; 1 897 → 29,9 s), ce qui renvoie à C1 et C2.

Levier : `--autocompact <tokens>` (flag CLI), ou repartir d'une conversation neuve périodiquement. Et le premier tour d'une session paie 18 826 jetons d'écriture de cache — un pré-chauffage au démarrage de JARVIS effacerait ce coût du premier échange.

### C4. Le verrou de tour

`claude_local.py:786` : `ask()` tient `self._ask_lock` pendant toute l'attente. L'étape 2 le montre — médiane 7 ms, mais **moyenne 1 764 ms et p90 2 640 ms** : c'est l'attente derrière le tour précédent. Le problème était déjà relevé dans l'audit du 11 septembre ; il n'a pas disparu. Il est atténué, pas résolu, par la règle de délégation du prompt système.

## 3. Leviers — cerveau réflexe

Précision de vocabulaire, parce que le dépôt porte deux choses sous le nom « front brain » : le cerveau réflexe **n'est pas** `jarvis/adapters/openai_front_brain.py` (analyseur Luna `gpt-5.6-luna`, qui produit des indications JSON et ne parle jamais). Le réflexe est un `response.create` dédié envoyé sur la **session Realtime déjà ouverte** (`jarvis/adapters/openai_realtime.py:678-709`).

**Ce qui est déjà optimal, et qu'il ne faut pas toucher :**

- Le modèle est `gpt-realtime-2.1-mini` (`jarvis/v2_config.py:55`), le plus rapide de la gamme, sur un websocket déjà connecté — aucune poignée de main, aucun second modèle, aucune clé séparée.
- Le prompt est minimal et auto-contenu : ~1 400 à 1 900 caractères (≈ 400-520 jetons), soit persona + consigne + transcription (`REFLEX_INSTRUCTION`, `openai_realtime.py:162-175`). **Aucun historique, aucune liste de tâches, aucun outil.** Rien à alléger.
- La sortie est `output_modalities: ["audio"]` : le modèle produit le PCM lui-même, sans étape de synthèse vocale séparée, et chaque `response.output_audio.delta` est joué dès réception (`jarvis/runtime/realtime_audio.py:2648`). Déjà streamé de bout en bout.

### R1. Lancer la génération tôt, ne décider qu'à l'échéance — gain ≈ 1,2 s sur le poste le plus visible

C'est le levier numéro un du réflexe. Aujourd'hui la séquence est strictement sérielle :

1. soumission du tour → armement du candidat, `due = now + 1 200 ms` (`jarvis/v2_config.py:174`, `jarvis/runtime/speech_scheduler.py:442`) ;
2. à l'échéance seulement, `await self.session.speak_reflex(...)` (`speech_scheduler.py:1244`) ;
3. puis **encore ~1 205 ms** au fournisseur pour le premier échantillon (médiane mesurée de l'étape 7, même chemin `response.create`).

Premier son réflexe ≈ **2,4 s** après la soumission, soit ≈ 3,9 s après la fin de parole. Le réflexe est censé couvrir le silence ; il arrive lui-même en retard.

Or la lecture est **déjà** protégée indépendamment de la génération, et c'est ce qui rend le correctif sûr :

- `OutputAdmission` ne tranche qu'à la frontière de l'écriture native (`jarvis/runtime/output_admission.py:41-56`) ; `invalidate()` réussit tant qu'aucune écriture n'a commencé ;
- `_play_audio` refuse un `INVALIDATED` avant de jouer quoi que ce soit (`realtime_audio.py:2621`, `2653-2658`) ;
- `cancel_pending_output` sait annuler une réponse réservée côté fournisseur (`openai_realtime.py:733-740`) ;
- `_reflex_cancelled` tient déjà la trace des sorties annulées (`speech_scheduler.py:495-500`).

Autrement dit : **rien n'oblige la génération à attendre l'échéance ; seule la lecture doit l'attendre.** Émettre le `response.create` dès la soumission du tour et n'ouvrir l'admission qu'à 1 200 ms ramène le premier son réflexe de ≈ 2,4 s à ≈ 1,2 s. Le coût est un `response.create` jeté quand le cerveau répond vite — exactement ce que la machinerie d'annulation existante sait déjà faire.

### R2. Borner la sortie du réflexe

Le `response.create` du réflexe (`openai_realtime.py:696-705`) ne porte **ni `max_output_tokens` ni `temperature`**. La seule contrainte de longueur est textuelle — « une phrase naturelle de trois à dix mots » (`openai_realtime.py:166`). Un réflexe bavard n'est coupé par rien, et il occupe alors le canal audio que la vraie réponse devra reprendre.

Attention en appliquant : sur l'API Realtime, la borne compte aussi les jetons audio ; trop basse, elle tronque au milieu d'un mot. La valeur doit être calibrée en réel, pas devinée.

### R3. La fenêtre d'utilité est plus courte que le tour du cerveau

`REFLEX_GRACE_S = 2.5` (`speech_scheduler.py:210`) : la fenêtre utile est `[1,2 s ; 3,7 s]` après la soumission, puis `_expire_reflex` invalide avec la raison `too_late` (`speech_scheduler.py:1280`). Or le tour du cerveau dure 2,7 s en médiane et **6,9 s en moyenne**. La fenêtre rate structurellement les tours longs — précisément ceux où le réflexe est le plus utile.

Relevé des décisions du 18/09 (94 décisions) : **17 `stale`**, 9 `user_speaking`, 6 `useful_content_ready`, 3 `answer_may_arrive_quickly`, 2 `acknowledgement_only`, pour seulement **6 `preamble`** et 2 `speak`.

Note : les 49 décisions `work_unconfirmed` du même jour sont **antérieures** au correctif `30549b5` (« parler sur le silence du cerveau, plutôt que sur un travail déclaré »), qui a remis `reflex_requires_confirmed_work()` à `False` (`jarvis/v2_config.py:227-236`). Cette porte-là est refermée ; `stale` est celle qui reste ouverte.

## 4. Levier en amont, commun aux deux — le moins cher de tous

`silence_duration_ms = 1 500` (`jarvis/adapters/openai_realtime.py:139`, repris dans `runtime/control-center-settings.json`). C'est **1,5 s payé avant que quoi que ce soit ne démarre**, à chaque tour, et c'est 20 % du budget médian. Le commentaire du code explique le choix : à 800 ms, une pause de réflexion se faisait prendre pour une fin de phrase et le reste de l'explication était perdu. Le compromis est donc assumé, et le baisser à l'aveugle rouvrirait ce défaut.

Mais `semantic_vad` est **déjà implémenté et sélectionnable** (`openai_realtime.py:216-222`), et la docstring de `build_turn_detection` décrit exactement la sortie de ce compromis : il « juge la fin de phrase sur son sens plutôt que sur une durée de silence : il répond vite à une phrase finie et attend pendant une hésitation ». Rapide **et** patient, au lieu d'arbitrer entre les deux avec un chronomètre.

Coût : zéro ligne de code. Un réglage, `vad_type: "semantic_vad"`, avec `vad_eagerness` déjà présent dans les réglages du Control Center.

## 4 bis. Le tampon du périphérique de sortie — ne concerne pas le premier son

À noter pour ne pas s'y tromper : les ~200 ms constants de `device_drain_ms` (mesurés sur toutes les sessions, min 189 / max 200) ne sont **pas** une constante du dépôt. C'est la latence native du flux de sortie, ouvert sans paramètre `latency=` en `jarvis/runtime/realtime_audio.py:453`, donc au défaut `sounddevice` `latency='high'` — ≈ 0,2 s sous Windows. Elle est consommée par le `stream.stop()` bloquant de `_checked_drain` (`realtime_audio.py:1011`), et bornée à 250 ms par `device_wait_s` (`realtime_audio.py:293`) : la marge n'est que de 50 ms avant qu'un périphérique un peu plus lent ne bascule en `audio_drain_unknown`.

Ce drain ne retarde pas le premier son d'un tour, mais il s'ajoute une fois par énoncé à l'attente de l'énoncé **suivant** (`speech_scheduler.py:1190` → `:1301-1333`). Il pèse donc sur les réponses en plusieurs morceaux, pas sur la latence perçue à l'ouverture. Basse priorité — mentionné pour que le chiffre ne soit pas relu comme un délai fixe qu'on aurait posé.

## 5. Classement

| # | Levier | Portée | Gain estimé sur le 1er son | Effort | Emplacement |
|---|---|---|---|---|---|
| 1 | `--effort low\|medium` | cerveau | **1 à 2,5 s** (médiane) | 1 ligne | `jarvis/runtime/claude_local.py:649-666` |
| 2 | Génération anticipée du réflexe | réflexe | **≈ 1,2 s** (quand le réflexe parle) | moyen | `jarvis/runtime/speech_scheduler.py:1237-1245` |
| 3 | `semantic_vad` | amont | **≈ 0,5 à 1 s** (médiane) | réglage | `jarvis/adapters/openai_realtime.py:139` / `216-222` |
| 4 | Parler sur le 1er bloc de texte | cerveau | 0 médian, **2,6 s moyens**, 12 % des tours > 5 s | moyen | `jarvis/runtime/claude_local.py:773-830` |
| 5 | Élargir `REFLEX_GRACE_S` | réflexe | débloque les 18 % de candidats `stale` | 1 ligne | `jarvis/runtime/speech_scheduler.py:210` |

Les leviers 1, 2 et 3 sont indépendants et cumulables : appliqués ensemble, ils visent **≈ 7,6 s → ≈ 4 s** sur le médian, et le premier son réflexe à ≈ 2 s après la fin de parole.

## 6. Pourquoi rien n'a été appliqué ici

Les cinq leviers touchent tous le comportement vocal en direct : effort du modèle, ordonnancement de la parole, fermeture du tour de l'utilisateur. Aucun ne se prouve par un test unitaire à faux websocket — il faut plusieurs tours contre le vrai fournisseur pour vérifier qu'on n'a pas échangé de la latence contre des tours coupés, des préambules bavards ou un aiguillage dégradé.

Ce rapport s'arrête donc au chiffre et à l'emplacement. L'ordre d'application recommandé est celui du classement : le levier 1 seul est mesurable en un échange, et c'est aussi le plus rentable.
