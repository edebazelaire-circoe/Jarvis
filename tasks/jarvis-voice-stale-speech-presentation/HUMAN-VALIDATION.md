# Validation humaine — parole périmée : fin de parole Live et présentation revalidée (HV-VOICE-STALE-02 … 06)

Séance unique, **dans l'ordre**, en voix réelle (micro et haut-parleurs du
portable, français). Elle regroupe les contrôles humains des Slices 02 à 06.
Elle ne remplace aucune QA machine (toutes passées, voir `LOG.md`) : elle
vérifie ce qu'aucun test synthétique ne peut dire — le vrai GPT-Live, le vrai
cerveau, la vraie oreille.

**Règle d'enregistrement.** Pour chaque point, noter **séparément** :

- **Mesuré** — ce que dit l'outil de mesure (section 7), la chronologie **CNV**
  ou `runtime/trace.jsonl` : nombres, raisons, états. Recopier tel quel.
- **Ressenti** — ce que vous avez entendu et éprouvé, en vos mots.
- **Verdict** — OK / KO / À revoir, avec la cause précise d'un KO (heure,
  phrase, ligne de journal).

Un ressenti positif ne vaut pas un mesuré négatif, et inversement : les deux
colonnes restent distinctes. Un ressenti ne remplace jamais une QA machine en
échec.

Durée estimée : 60 à 75 minutes, mesure comprise.

---

## 0. Préconditions (une fois)

1. Branche de tâche `task/jarvis-voice-stale-speech-presentation` à jour dans
   `C:\Projects\jarvis\jarvis` ; Core, Voice et Control Center lancés
   normalement.
2. **Noter l'heure de début de séance** (heure de Paris ; en septembre-octobre,
   UTC = Paris − 2 h). Toutes les fenêtres de mesure sont en UTC.
3. Ouvrir la chronologie **CNV** du dock (mode **Tout**) : elle montre les
   paroles, les points « Parole retenue pour le cerveau », « L'utilisateur
   prend la parole (file gelée) » et « File dégelée »
   (`docs/OPERATIONS.md`, « Chronologie de conversation (CNV) »).
   **Remises au cerveau** : le fait « remis au cerveau »
   (`brain.presentation.handed`) n'existe que dans `runtime/trace.jsonl`, pas
   dans la chronologie. On le lit dans CNV par ses deux bouts : le point
   « Parole retenue pour le cerveau », puis la clôture de cette parole, dont
   le statut dit le verdict — « redit autrement » (le cerveau l'a réémise ;
   le détail donne « Redite par la parole » et l'identifiant de la nouvelle)
   ou « non redit » ; « expiré » au bout de 120 s sans verdict.
4. **Choisir la surface.** Control Center → réglages → onglet **Voix** →
   catégorie **Architecture** (libellés lus dans le code :
   `voice_settings_schema.py`, `voice_capabilities.py`,
   `control_center.html`) :
   - **Live** (GPT-Live) : liste **« Architecture vocale »** → **Duplex** ;
     « Conversation » = `openai / gpt-live-1` (seul modèle Duplex) ; garder
     cochée **« Déléguer au cerveau (outils et sous-agents) »**, sinon les
     tours ne passent pas par le cerveau Claude et ni la présentation
     revalidée ni les sous-agents ne sont exercés.
   - **Realtime** : bouton **« Revenir au mode continu avec le cerveau
     Claude »** (sous la liste), puis Enregistrer. C'est le mode de
     compatibilité : sous **« Compatibilité et invariants avancés »**,
     « Mode vocal historique » = « Conversation continue (jusqu'à F9) »
     (`continuous_brain`) et « Pile vocale de compatibilité » = OpenAI
     Realtime (modèle `gpt-realtime*`). Ne pas choisir « Simple » : cette
     architecture répond sans le cerveau Claude (l'écran le dit).
   - Un changement de réglage **ne remplace pas une session voix active** : il
     prend effet au prochain démarrage de Voice (relancer Voice).
   - Contrôle : l'outil de mesure classe chaque parole par surface d'après son
     identifiant de corrélation (`live:` / `realtime:`). Si la ligne de la
     surface attendue est vide dans le rapport, la séance n'a pas tourné sur la
     bonne surface.
5. Bare Hands **allumé** avant le démarrage du cerveau (outils
   `jarvis-barehands` montés) pour la calibration de la section 3.
6. **Vérifier que la trace s'écrit.** `runtime/trace.jsonl` sert à compter
   `speech_output_stalled` ; sa dernière écriture connue date du 25/09 alors
   que Jarvis a tourné le 28/09 (la trace allait donc ailleurs, ou n'était
   pas écrite). Après le démarrage et une première phrase, dans
   `C:\Projects\jarvis\jarvis` (PowerShell) :
   `(Get-Item runtime\trace.jsonl).LastWriteTime` doit être l'heure
   actuelle, et `Get-Content runtime\trace.jsonl -Tail 1` une ligne de la
   minute. Sinon, la trace est dans le dossier désigné par
   `JARVIS_RUNTIME_DIR` (fichier `.env` ou environnement du lanceur) : donner
   ce chemin à `--trace` en section 7. Sans trace qui couvre la séance,
   l'outil affiche `speech_output_stalled` « non mesuré » (jamais 0).

Commencer sur **Live**. La section 4 (b) se refait sur **Realtime**.

---

## 1. HV-VOICE-STALE-02 — Fin de parole Live par preuve locale (Live)

1. Enchaîner **5 demandes courtes**, en attendant chaque réponse : « quelle
   heure est-il ? », « quel jour sommes-nous ? », « combien font sept fois
   huit ? », « donne-moi un synonyme de rapide », « merci, c'est tout ».
2. Puis une demande à **réponse longue** (« explique en quatre phrases comment
   marche un arc-en-ciel ») et écouter les pauses entre ses phrases.

**Attendu mesuré** : aucune pause de ~30 s entre deux réponses ; paroles Live
`completed` avec `completion_basis=local_quiescence` ; libération p95 < 1 s ;
aucun `speech_output_stalled` ; aucun `delivery_not_complete` à ~30 s.

**À surveiller (limite S02)** : la bouche conclut une parole Live après
**500 ms** de silence du haut-parleur (`LIVE_COMPLETION_GRACE_MS`). Si une
réponse longue marque des pauses **plus longues que 500 ms** entre ses phrases,
la bouche peut la croire finie : la parole suivante part plus tôt. Noter tout
chevauchement ou enchaînement trop serré, avec l'heure.

**Après la séance, lire les pauses** (outil, section 7, ligne `live:` →
« pauses entre phrases ») : nombre de pauses, p50 / p95 / max en ms, et le
nombre de paroles dont la plus longue pause atteint **0,8 × la grâce**
(≥ 400 ms). Recopier dans « Mesuré ». Si le p95 approche 500 ms ou si
plusieurs paroles sont proches de la grâce, noter « grâce à relever ». Une
pause plus longue que la grâce ne se voit pas comme pause (elle termine la
parole) : seul le ressenti ci-dessus la révèle.

| | |
|---|---|
| Mesuré | |
| Ressenti | Jarvis répond au rythme de la conversation, sans couper ni chevaucher ses propres phrases ? |
| Verdict | |

---

## 2. HV-VOICE-STALE-04 — Présentation revalidée (Live)

### 2.1 Décision à confirmer d'abord

La Décision 48 **amende** la décision de l'utilisateur du 19/09/2026.

- **Décision du 19/09/2026** (vos mots,
  `docs/fixes/stale-answer-carried-over/resolution-report.md`) : « Une réponse
  sans retard faut qu'elle soit dite si c'est cohérent avec le contexte […] il
  manque vachement de gestion de contexte entre ce qui doit être dit, ce qui va
  être dit. […] normalement le brain est censé être capable de faire cette
  distinction ».
- **Décision 48** (`docs/handoff-realtime-brain/docs/01-decision-log.md`,
  « Truth survives, the formulation waits for the brain ») : « *a result can
  stay true forever without the sentence prepared to announce it staying
  speakable forever.* » Une formulation durable d'une intention passée, pas
  encore commencée, est **retenue** (`held_for_brain`) ; elle n'est dite que si
  le cerveau la réémet pour l'intention courante (reformulée), sinon elle est
  close `not_revalidated` à la fin du tour réussi suivant ; filet 120 s. La
  pertinence reste jugée par le cerveau, jamais par une règle d'âge ; la vérité
  (résultats, faits publics, travaux) n'est jamais touchée ; aucun job ni
  sous-agent n'est annulé.

En clair : la cohérence reste jugée par le cerveau ; ce qui change, c'est que
**pendant** ce jugement la vieille formulation attend au lieu d'être servie en
premier.

| | |
|---|---|
| Décision 48 confirmée ? | Oui / Non (et pourquoi) |

### 2.2 Test réel

1. Demander quelque chose qui prend quelques secondes (« cherche la météo de
   demain à Lyon »).
2. **Pendant qu'il prépare**, le relancer ou le contredire : « non, plutôt
   Marseille », puis une autre fois « t'as rien relancé ».

**Attendu mesuré** : la première phrase entendue répond à la relance ; aucune
phrase rédigée avant la relance n'est dite telle quelle. Journal / CNV :
« Parole retenue pour le cerveau » (`mouth.speech.held`) puis la clôture
« redit autrement » (`revalidated_as`) ou « non redit » (`not_revalidated`) ; outil : « Paroles d'une intention
dépassée démarrées » = 0 et « retenue→démarrée » = 0.

**À surveiller (limite S04)** : un **refus de délégation** local d'une
intention passée (parole du contrôleur, inconnue de Core) n'est jamais remis au
cerveau : il reste retenu puis expire au bout de **120 s**
(`held_for_brain_timeout`, trace `voice.speech.error_withheld`). Noter s'il
survient.

| | |
|---|---|
| Mesuré | |
| Ressenti | Plus de « métro de retard » ? Une information utile encore vraie est-elle redite, reformulée ? |
| Verdict | |

---

## 3. HV-VOICE-STALE-03 — Relais spontanés typés (Live, calibration Bare Hands)

1. Lancer une calibration Bare Hands et **terminer deux exercices d'affilée**.
2. Écouter les annonces entre les exercices.

**Attendu mesuré** : « Tes résultats viennent d'arriver » dit **au plus une
fois** par exercice, jamais après l'analyse correspondante ; aucun accusé d'un
exercice précédent dit plus tard ; outil : « Relais sans genre / transitoires
sans TTL » = 0 (l'accusé est un `ack` à TTL 15 s, clé `calibration:<séance>:<révision>`).

| | |
|---|---|
| Mesuré | |
| Ressenti | Les annonces collent-elles à l'exercice en cours ? |
| Verdict | |

---

## 4. HV-VOICE-STALE-05 — Interruption unifiée

### (a) Nouvelle question — Live

1. Poser une question à réponse longue ; **couper Jarvis au milieu d'une
   phrase** alors qu'il a encore des choses à dire, avec une **nouvelle
   question**.

**Attendu mesuré** : la réponse porte sur la nouvelle question ; CNV : « file
gelée » puis « File dégelée » (raison `addressed`) ; aucun sous-agent ni job
annulé.

**Limite connue sur Live** (Issue `Issues/live-barge-in-mutes-incarnation.md`) :
après un barge-in, GPT-Live **reste muet jusqu'à la fin de l'incarnation** de la
session. Sur Live, il est donc attendu que Jarvis se taise après la coupure :
noter combien de temps (outil : « Live après barge-in … prochaine parole
entendue »). Les paroles dispatchées pendant ce mutisme finissent `unconfirmed`.

### (b) Toux / aparté — **Realtime** (ne peut pas passer sur Live)

Repasser sur **Realtime** (section 0.4, relancer Voice).

1. Poser une question à réponse longue ; couper Jarvis en **toussant**.
2. Recommencer ; couper Jarvis en **parlant à quelqu'un d'autre** (phrase
   longue, à la troisième personne).

**Attendu mesuré** : Jarvis **reprend** ce qu'il avait à dire (CNV : « File
dégelée », raison `noise` ou `unaddressed`) ; aucun sous-agent ni job annulé.

**À surveiller (limite S05)** : une **phrase courte (≤ 8 mots)** dite à
quelqu'un d'autre pendant une conversation engagée est classée **adressée**
(`realtime_audio.py`, `classify` : question, relance courte ou phrase ≤ 8 mots
⇒ adressé). Jarvis ne reprend alors pas simplement : le cerveau décide
(réponse, ou rien). Ce n'est pas un KO de la Slice 05 ; le noter.

| | (a) Live | (b) Realtime |
|---|---|---|
| Mesuré | | |
| Ressenti | La coupure est-elle respectée ? | Reprend-il ce qu'il avait à dire ? |
| Verdict | | |

---

## 5. HV-VOICE-STALE-06 — Séance complète (Live, puis mesure)

Revenir sur **Live**. Noter l'heure de début de cette partie.

1. **Calibration avec interruptions** (reproduire la scène du 28/09) :
   calibration Bare Hands ; pendant une annonce, **relancer** (« recommence
   l'exercice ») ; **contester** un résultat (« non, c'était pas un clic ») ;
   **couper** Jarvis pendant une annonce.
2. **Conversation libre** : une question simple ; une demande qui lance un
   **sous-agent d'arrière-plan** (« lance une recherche de fond sur l'histoire
   du métro de Paris et résume-la-moi ») ; **interrompre** Jarvis pendant qu'il dit le résumé.
3. Noter l'heure de fin, puis lancer la mesure (section 7).

**Attendu mesuré** : toutes les cibles du tableau de la section 6 atteintes,
ou l'écart expliqué ; la comparaison avec la ligne de base montre la
disparition des `delivery_not_complete` à ~30 s sur Live.

| | |
|---|---|
| Mesuré | tableau de l'outil (copier la section « Cibles ») |
| Ressenti | |
| Verdict final | |

---

## 6. Cibles (Slice 06) et ligne de base

Ligne de base mesurée par l'outil sur le journal Core copié sans son WAL
(`LOG.md`, Slice 06 partie A) :

| Métrique | Cible | 18–21/09 | 28/09 12:54–12:59Z |
|---|---|---|---|
| Libération bouche Live après quiescence, p95 | < 1 s | n/a (0 Live `completed`) | n/a (0 Live `completed`) |
| `speech_output_stalled` sur Live (trace) | 0 | 14 | non mesuré (trace absente) |
| Live `delivery_not_complete` à ~30 s | 0 | 32 | 8 |
| Paroles d'une intention dépassée démarrées sans réémission | 0 | 31 | 5 |
| Paroles retenues pour le cerveau puis démarrées | 0 | n/a (pas de retenue avant S04) | n/a |
| Attente en file de l'intention courante au-delà de la parole en cours, p95 | < 2 s | 4,3 s | 0,9 s |
| Relais sans genre / transitoires sans TTL | 0 | 23 | 8 |

---

## 7. Mesure après la séance

Depuis `C:\Projects\jarvis\jarvis` (PowerShell), en remplaçant les heures par
celles notées (UTC) :

```powershell
.\.venv\Scripts\python.exe scripts\measure_speech_metrics.py --db data\state\jarvis.sqlite3 --snapshot `
    --baseline --window seance=2026-10-01T09:00Z..2026-10-01T10:15Z --trace runtime\trace.jsonl
```

- `--snapshot` copie le journal **sans son WAL** et mesure la copie ; le
  fichier d'origine n'est jamais ouvert par SQLite.
- Si l'outil affiche « le WAL contient N évènements absents du fichier seul »,
  **relancer avec `--snapshot-with-wal`** à la place de `--snapshot` (sinon la
  séance du jour peut manquer). S'il affiche « la vue AVEC le WAL échoue à
  l'intégrité », garder `--snapshot` et le noter (Issue
  `Issues/journal-wal-corrupt.md`).
- Ajouter `--json > seance.json` pour archiver le résultat avec la séance.
- Une partie précise seulement : une seconde fenêtre `--window partie5=DEBUT..FIN`.
- Définitions de chaque métrique : `docs/OPERATIONS.md`, « Speech presentation
  metrics ».

Recopier dans « Mesuré » : la section **Cibles**, la ligne `live:` (terminaux,
durées par `completion_basis`), « retenues », « parole prise / rendue » et
« Live après barge-in ».

---

## 8. Limites connues à garder en tête

| Limite | Effet attendu | Où |
|---|---|---|
| Barge-in sur Live : surface muette jusqu'à la fin de l'incarnation | Après une coupure sur Live, Jarvis se tait ; HV-05 (b) ne peut passer que sur Realtime | `Issues/live-barge-in-mutes-incarnation.md` |
| Aparté court (≤ 8 mots) classé adressé | Jarvis ne reprend pas simplement : le cerveau décide | `jarvis/runtime/realtime_audio.py`, `classify` |
| Pauses entre phrases > 500 ms | Fin de parole Live conclue trop tôt, parole suivante envoyée plus tôt | `LIVE_COMPLETION_GRACE_MS`, LOG Slice 02 rework |
| Refus de délégation retenu d'une intention passée | Jamais remis au cerveau ; expire après 120 s | LOG Slice 04 rework, point 4c |
| Pause plus longue que la grâce invisible comme pause | Elle termine la parole : seul le ressenti (section 1) la révèle ; les pauses plus courtes sont mesurées (« pauses entre phrases ») | `docs/OPERATIONS.md`, « Speech presentation metrics » |
| WAL du journal Core périmé | Lire la copie sans WAL (`--snapshot`) | `Issues/journal-wal-corrupt.md` |
