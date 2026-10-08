# Jarvis V1 operations guide

## First install

Run `setup.sh` (macOS/Linux) or `setup.ps1` (Windows PowerShell). This creates `.venv`, installs Jarvis with voice/dev extras, and copies the example configuration to `config/jarvis.toml` if absent.

Set the OpenAI key in the environment; do not place it in the tracked TOML file.

For persistent local configuration, put `OPENAI_API_KEY=your-key` in `.env` at the
Jarvis project root (already ignored by Git). The Jarvis CLI, `dev_start.py`, and
`supervisor_v2.py` load that file before reading configuration or starting children,
including Windows autostart. Restart Jarvis after editing it. Existing process
environment variables take priority; saved Control Center credentials still take
priority for Voice.

The file supports UTF-8 with or without a Windows BOM, one `NAME=value` per line,
optional single/double quotes, `export NAME=value`, and comments. Unquoted inline
comments start at whitespace followed by `#`. Values are literal: no shell commands,
variable expansion, escape decoding, or multiline values. Invalid assignments report
only the filename and line number, never the value. No file is required when the key
is already supplied through the environment or Control Center.

```bash
export OPENAI_API_KEY='...'
```

```powershell
$env:OPENAI_API_KEY="..."
```

## Optional screen recording (`capture` extra)

Desktop screenshots need nothing. Screen recording needs ffmpeg, installed
with the `capture` extra (Windows, from the Jarvis project root, Jarvis
stopped or not — Core reads it at each recording start):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[capture]"
```

This installs `imageio-ffmpeg==0.6.0` (BSD-2-Clause) and its bundled
ffmpeg 7.1 binary (about 85 MB, GPLv3 build with libx264, run as a separate
process). No restart is needed. Without it, a screen recording is refused
`source_unavailable` with the install command in the message. To use another
ffmpeg, set `JARVIS_FFMPEG_EXE`. Details: [capture.md](capture.md#screen-capture-slice-07).

Sessions, Contexts, recordings and evidence as a whole — what survives which
restart, environment flags, costs, where media live and how to delete them,
troubleshooting, schema v7 and rollback:
[session-context-capture.md](session-context-capture.md).

## Optional UI bootstrap

On a networked workstation:

```bash
python scripts/bootstrap_third_party.py
```

This downloads exact pinned snapshots and browser assets, verifies them, hardens Barehands and writes `third_party/INSTALL-STATE.json`.

Verify at any time:

```bash
python scripts/bootstrap_third_party.py --verify
```

Use `--force` only when intentionally rebuilding the pinned installation from `LOCK.json`.

## Health

```bash
python -m jarvis health
```

Required failures:

- missing API key;
- unreadable/unwritable memory directory;
- microphone preflight failure (unless intentionally skipped).

Optional warnings:

- Barehands unavailable;
- ai-visualizer unavailable;
- third-party UI not bootstrapped.

For headless/CI checks:

```bash
python -m jarvis health --skip-audio
```

## Starting Jarvis

Full stack:

```bash
python scripts/dev_start.py
```

Voice only:

```bash
python scripts/dev_start.py --no-board --no-visualizer
```

Useful launcher options:

- `--no-open`: do not open browser tabs automatically.
- `--no-preflight`: skip microphone startup check (debug only; normal operation should keep preflight).
- `--no-board`: do not start/use Barehands.
- `--no-visualizer`: do not start/use ai-visualizer.

## PTT behavior

Default key: `F9`.

- press/hold -> listening + capture;
- release -> stop capture, transcribe, think, answer;
- press during speech -> cancel playback and immediately enter listening for a new turn.

A very short accidental press is discarded without sending an empty turn.

Realtime Voice (`python -m jarvis voice`) has two turn modes, selected by
`JARVIS_VOICE_TURN_MODE` or by "Fin de tour" in Control Center settings.

`auto` (default): press F9, wait for `LISTENING`, speak. The provider's server
VAD closes the turn on silence and starts the answer, so F9 is never pressed
twice; while a turn is open F9 only cancels it. The microphone is released as
soon as the turn is committed, which keeps the speakers out of the next VAD
segment. `voice.speech_started` and `voice.input_submitted` record the turn.

`manual`: press F9, wait for `LISTENING`, speak, then press F9 again to submit.
An input shorter than 100 ms is skipped with a retry hint, and Voice returns to
background so F9 can start another turn. `voice.input_skipped` records the
reason.

In both modes, connecting and opening the devices can take several seconds, and
`voice.input_submitted` includes the number of captured/sent bytes and sent
duration, without storing raw audio.

## La fenêtre de réglages

Le bouton **SET** du Control Center (ou la touche `s`) ouvre une fenêtre
centrée, fermée par un clic à l'extérieur ou par `Échap`. Elle a six onglets :
Mode vocal, Prompts, Agent / CLI, Config, API Keys et Raccourcis, plus
Apparence (couche de thèmes) et Expérimental (scène constellation et Barehands en mode test).

Un principe la traverse : **la page ne connaît aucun réglage**. Le serveur
décrit ce qui existe — les piles vocales, leurs champs, les CLI, leurs modes,
les raccourcis — et la page se contente de l'afficher. Ajouter une option se
fait donc dans `jarvis/runtime/voice_stack.py` ou `cli_catalog.py`, pas dans le
HTML. Corollaire : un champ visible est un champ réellement transmis au
fournisseur, et il n'apparaît que lorsqu'il s'applique — les réglages de silence
disparaissent en fin de tour manuelle, les options Gemini n'existent pas sous
OpenAI.

### Mode vocal

Onglet **Voix** des réglages, catégorie **Architecture**. La liste
**« Architecture vocale »** propose les architectures versionnées du registre de
capacités (`jarvis/runtime/voice_capabilities.py`, `settings_architectures`) :
**Simple**, **Front Brain**, **Duplex** (GPT-Live, `openai / gpt-live-1`, avec
« Déléguer au cerveau (outils et sous-agents) ») ; enregistrée sous
`voice_architecture`. Laissée sur « Projection de compatibilité », Voice suit le
**« Mode vocal historique »**, rangé sous « Compatibilité et invariants avancés » :
« Un tour par appui » (`legacy`) ou « Conversation continue (jusqu'à F9) »
(`continuous_brain`), avec la « Pile vocale de compatibilité ». Le bouton
« Revenir au mode continu avec le cerveau Claude » y ramène. Ce choix historique
est rangé dans `voice_arch` de `runtime/control-center-settings.json` et passe
devant `JARVIS_VOICE_ARCH` ; laissé sur « Par défaut », Voice suit la variable,
puis le défaut calculé (voir « Deux architectures vocales »). Une combinaison que Voice refuserait —
conversation continue avec Gemini Live, ou avec une fin de tour manuelle — est
refusée à l'enregistrement, avec la raison.

The architecture does not say **who** may talk to JARVIS: that is the separate
role of the conversation mode (`open_room` / `solo_owner`), set right below it in
the **Qui peut parler à JARVIS** block of this tab and described in
"Conversation mode: who may talk to JARVIS" (what the block shows: "What the
Control Center shows for Solo Owner and echo cancellation"). The state of echo
cancellation (requested, installed, really applied by Voice) is shown under the
stack's settings, in **Annulation d'écho**.

Deux piles, interchangeables :

| Pile | Modèle | Clé | Fréquences |
| --- | --- | --- | --- |
| ChatGPT Live (OpenAI Realtime) | `gpt-realtime*` | OpenAI | 24 kHz → 24 kHz |
| Gemini Live (Google) | modèles `bidiGenerateContent` | Google | 16 kHz → 24 kHz |

Les deux adaptateurs émettent les mêmes enveloppes `realtime.*` : le pont de
conversation, les outils Core et l'appel de `claude_task` ne savent pas quel
fournisseur parle. Les fréquences ne sont pas des préférences, elles sont
imposées par chaque API ; `SoundDeviceRealtimeAudio` ouvre donc deux flux
PortAudio de fréquences différentes selon la pile choisie.

Gemini envoie les transcriptions par fragments pendant que la phrase se
construit. L'adaptateur les accumule et n'en publie qu'une par tour : le pont
range la transcription dans l'historique et s'en sert pour décider si JARVIS est
concerné, un flot de fragments créerait une dizaine de faux tours par phrase.

Gemini Live n'a pas de modèle par défaut : il faut en choisir un, sinon Voice
refuse de démarrer en le disant.

Les voix (`cedar`, `ash`, … côté OpenAI ; `Puck`, `Kore`, … côté Google) sont
les seules listes écrites en dur de cet écran, parce qu'aucun des deux
fournisseurs ne les expose par une API. La persona vit dans `JARVIS_PERSONA`,
`jarvis/adapters/openai_realtime.py`, et sert aux deux piles.

### Agent / CLI

| CLI | Pilotage | Console | Modèles listés depuis |
| --- | --- | --- | --- |
| Claude Code | processus permanent, `stream-json` | oui, sur la même conversation | Anthropic |
| Codex CLI | un `codex exec --json` par question | oui, sans passation de main | OpenAI |

L'onglet ne propose pas « Claude » et « Codex » dans l'abstrait : il exécute
`shutil.which` puis `<cli> --version`, et affiche la version et le chemin
résolus, ou la raison de l'échec. C'est aussi ce chemin résolu qui est lancé —
sous Windows, `CreateProcess` n'applique pas PATHEXT, et un CLI installé par npm
en shim `.CMD` (c'est le cas de `codex`) ne démarre pas autrement.

Changer de CLI arrête l'agent précédent avant d'armer le nouveau : deux agents
vivants écriraient dans le même dépôt sans se voir. Codex n'ayant pas de
processus permanent, son état oscille entre `ready` et `running`, et son fil se
poursuit d'une question à l'autre par son identifiant de thread.

Le vocabulaire diffère et l'écran le reprend : Claude parle d'autorisations
(`bypassPermissions`, …), Codex de bac à sable (`danger-full-access`,
`workspace-write`, `read-only`). Dans les deux cas, voir « Autorisations :
pourquoi le défaut est "tout autoriser" » plus bas — en vocal, personne ne peut
répondre à une demande d'approbation.

### D'où viennent les listes de modèles

Aucun CLI n'expose « donne-moi tes modèles ». La seule source qui ne périme pas
est l'API du fournisseur, et c'est celle qu'interroge `model_catalog` :

| Fournisseur | Appel | Classement |
| --- | --- | --- |
| Anthropic | `GET /v1/models` (paginé) | tout est du texte |
| OpenAI | `GET /v1/models` | `realtime`, `transcribe`/`whisper`, `tts`, sinon texte |
| Google | `GET /v1beta/models` | d'après `supportedGenerationMethods` déclaré par l'API |

Le résultat est mis en cache dix minutes, en mémoire et dans
`runtime/model-catalog.json`. Changer la clé active d'un fournisseur invalide
son catalogue : les modèles visibles dépendent du compte, pas seulement du
fournisseur.

Quand l'appel échoue, l'écran le dit et propose le dernier catalogue connu en le
marquant comme périmé. **Aucune liste écrite en dur n'est servie à la place** :
un modèle retiré du service qui resterait proposé dans un menu est un piège, pas
un secours. Sans clé du fournisseur, le menu reste sur « valeur par défaut du
service » et l'explique.

### API Keys

Une clé est une entrée nommée : `<fournisseur>` — `<nom libre>` — `<valeur>`.
Deux clés OpenAI, une perso et une du travail, coexistent ; le bouton de la
colonne « Active » désigne celle qu'utilisent les services de ce fournisseur.

L'ordre de résolution, dans `credentials.secret_for` :

1. la clé explicitement désignée pour ce fournisseur ;
2. son unique clé, s'il n'y en a qu'une ;
3. l'ancien champ plat du Control Center, s'il existe encore ;
4. la variable d'environnement, donc le `.env` du projet.

Les valeurs ne remontent jamais vers le navigateur : seuls les quatre derniers
caractères sont affichés. Et une clé venue de l'environnement n'est pas recopiée
dans le fichier de réglages — sinon le `.env` cesserait d'être sa propre source,
et la copie gagnerait après une rotation.

Le fichier `runtime/control-center-settings.json` contient donc des secrets en
clair dès qu'une clé y est saisie. Il est écrit en `0600`, hors du dépôt.

### Raccourcis

Ne figure dans cet onglet que ce qui fait quelque chose. Deux portées :

- **système** — la touche de réveil, captée par pynput dans le processus Voice
  même sans focus. `KeyboardWakeWordBackend` ne sait résoudre qu'une **touche
  seule** : `ctrl+j` est refusé à la saisie plutôt qu'accepté puis ignoré au
  démarrage. Prend effet au prochain redémarrage de Voice.
- **interface** — captés par le Control Center dans le navigateur, avec
  modificateurs, ignorés pendant la saisie dans un champ. Effet immédiat.

Deux actions ne peuvent pas partager une touche dans une même portée : la
seconde ne se déclencherait jamais et rien ne le dirait.

### Expérimental : Barehands en mode test (pointeur à mains nues)

L'onglet **Expérimental** (ajouté par `jarvis/runtime/control_center_barehands.js`,
comme l'onglet Apparence l'est par la couche de thèmes) porte un interrupteur
**Activer Barehands (mode test)**, éteint par défaut. Il s'applique et
s'enregistre immédiatement, sans bouton Enregistrer, sous
`barehands_test_mode` dans `runtime/control-center-settings.json` ; il reste
actif au prochain chargement de la page. Route dédiée, comme les raccourcis :
`GET /api/barehands` (réglages + outils + présence des assets) et
`POST /api/barehands` (refus HTTP 400 avec code stable `barehands_*`, rien
d'écrit). Depuis la Slice 07 la route porte **les neuf réglages**, en
`snake_case`, estampillés `schema_version` ; une clé absente garde ce qui est
enregistré, si bien que `{"enabled": false}` seul reste une écriture valide.
Événements : `settings.barehands`, `settings.barehands.rejected`.

Cette route est **délibérément hors de `/api/settings`** : elle s'applique à
chaud et ne dépend pas de la validité du reste des réglages (voix, CLI), qu'un
enregistrement complet revaliderait.

Activé, la page ouvre la webcam et suit les mains **dans le navigateur**
(MediaPipe Hand Landmarker, WASM + modèle `hand_landmarker.task`), sans service
cloud ni serveur Barehands. Mais **allumer, c'est guetter** : depuis la Slice 02
le cycle de vie vaut `off` → `sleep` → `active` (décision 4) et l'interrupteur
mène en **veille**, jamais directement à l'interaction. Aucun jeton, aucun
survol et aucun clic tant que l'utilisateur n'a pas réveillé. Contrat complet :
`docs/barehands-contracts.md` § 1.

**Veille (`sleep`)** — la caméra reste ouverte mais n'alimente qu'un guetteur
cadencé à **5 images par seconde** (une inférence toutes les 200 ms,
`WAKE_INTERVAL_MS`) ; entre deux, la boucle d'images ne fait qu'une comparaison
d'horodatage. Pastille `MAINS · VEILLE` en bas à gauche, `MAINS · VEILLE 40 %`
dès que la posture de réveil **commence** — une main qui bouge ordinairement ne
dessine rien (décision 46, tâche adaptative Slice 03) ; une main que le suivi
ne croit pas et qui forme le C montre un anneau pâle immobile et
`MAINS · VEILLE · rapprochez la main`. Le réveil est la **posture en C** (décision 5), majeur, annulaire et
auriculaire courbés vers la paume (décision 46 : une main plate ne réveille
pas) : pouce
et index écartés sans se toucher, index déplié, **tenue une seconde**
(`WAKE_HOLD_MS`). Un anneau de progression circulaire se remplit autour de la
main et dit combien de la seconde est acquise ; relâcher avant la fin annule.
Un trou du traqueur de moins de 400 ms (`wakeGraceMs`) est pardonné ; un trou
plus long remet la progression à zéro. **Ces deux nombres ne se règlent pas
séparément** : le guetteur n'échantillonne qu'une fois par `wakeIntervalMs`,
donc l'écart entre deux mesures **est** cette cadence, et
`wakeIntervalMs > wakeGraceMs` ferait retomber le maintien à chaque image — la
posture en C ne pourrait plus jamais aboutir, sans erreur ni trace. `options()`
refuse donc ce couple à la construction (`RangeError`), au même titre que
`pressRatio < releaseRatio` et `wakeGapMin < wakeGapMax` ; l'égalité
(`interval === grace`) reste permise et réveille encore. Baisser la cadence du
guetteur pour économiser le processeur, ou descendre la tolérance de trou,
oblige donc à regarder l'autre nombre. **Le temps non observé ne compte jamais** :
une caméra figée, un onglet passé en arrière-plan ou un écran rabattu ne
crédient rien du maintien, même si la posture était là avant et après.

**Interaction (`active`)** — chaque main détectée est **suivie**, mais son jeton
rond n'apparaît que lorsqu'elle **vise** (décision 46) : posture en C ou
pré-pincement (pouce qui se rapproche de l'index, index tendu, **les trois
autres doigts courbés** vers la paume — une main plate ou détendue ne vise
pas, et ne réveille pas non plus : le C qui réveille est le C qui vise) tenue
150 ms, ou
un pincement en cours, ou une prise tenue. Il disparaît 300 ms après que la
posture s'est perdue. Une main qui parle, passe ou se pose ne dessine rien — et
continue pourtant d'être suivie : un pincement, une prise et un clic se
décident sans le jeton, qui n'est jamais la source de l'interaction. Le jeton
suit le bout de l'index (image vue en miroir, 12 % de bord ignoré pour atteindre
les coins). La pastille compte toujours les mains suivies. Retour visuel : le jeton grossit et l'élément visé est cerné au survol ;
**présélection** (Slice 05 adaptative) : tant que la main vise, la cible qui
serait prise si l'on pinçait maintenant est cernée discrètement — une étoile
par un anneau et son nom dessous, un bouton par un cadre pâle — sans que le
jeton bouge ; entre deux voisines presque à égale distance, rien n'est
présélectionné, et l'aperçu ne bascule vers une voisine que si elle est
nettement plus proche ;
l'anneau se remplit pendant le rapprochement pouce-index et le jeton se fige
pour viser ; au pincement franc, une onde marque le clic. Le clic rejoue la
séquence souris (`pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`)
sur l'élément sous le jeton : boutons du dock, onglets, cases, cartes Agents,
fermeture de fenêtre. Seuils (`JarvisBarehandsCore.DEFAULTS`) : pincé sous 0,28
de la taille de paume, relâché au-dessus de 0,42 (hystérésis), deux images de
confirmation, 450 ms d'anti-rebond, un seul clic par pincement. Le jeton prend
le bleu de l'interface (`--bh-accent`, sinon `--accent`, sinon `#6ee7ff`) et
**ne suit pas l'état de l'agent** : `--cosmos-accent` est la couleur que l'orbe
republie à chaque changement d'état vocal (orange quand JARVIS parle), et elle
lui reste réservée — rien d'autre à l'écran ne s'y abonne, ce que vérifie
`tests/unit/test_agent_state_colour_stays_on_the_orb.py`.
Sans main exploitable pendant **30 secondes** (`SLEEP_TIMEOUT_MS`, décision 7),
l'interaction retourne d'elle-même en veille — la caméra n'est pas rendue, le
guetteur reprend. Le délai est jugé **avant** la lecture de la vidéo : une
caméra figée rendort aussi au lieu de rester active pour toujours.

**Gestes et pincements reconnus (`active`)** — depuis la Slice 04, deux moteurs
sémantiques tournent à côté des jetons, **en interaction seulement** (la veille
garde son budget de 5 images par seconde). Ils *reconnaissent et publient* ; ils
ne déclenchent encore aucune action, qui viendra avec le retour visuel et le
moteur d'interaction.

- **Pincement**, deux canaux : pouce + **index** (primaire) et pouce + **majeur**
  (secondaire, le clic droit). Le clic droit est un **doigt**, jamais un appui
  long. Chaque canal a ses propres états — approche, contact, déplacement,
  relâchement, annulation — et une **confiance** qui mesure ce qui le sépare de
  l'autre : une main qui se ferme entièrement rapproche le pouce des deux
  doigts à la fois, et n'est donc ni un clic ni un clic droit.
- **Intention** du canal primaire : un contact court, sur place et relâché main
  immobile est un **clic** ; dès que la main dépasse la tolérance de
  déplacement, c'est un **glissement**, décidé en chemin. Une main perdue en
  cours de contact **annule**, elle ne relâche pas : l'arrêt ne doit pas
  déclencher ce qu'il interrompt.
- **Pincer dans le vide ferme le menu contextuel** (Slice 10 adaptative,
  décision 70) : un pincement primaire qui descend sans **aucune** cible à
  portée fait ce que fait un clic gauche dans le vide — il ferme le menu du
  clic droit ouvert (et rien d'autre). Pincer entre deux voisines trop
  proches (refus pour ambiguïté) ne ferme rien : la main visait l'une d'elles.
  Pincer sur l'en-tête du menu ne le ferme pas non plus.
- **Postures** : le **C** de réveil (la même mesure que le guetteur), la **main
  ouverte**, le **poing**, la **double fermeture** (deux poings rapprochés dans
  le temps) et le **claquement** (deux paumes qui se rejoignent vite). Une
  posture doit être tenue un quart de seconde avant d'être annoncée ; une main
  qui pince n'est aucune posture.
- **Arbitrage** : un geste global ne volera pas la main à une manipulation en
  cours quand celles-ci existeront — seule la **main ouverte** est autorisée à
  passer, parce qu'une manipulation qu'on ne peut pas abandonner est un piège.

À lire depuis la console : `JarvisBarehands.gestures()` (événements, gestes
étouffés avec leur raison, postures et progressions de la dernière image) et
`JarvisBarehands.pinch()` (événements de contact au format du contrat, avec
l'identité de pointeur de chaque main, et l'état des deux canaux). Les deux sont
vides hors interaction. Contrat complet : `docs/barehands-contracts.md` § 4 et
§ 5.

**Panne (`error`)** — caméra refusée, absente, occupée ou débranchée, modèle
absent, suivi ou surimpression en échec. C'est un état distinct d'`off` : il dit
« arrêté sans l'avoir demandé », là où `off` dit « l'utilisateur l'a voulu ».
Comme `off` il ne tient rien — caméra, modèle, vidéo et boucle d'images sont
rendus **avant** qu'il soit publié — et le motif précis vit à côté de l'état,
dans le code du statut (`camera_denied`, `camera_busy`, `camera_missing`,
`camera_ended`, `camera_unsupported`, `assets_missing`, `webgl_unavailable`,
`tracking_failed`, `overlay_failed`, `start_failed`), jamais aplati dedans. On en
sort en rallumant.

Chaque panne est aussi envoyée par la page à `POST /api/barehands/failures`, qui
la range dans `runtime/errors.jsonl` (donc dans Error Logs) sous le kind
`barehands.failure`, avec le code, le message de l'erreur réelle et sa pile
(bornés à 4 000 caractères). C'est là qu'on lit la cause d'un « Suivi
interrompu », sans avoir besoin de la console du navigateur.

`webgl_unavailable` : le navigateur ne crée aucun contexte WebGL (ni 2 ni 1).
MediaPipe envoie chaque image vidéo au modèle par une texture WebGL, **même avec
le délégué CPU** : sans WebGL, le suivi ne peut pas tourner. La page le vérifie
avant de charger le modèle. Remède : activer l'accélération graphique
(`chrome://settings/system`), relancer le navigateur, vérifier `chrome://gpu`.
Si le pilote graphique est sur la liste noire de Chrome, le mettre à jour.

**Bandeau de cycle de vie**, sous l'interrupteur de l'onglet : il nomme l'état
courant (`Éteint`, `Démarrage…`, `En veille`, `Actif`, `Interrompu · <code>`) et
porte le bouton qui en change — « Allumer et activer », « Activer
l'interaction », « Mettre en veille », « Réessayer ». Pendant le démarrage il
affiche le temps écoulé et se désarme : la sortie est l'interrupteur du dessus,
qui annule un démarrage encore en vol. C'est le second chemin d'activation exigé
par la décision 6 ; **la voix emprunte le même depuis la Slice 12** (voir
« Piloter Bare Hands à la voix » ci-dessous). Depuis la console :
`JarvisBarehands.activate()` (allume si besoin, puis réveille),
`JarvisBarehands.sleep()` (rendort sans rendre la caméra),
`JarvisBarehands.lifecycle()` (l'état lu dans le vocabulaire du contrat) et
`JarvisBarehands.state()` pour le détail.

Arrêt **voulu** : interrupteur coupé, `pagehide`. L'état devient `off` et le
toast dit « Barehands arrêté ». Arrêt **subi** : caméra refusée, absente,
occupée ou débranchée, modèle absent, erreur du suivi. L'état devient `error`,
le toast reste à l'écran 9 s et porte la cause réelle. Dans les deux cas, un
seul chemin (`teardown`) arrête les pistes caméra, ferme le modèle, retire la
vidéo, les jetons et le survol ; un toast et l'onglet disent pourquoi. Un
démarrage encore en vol quand on éteint rend la caméra dès qu'elle arrive.

#### Piloter Bare Hands à la voix (Slice 12)

« Active les mains » n'est **pas** reconnu par la surface vocale : en
architecture `continuous_brain` elle n'a aucun outil (Décision 34) et il
n'existe dans ce dépôt ni registre de commandes vocales ni routeur d'intention.
C'est le **cerveau** (CLI Claude) qui reconnaît la demande et appelle un outil :

```
parole → cerveau → outil MCP jarvis-barehands → POST /api/barehands/commands
       → long-poll de la page → window.JarvisBarehands → reçu → réponse au cerveau
```

Six outils, un par action : `barehands_activate`, `barehands_deactivate`,
`barehands_calibrate`, `barehands_tutorial`, `barehands_exit_overlay` et, depuis
la Slice 10 adaptative, `barehands_test` (ouvre l'écran d'accueil du **Tester**
par la porte de son bouton ; aucun run ne démarre, aucun réglage ne change).
Un parcours refusé par sa porte d'entrée remonte au cerveau **son** code et sa
phrase (`barehands_flow_busy`, `barehands_calibration_lifecycle_off`,
`…_disabled`, `…_no_camera`, `barehands_benchmark_lifecycle_off`,
`…_no_camera`, `…_unavailable`) au lieu d'un `barehands_flow_unconfirmed`
muet. Bare Hands **éteint**, la voix reçoit d'abord le refus du Control
Center, `barehands_disabled` (409), avant que la page soit consultée : les codes
d'extinction de la page (`…_lifecycle_off`) ne viennent que des boutons, ou d'un
désaccord passager page/serveur. Les outils sont **vivants**, mais il ne reste **qu'un seul parcours
guidé** : la calibration (le Tester mesure, il ne guide pas). `barehands_tutorial` est
**déprécié** depuis la Slice 07B de l'affinage d'UI : le parcours de tutoriel
séparé a été retiré, l'outil ouvre la **calibration**, et sa note le dit au
cerveau — préférer `barehands_calibrate`. Aucun de ces six outils ne touche
l'interrupteur, les réglages ni l'outil de la main : ce canal-là transporte le
cycle de vie, le cerveau y réveille et y rendort, rien de plus. L'interrupteur
maître lui-même n'est pas hors de sa portée pour autant — c'est un réglage,
qu'il lit et écrit par le serveur de réglages (`barehands_test_mode.enabled`,
`GET`/`POST /api/barehands`), avec l'asymétrie décrite juste dessous.

Le serveur MCP `jarvis-barehands` n'est déclaré au CLI **que** si l'utilisateur
a allumé Bare Hands, avec sa consigne système ; éteint, le cerveau est lancé
exactement comme avant et ne sait pas que ces outils existent. Comme pour
l'affichage, c'est effectif au prochain **(re)démarrage du cerveau**.
L'asymétrie à connaître avant d'écrire le réglage : **éteindre prend effet tout
de suite** — la route des commandes relit l'interrupteur à chaque appel et
refuse `barehands_disabled` (409), donc les outils restent listés mais tous
leurs appels échouent —, tandis qu'**allumer** ne les fait pas apparaître dans
la session en cours ; ils n'arrivent qu'au redémarrage suivant. Le canal
côté page ne s'ouvre que pendant que l'interrupteur est vrai et que l'onglet est
**visible** ; il suit `/api/status` (`barehands.enabled`), sans minuterie de
plus. Fenêtre fermée ou onglet caché : `barehands_no_visible_page` après 3 s —
JARVIS le dit, il ne prétend pas avoir activé. Page **visible mais muette**
(l'invite d'autorisation caméra du navigateur tient `activate()` au-delà de 3 s,
par exemple) : c'est `barehands_command_expired`, et JARVIS dit que l'issue est
inconnue au lieu d'envoyer chercher une fenêtre qui est là. La ligne de trace se
lit sur `deliveries` : `0`, personne ne l'a prise ; `1`, une page l'a prise.

Refus HTTP : code stable dans le corps JSON **et** dans `X-Jarvis-Error-Code`.
Événements de trace : `barehands.command_requested`, `…_delivered`,
`…_applied`, `…_expired`, `…_abandoned`, `…_disabled` (interrupteur éteint),
`…_busy` (une commande est déjà en vol), `…_refused` (**la page** a dit non),
`barehands.receipt_refused`, `barehands.tool`, `barehands.tool_failed`. Toutes
les lignes d'une même commande portent le même `data.id` court, des deux côtés
du saut MCP. Contrat complet : `docs/barehands-contracts.md` § 12.

#### Agent de calibration : régler en parlant (calibration adaptative, Slice 06)

Pendant une calibration ouverte à l'écran, l'utilisateur peut dire ce qu'il
ressent (« le release colle », « ça saute », « là c'est nickel ») et JARVIS
règle **par essais** : il note le ressenti, relie ce qu'il entend aux mesures de
la séance, propose une cause, applique un réglage temporaire, fait refaire
l'exercice, juge sur les mesures, et ne range le réglage que si l'utilisateur
dit vouloir le garder. Contrat : `docs/barehands-contracts.md` § 17, décisions
50 à 55.

```
page : calibration ouverte ──POST /api/barehands/calibration-session (battement 10 s)──▶ Control Center
parole ─▶ Core ─▶ /api/agent/ask ─▶ (séance ouverte ?) consigne « Mode CALIBRATION » ─▶ cerveau
cerveau ─▶ outil calibration_* ─▶ POST /api/barehands/commands {command, payload}
        ─▶ long-poll de la page ─▶ JarvisBarehands.calibrationAgent ─▶ reçu {…, result}
```

- **Séance** : ouverte avec la calibration, fermée avec elle (Enregistrer,
  Quitter, Échap, croix, « ferme la surimpression »), échue côté serveur après
  30 s sans battement. `GET /api/barehands/calibration-session` dit si le
  serveur en voit une (`active`, `exercise`, `trial`, `expires_in_ms`).
- **Outils** : `calibration_status`, `calibration_record_feedback`,
  `calibration_propose_hypothesis`, `calibration_prepare_trial` (proposition
  visible, rien d'appliqué), `calibration_commit_proposal` (validation sur
  l'accord de l'utilisateur),
  `calibration_resolve_trial`, `calibration_rollback_trial`,
  `calibration_accept_trial`, `calibration_rerun_exercise`,
  `calibration_next_exercise` — toujours listés avec `jarvis-barehands`, refusés
  `barehands_calibration_inactive` hors séance.
- **Garder** exige un accord de l'utilisateur dit **depuis** l'essai, dans un
  tour qui lui est adressé : une ou plusieurs propositions entières qui
  **demandent** de garder (« oui », « on garde », « garde ce réglage »,
  « d'accord »…), et **aucun** mot de refus, de doute ou de retour à l'ancien
  dans la phrase (« non », « nan », « pas », « annule », « l'ancien », « comme
  avant », « bof », « si tu veux », « peut-être », une question…) ; « rien à
  redire », « pas mal », « ne colle plus » restent des accords — sinon
  `barehands_calibration_consent_missing`, avec le motif. À l'écran, le bouton
  « Garder ce réglage » suffit.
- **Réglages pendant la séance** : `settings_set` refuse
  (`barehands_calibration_active`) tout réglage Bare Hands qui change ce que
  fait le moteur — `assistance`, `sensitivity`, `target_preview`,
  `sleep_timeout_ms`, `tool` ; restent libres l'interrupteur (éteindre ferme la
  séance tout de suite), la lecture de diagnostic, la proposition de
  calibration et le champ tutoriel. L'écran de la page écrit ses réglages par sa
  propre route, comme avant.
- **Annuler** est immédiat, mais l'essai annulé reste à juger et bloque le
  suivant (`barehands_calibration_trial_unresolved`) ; sans mesure prise sous
  lui, seul « inconclusive » ou « worse » soutenu par la plainte de
  l'utilisateur passe. « inconclusive » coûte toujours × 0,8 : seul « improved »
  ne baisse pas la confiance.
- **Deux onglets** : une seule séance à la fois ; le second onglet reçoit
  `barehands_calibration_session_busy`, le dit une fois dans sa coque et
  calibre sans agent ; les commandes `calibration_*` ne sont remises qu'à
  l'onglet qui tient la séance (son long-poll présente `?calibration=`). Fermer
  la page ferme la séance (`sendBeacon`) ; éteindre Bare Hands ailleurs ferme la
  calibration de la page.
- **Avant / après par état effectif** : chaque mesure porte l'état sous lequel
  elle a été prise ; après un essai gardé, le suivant se compare aux mesures
  prises sous le réglage gardé. Un verdict chiffré demande trois pincements (ou
  un exercice entier) sous l'essai ; « Garder ce réglage » à l'écran refuse un
  essai que les mesures disent pire.
- **Un essai se juge sur son exercice** : l'essai liste ses exercices ;
  « refais » y ramène (`calibration_rerun_exercise` avec ou sans `exercise`) ;
  la revue de cet exercice met alors « Refaire » en avant ; il ne se garde que
  jugé et pas « worse ».
- **La revue attend toujours** (Slice 07 adaptative, décision 56) : après
  chaque exercice, le parcours s'arrête sur une revue — ce qui a été mesuré,
  l'explication de l'assistant — et n'avance jamais seul.
  `calibration_next_exercise` **sans** `reason` valide une revue réussie ;
  **avec** `reason` (`not_relevant`, `cannot_perform`, `tracking`, `later`)
  il passe l'exercice, même réussi, et sa mesure n'est pas gardée ; passer un
  exercice non terminé ou raté l'exige (`barehands_calibration_skip_reason_required`
  sinon : l'agent demande pourquoi). Le reçu dit `decision` (`validated` /
  `skipped`) : c'est ce que JARVIS annonce. Tant qu'un essai attend sa mesure
  sur l'exercice à l'écran : `barehands_calibration_trial_pending` — et depuis
  la Slice 10 les boutons « Valider l'étape » et « Passer… » refusent de même,
  avec la phrase « Un réglage d'essai attend d'être jugé sur cet exercice… »
  (un essai qui attend sur un autre exercice ne bloque rien). « Refais
  l'exercice X » vers une étape pas encore jouée :
  `barehands_calibration_exercise_not_played`.
  `calibration_status` rend les dernières décisions (`reviews`) et l'instant de
  séance de chaque ligne de mesures (`t`), sur la même horloge que les retours
  et les essais (décision 58).
- **Reçu refusé** : si la page répond avec un reçu que le serveur refuse (mal
  formé, trop gros), l'outil rend aussitôt `barehands_receipt_invalid` /
  `barehands_receipt_too_large` — la page a peut-être agi, le cerveau doit
  relire `calibration_status`. `calibration_status` se tient sous 14 Ko et dit
  ce qu'il a retiré (`truncated`).
- **Mise en veille demandée pendant un parcours** (Slice 10) : « mets les
  mains en veille », le bouton ou `JarvisBarehands.sleep()` pendant une
  calibration (ou un run du test) **ferme d'abord le parcours** — rien n'est
  enregistré, l'essai en cours est défait —, affiche « Bare Hands en veille »
  avec la raison (`barehands.sleep_ends_flow` en console), puis endort. La
  veille automatique (trente secondes sans main), elle, reste suspendue
  pendant un parcours.
- **Rapport** : la liste des exercices a une hauteur bornée et défile seule
  (liseré en bas quand elle déborde, focalisable au clavier), pour que « Sera
  enregistré » et les boutons restent visibles à 1440 × 900.
- **Sans la voix** : dans la revue, « Ajuster » ouvre « Qu'est-ce qui ne va
  pas ? » (quatre ressentis) ; quand un essai est en cours, « Annuler
  l'essai » / « Garder ce réglage » restent sous la ligne de commentaire. Ce que
  fait la voix s'écrit sur la même ligne.

**Trace** (`runtime/trace.jsonl`) : `barehands.calibration_session_opened` /
`_closed` (`why` : `page`, `expired`, `disabled`, `shutdown`), `_session_refused`
(second onglet), `barehands.receipt_rejected`, `barehands.calibration_refused`
(porte du serveur : `code` `barehands_calibration_inactive` ou
`_consent_missing`), plus les lignes `barehands.command_*` et `barehands.tool*`
du canal. Ces lignes-là ne portent aucune phrase de l'utilisateur ; **le journal
général du cerveau**, lui, écrit chaque tour (`agent.input`, et les résultats
d'outils `calibration_*` dans `agent.event`), calibration comprise — question de
rétention ouverte pour l'Humain (Issue ISSUE-03 de la tâche). Côté page (console,
convention `[barehands] événement {json}`) : `barehands.calibration_feedback`,
`_hypothesis`, `_trial`, `_trial_resolved` (confiance avant/après),
`_trial_rolled_back`, `_trial_accepted`, `_agent_refused` (faute nommée),
`_status_truncated`, `_session_held`, `_session_beacon`,
`_session_report_failed` (erreur après trois échecs de suite, donc dans Error
Logs par `/api/barehands/failures`).

**Diagnostiquer** : l'outil refuse `barehands_calibration_inactive` alors que la
coque est ouverte → la page n'a pas déclaré sa séance (module
`control_center_barehands_calibration_agent.js` absent : la console dit
`barehands.calibration_agent_unavailable` ; ou envoi refusé :
`barehands.calibration_session_report_failed`). Un essai refusé nomme sa faute
dans l'erreur d'outil (`barehands_calibration_hypothesis_disproven`,
`_trial_unresolved`, `_refs_misplaced`, `barehands_trial_*`…).

**Modèle de menace.** Ces contrôles défendent contre un cerveau qui comprend
mal l'utilisateur, pas contre un cerveau hostile : ses propres moyens (Bash,
sous-agents) sont hors du modèle. La route de séance et `/api/agent/ask`
acceptent une requête sans `Origin` (processus locaux), comme le canal de
commandes ; une origine étrangère est refusée.

**Trace du vrai cerveau (QA).** Le harnais
`tasks/jarvis-mcp-semantic-batch-inspector/slices/08-integration-release-qa/qa/evidence/scripts/brain8.py`
appelle `ClaudeLocalAgent.ask` directement : il ne passe pas par
`/api/agent/ask`, donc ni la consigne du mode ni l'enregistrement des paroles
(accord) n'y seraient. Pour une trace de calibration, sur un Core et un Control
Center isolés (jamais 17653/17654) avec Bare Hands allumé et la page ouverte
dans Chrome sans tête (caméra factice), une calibration lancée
(`barehands_calibrate` ou le bouton) :

1. interroger **l'agent du Control Center isolé** : allumer Bare Hands avant
   son (re)démarrage, pour que `jarvis-barehands` (et donc `calibration_*`)
   soit monté — l'instantané de l'agent le dit (`barehands_tools`). Les
   retouches d'argv de `brain8.py` (`--no-session-persistence`) se reportent
   dans ce lancement si on les veut ;
2. envoyer chaque tour par la route du Control Center, pas par `agent.ask` :
   `POST http://127.0.0.1:$JARVIS_UI_PORT/api/agent/ask`
   `{"text": "<phrase>", "context": {"addressing": "addressed"}}` — c'est elle qui
   appose le mode calibration et garde la phrase pour l'accord ;
3. suivre les fixtures `tests/fixtures/barehands_calibration_traces/`
   (`falsified.json`, `ambiguous.json`) comme scénario de phrases, et relire
   dans `runtime/trace.jsonl` les `barehands.tool` (outils appelés, dans
   l'ordre) et dans la réponse du cerveau les nombres annoncés, à comparer aux
   reçus (`calibration_status`, `calibration_resolve_trial`).

Assets : non versionnés, ce sont ceux que `scripts/bootstrap_third_party.py` a
vendorisés sous `third_party/barehands/vendor` (MediaPipe Tasks Vision 0.10.14,
Apache-2.0). Le Control Center en sert une liste blanche sous
`/barehands/assets/…` ; `JARVIS_BAREHANDS_VENDOR_DIR` désigne un autre dossier
(un worktree sans installation, par exemple). Absents, l'onglet liste les
fichiers manquants et la caméra n'est jamais ouverte.

Ce qui n'a pas été repris ni touché, volontairement : le serveur Barehands
(port 8794), `stage.html` et son moteur de gestes (code AGPL-3.0 : rien n'en est
copié, le pointeur est une réimplémentation), le jeton codé en dur de
`jarvis/runtime/factory.py` (il ne concerne que l'outil V1 `board_present` via
`/cmd`, que le mode test n'utilise pas), la CSP `frame-ancestors 'none'` du
serveur patché (aucune iframe) et le chemin d'orbe périmé de
`third_party/barehands/barehands.json` (lu seulement par `stage.html`). Ces
points restent ouverts pour le board V1.

Limites connues : pas de glisser-déposer ni de défilement ; une liste
déroulante `<select>` ne s'ouvre pas sur un clic simulé ; le visage
ai-visualizer (iframe) ne reçoit pas les clics ; le survol n'active pas les
styles `:hover` natifs (un contour les remplace) ; le suivi tourne sur le fil
principal de la page.

#### Tester : vérifier qu'une calibration a aidé (calibration adaptative, Slices 08 et 09)

**Lancer.** Clic droit sur le bouton à icône de main (en haut à gauche) →
**Tester…**, ou onglet Expérimental → section **Test** → **Tester…**, ou à la
voix (« teste mes mains », outil `barehands_test`, Slice 10 : ouvre l'écran
d'accueil, l'utilisateur lance le run ; un refus remonte au cerveau avec le code
et la phrase de la porte). Bare
Hands doit être en Veille ou Actif (sinon, aux boutons : refus
`barehands_benchmark_lifecycle_off`, entrée grisée avec sa raison ; à la voix :
`barehands_disabled` du Control Center, avant la page) ; le test réveille la caméra lui-même. Il ne
dépend pas de « Proposer la calibration ». La fenêtre doit faire au moins
**1024 × 560** : plus petite, l'accueil affiche la phrase du banc et ne propose
que « Vérifier à nouveau ».

**Déroulé** (~2 minutes) : six exercices — prendre une étoile (6), étoiles
voisines (6), étoile mobile (4), glisser-déposer (5), enchaîner (4), bouger sans
cliquer (4, mouvement libre puis visée sans pincer). Chaque exercice s'ouvre sur
une consigne de 3 s (« Commencer maintenant » l'abrège). Pendant les essais :
l'étoile **pleine** est à prendre, les cercles vides sont des leurres, l'anneau
blanc montre ce qu'un pincement prendrait maintenant, le cadre en pointillé est
la destination (la fenêtre doit y tenir entière). Aucun score pendant le run.
**Pause** (bouton ou Échap) arrête le temps des exercices ; en pause, Échap
quitte sans rien enregistrer ; une pause ne tue jamais le test (seul le temps
des exercices compte pour l'échéance de 6 minutes). Sans main visible, le test
continue et le dit (« Aucune main vue »). Éteindre Bare Hands ou changer la
taille de la fenêtre (autre classe, ou plus petite) arrête le test sans rien
enregistrer ; relancez-le.

**Lire les résultats.** Les huit dimensions d'abord (score sur 100, barre, une
phrase), l'indice global ensuite — il n'est calculé que si les huit sont
mesurées, et plafonné par la plus faible. **Mesures** déplie les valeurs brutes.
Une dimension **sous 60** est expliquée et propose « Calibrer « exercice »… »,
qui ouvre la calibration directement à l'exercice qui y répond (les écrans
d'avant sont passés « plus tard » ; « Enregistrer » ne remplace que ce que la
séance a mesuré — le rapport liste « avant → après » et « Conservé »). Le score décrit **Bare
Hands avec ces réglages**, pas la personne.

**Avant / après.** Chaque résultat se range tout seul (au plus 20,
`runtime/barehands-benchmarks.json`). Refaire le test après une calibration :
le rapport annonce le test comparable précédent (même taille de fenêtre, même
version du test) et **Voir l'avant / après** donne, par dimension, Amélioré,
Dégradé, Inchangé ou **Pas de conclusion — relancez le test** (trop peu
d'essais, ou écart trop incertain). Ne comparez que deux tests faits par la
**même personne** : le geste de chacun entre dans les mesures. Un réglage qui
agit sur des événements rares (l'assistance, par exemple) demande souvent
plusieurs runs pour sortir de « Pas de conclusion ». **Tous les résultats**
rouvre un ancien test ; « Effacer tous les résultats… » (deux pressions) vide
l'historique.

**Journal** (console de la page, `[barehands] événement {json}`) :
`barehands.benchmark_opened`, `_run_started`, `_screen`, `_paused`/`_resumed`,
`_run_done`, `_saved`, `_compared`, `_run_ended` (`why`), `_closed`,
`_seam_opened`/`_seam_closed` ; pannes au niveau erreur, donc dans **Error
Logs** : `barehands.benchmark_frame_failed` (le run s'arrête, l'écran dit la
cause et le code), `_start_failed`, `_run_timeout` (6 min), `_save_failed`,
`_list_failed`, `_compare_failed`, `_clear_failed`. Serveur :
`barehands.benchmark_recorded`, `_rejected`, `_unreadable`, `_cleared`.

#### Outils et Réglages (Slice 07)

L'onglet porte **deux sections de plus**, et la distinction est le sujet
(décision 25) : un **outil** dit « ce que la main veut dire » et se change en
pleine session ; un **réglage** dit « comment Bare Hands se comporte » et se
persiste.

**Outils.** Palette de **trois**. `Pointeur` reste **contextuel** — clic,
glissement, défilement ou sélection selon ce qu'il y a sous la main, c'est-à-dire
le comportement d'avant. `Main` impose le défilement, `Sélection` impose la
désignation ; l'une et l'autre **refusent** une cible qui ne s'y prête pas, et
le refus s'écrit sous la pastille (`OUTIL INAPPLICABLE · cette cible ne s'y
prête pas`). Un outil ne prend jamais un bord, un coin, ni le corps d'une étoile
`point`/`signal` : ce sont des poignées de cadre.

`Surligneur` et `Dessin` ont été **retirés de la V1** (décision humaine, fin de
tâche). Ils étaient déclarés au contrat, refusés partout, et possédés par
aucune Slice : la palette proposait deux capacités qui n'existaient pas, et
rien à l'écran ne doit laisser croire à une capacité absente. La couche
d'annotation sera conçue pour elle-même, plus tard. La table
`INSTALLED_TOOLS` reste néanmoins **séparée** de `TOOLS`, bien qu'elles
coïncident aujourd'hui : c'est elle qui rend « installé » vérifiable, donc un
outil déclaré demain sans moteur se refait refuser
(`barehands_tool_not_installed`) au lieu d'être accepté sans effet.

**Réglages**, tous appliqués à chaud et enregistrés immédiatement :

| Réglage | Effet |
|---|---|
| Aperçu de la cible | décision 24 : éteint, le cadre et la zone ne sont plus dessinés ; la cible continue d'être résolue, et le contour hérité reste le repère sous intention |
| Assistance de visée | portée au-delà du cadre, 0 à 48 px ; le défaut (0,5) rend exactement la portée d'usine |
| Sensibilité du geste | divise les deux tolérances de déplacement (`clickSlopPx`, `dragSlopPx`) ; le défaut rend les seuils d'usine. Depuis la Slice 04 adaptative, le résultat est **borné** à 3 – 48 / 6 – 104 px (une sensibilité basse sur une tolérance calibrée large plafonne), et le chiffre affiché est la tolérance effective, profil et essai compris |
| Retour en veille | décision 7, 5 s à 600 s ; c'est enfin le délai **réel** (le contrôleur recevait la constante) |
| Lecture de diagnostic | panneau en bas à droite : qualité, vitesse et immobilité par main. Rien n'est enregistré ; éteint, le panneau est **absent** de l'arbre |
| Proposer la calibration | décision 27 ; **lu depuis la Slice 08** : décoché, le bouton « Calibrer » est désarmé et le parcours ne se propose plus |
| Réinitialiser les réglages | rend les valeurs d'usine ; **ne touche pas à l'interrupteur**, donc n'éteint jamais la caméra, et **ne touche pas au profil de calibration** (voir ci-dessous) |

**« Réinitialiser » réinitialise les réglages, pas le profil.** Le handoff
parlait d'une « réinitialisation du profil » ; ce qui est livré remet les neuf
**réglages** à l'usine et laisse la calibration enregistrée intacte. C'est un
rétrécissement assumé et non un oubli : les deux effacements ne se pardonnent
pas pareil — un réglage se refait en trois clics, une calibration coûte une
minute de poses à l'utilisateur. Le profil s'efface par sa propre route
(`clear`), qui retire le bloc au lieu de le remplir de nuls, et le moteur
revient alors à ses défauts (décision 31).

**Septième paire dangereuse.** `sleepTimeoutMs` doit rester **au-dessus** de
`wakeHoldMs` : en dessous, la seconde de posture en C coûte plus cher que le
temps qu'elle achète, la veille reprend la main à l'image suivante et la
session cycle — en détruisant à chaque tour les identités de piste et les
fentes de pointeur. `options()` le refuse à la construction **et** à chaque
`controller.configure`, comme `pressRatio < releaseRatio` et les cinq autres.
La borne basse de l'écran (5 s) est cinq fois au-dessus : le refus protège un
appelant, pas l'interface.

**Depuis la console** : `JarvisBarehands.settings()` lit, `settings({...})`
écrit (normalisé, appliqué, enregistré, `null` si rien n'a été enregistré) ;
`tools()` liste la palette et `tool('pan')` en choisit un. `targetPreview()` et
`targetAssistance()` changent le moteur **sans** persister — un essai n'a pas à
devenir une préférence.

**Profil d'essai** (tâche adaptative, Slice 04, contrat § 17 décision 48) :
`JarvisBarehands.trial.apply({pressFrames:1})` applique un réglage borné **à
chaud**, relit la valeur chez le moteur et rend un reçu
`{ok, code, applied, rejected, trialId, appliedAt}` ; `trial.rollback()` défait
le dernier essai (`{all:true}` : tous), `trial.accept()` range exactement
l'essai (profil v3 et réglages), `trial.status()` montre enregistré / essai /
effectif, `trial.history()` les dernières opérations. Rien n'est rangé sans
`accept()` : recharger la page ou quitter la calibration défait l'essai.
L'onglet liste les réglages acceptés sous le profil de calibration.

**Changement de conduite (Slice 04 adaptative).** Les seuils de pincement
calibrés **par main** s'appliquent enfin à la main gauche et à la main droite :
avant, le moteur lisait toute main comme « non étiquetée » et ignorait les
seuils mesurés pour `left`/`right`. Une calibration existante peut donc se
sentir différente dès la mise à jour. `jitterPx` et la portée mesurée ne
comptent plus pour « Calibré » (aucun effet moteur). La carte d'aide annonce la
durée de réveil réellement exigée. Un réglage changé côté serveur
(`settings_set barehands.*`) n'atteint toujours la page qu'au rechargement.

#### Ce qu'une main peut saisir, et les deux façons de tirer

La page a longtemps dit ici que « Barehands ne glisse pas ». C'était faux depuis
la Slice 06, et le tableau de la scène constellation, trois lignes plus haut,
disait déjà le contraire. Voici la vraie règle, qui est une distinction et non
un oui-ou-non.

**Un glissement de pointeur, partout.** Sur une page ordinaire — un panneau, une
liste, un champ — un pincement tenu puis déplacé émet la vraie séquence
`pointerdown` / `pointermove` / `pointerup`, et l'annulation émet
`pointercancel`. Ce que la souris déplace, la main le déplace.

**Une capture de cadre, sur les objets de la scène.** Une étoile, une capsule ou
une fenêtre de la constellation ne passe **pas** par le pointeur : elle passe par
la couture `JarvisScene.frames`, qui déplace, redimensionne et valide en unités
de scène. Une zone tenue déplace le cadre entier ; deux zones compatibles du même
objet le redimensionnent.

**Et le corps d'une étoile n'émet aucune séquence de pointeur** — c'est le
carve-out `.sc-node` de la décision 8. Sans lui, la page de scène lirait un
glissement sur le corps comme un déplacement de cadre, c'est-à-dire exactement ce
que la décision 8 interdit, mais par la porte de derrière : le corps d'une
capsule ou d'une fenêtre est du **contenu** (on y défile, on y sélectionne), pas
une poignée. Les poignées sont les bords et les coins.

**Ce qui reste vrai, en revanche : le pincement n'ouvre pas de lien.** Un
navigateur n'ouvre un onglet que sur une activation utilisateur réelle, et un
geste synthétisé par la page n'en est pas une. Ce n'est pas une limite de Bare
Hands mais une règle du navigateur, la même que celle notée au § 13 de
`docs/SECURITY.md`. Un lien se lit à la main, il se suit à la souris ou au
clavier.

#### Procédure de test manuel (caméra réelle)

**Rien de ce qui suit n'a été exécuté.** Il n'y a ni webcam ni navigateur dans
l'environnement où Bare Hands a été construit, et la validation humaine a été
**levée** pour cette livraison — levée, pas satisfaite. Aucune phrase de ce
dépôt sur la façon dont Bare Hands se comporte devant une vraie main n'a été
vérifiée par observation. Ce qui suit est la dette, rassemblée en une procédure
qu'un humain peut réellement dérouler.

**Groupée par séance de caméra**, parce que c'est la contrainte réelle : ouvrir
la caméra, se placer, régler la lumière coûte plus cher que n'importe quelle
étape prise isolément. Sept lots, A1 à A7. A1 et A2 se tiennent d'une traite ;
A3 demande une webcam **réellement** en 640×480 ; A7 demande le cerveau lancé.

Notez la webcam, sa résolution, le navigateur et l'éclairage : ce sont les
variables qui font diverger deux séances, et sans elles un « ça marche » ne se
compare à rien.

##### Préparation (une fois)

1. Assets présents : `python scripts/bootstrap_third_party.py --verify` rend 0.
2. Lancer le Control Center (`python -m jarvis control-center`), ouvrir
   `http://127.0.0.1:17654/` dans Chrome. Depuis un worktree, en parallèle d'un
   JARVIS déjà lancé : `JARVIS_UI_PORT=17655`, `JARVIS_VISUALIZER_ENABLED=0`,
   `JARVIS_BAREHANDS_VENDOR_DIR=<dépôt principal>\third_party\barehands\vendor`.

##### A1 — caméra, cycle de vie, pannes

- **A1.1** SET → Expérimental → cocher l'interrupteur. Attendu : invite caméra,
  le bandeau passe par « Démarrage… » avec son compteur de secondes, puis toast
  **« Barehands en veille »** et pastille **`MAINS · VEILLE`** en bas à gauche.
  Le bandeau lit « Cycle de vie : **En veille** », bouton « Activer
  l'interaction ». **Aucun jeton ne doit apparaître**, même en agitant les
  mains : la veille guette, elle ne pointe pas.
- **A1.2** **Veille par le bouton, et retour.** SET → Expérimental → « Mettre en
  veille » : jetons retirés, pastille `MAINS · VEILLE`, **le voyant caméra
  reste allumé** (c'est SLEEP, pas OFF). « Activer l'interaction » : les jetons
  reviennent sans nouvelle invite caméra. Même chose depuis la console avec
  `JarvisBarehands.sleep()` / `JarvisBarehands.activate()`.
- **A1.3** **Retour en veille après 30 s (décision 7).** En interaction, sortir
  les mains du champ et attendre 30 secondes sans bouger. Attendu : toast
  « Retour en veille », pastille `MAINS · VEILLE`, voyant caméra toujours
  allumé. Refaire ensuite avec « Retour en veille » réglé à 5 s : c'est le délai
  **réel** qui doit être suivi, pas la constante d'usine.
- **A1.4** Couper l'interrupteur au pincement : jetons retirés, voyant caméra
  éteint, toast « Barehands arrêté », bandeau « Éteint ». Recharger la page :
  toujours éteint, et la page repart en veille, pas en interaction.
- **A1.5** Réactiver, recharger : le mode test repart seul **en veille**.
  Refuser la caméra dans Chrome (icône de l'adresse) puis recharger : toast
  « Caméra refusée », aucune surimpression, message dans l'onglet, et le bandeau
  lit « Interrompu · camera_denied » avec un bouton « Réessayer » — **pas**
  « Éteint » : une panne n'est pas un arrêt voulu.
- **A1.6** Débrancher la webcam pendant le suivi : « Caméra coupée », tout est
  retiré, bandeau « Interrompu · camera_ended ».
- **A1.7** **La caméra prise par quelqu'un d'autre.** Ouvrir Zoom, Teams ou
  `chrome://settings` sur la même webcam, puis activer Bare Hands. Attendu : un
  refus **qui nomme la cause**, jamais un bandeau « Démarrage… » qui ne finit
  pas. C'est la RÈGLE ZÉRO : un état d'attente porte une échéance.
- **A1.8** **Deux onglets du Control Center.** Attendu : les deux ouvrent la
  caméra, ou le second dit pourquoi il ne peut pas ; aucun des deux ne reste
  muet. Noter ce qui se passe — ce cas n'a pas de contrat écrit, et la réponse
  observée doit en devenir un.

##### A2 — la posture de réveil

**A2.2 en premier : c'est l'item ouvert le plus cité de toute la tâche.** S'il
échoue, le reste du lot peut attendre — la bande de réveil se règle d'abord.

- **A2.2 — LE FAUX RÉVEIL À MAIN PLATE.** Présenter une main **plate, doigts
  serrés, pouce collé contre l'index**, paume face caméra, et la tenir immobile
  deux secondes. Attendu : **rien**. La pastille peut monter un peu puis
  redescendre, mais l'anneau ne doit pas se remplir et Bare Hands ne doit pas
  passer en `ACTIF`. Reprendre en inclinant la main de 15°, 30°, 45°, et à deux
  distances (40 cm, 80 cm). Un réveil sur l'une de ces poses est le défaut
  suspecté depuis la Slice 02 : le score du C tient l'écart pouce-index entre
  `wakeGapMin` (0,46) et `wakeGapMax` (0,85) **en paumes**, et une main plate
  vue de face peut produire un écart apparent dans cette bande alors que le
  pouce est adducté. Si ça réveille : noter la pose, la distance et l'angle,
  puis lire `JarvisBarehands.inspect()` pour relever `cPose`, `gapPalms` et
  `closure` au moment du faux positif. Ce sont ces trois nombres qui disent s'il
  faut resserrer la bande ou ajouter une condition d'index déplié.
- **A2.1** **Le vrai réveil (décision 5).** Former un C — pouce et index écartés
  sans se toucher, index bien déplié, main à plat face caméra. Attendu : la
  pastille passe à `MAINS · VEILLE 20 %`, `40 %`… et un anneau de progression
  se remplit autour de la main en une seconde environ. Relâcher à mi-course :
  la progression retombe, rien ne s'active. Retenir la posture jusqu'au bout :
  toast « Barehands activé », pastille `MAINS · ACTIF`, bandeau « Actif ».
- **A2.3** **Le temps non observé ne compte pas (R1).** Reformer le C et, à
  mi-anneau, masquer la main une bonne seconde, ou passer l'onglet en
  arrière-plan, ou rabattre l'écran une minute. Au retour : l'anneau **repart
  de zéro**. Attendu : aucune activation en une image. Un réveil qui
  surviendrait sans seconde de maintien réellement observée est un défaut
  bloquant.
- **A2.4** **Le trou pardonné.** Masquer la main **moins de 400 ms**
  (`wakeGraceMs`) au milieu de l'anneau. Attendu : la progression **continue**
  au lieu de repartir de zéro. C'est la moitié d'A2.3 qu'aucun test ne peut
  distinguer de l'autre sans caméra.
- **A2.5** **Un pincement en cours ne réveille pas.** Pincer franchement (pouce
  et index en contact) et tenir. Attendu : aucun anneau de réveil. La bande le
  garantit par construction — `wakeGapMin` reste au-dessus du seuil de
  relâchement du pincement — mais c'est une garantie sur des nombres, pas sur
  une main.
- **A2.6** **Deux mains qui forment le C en même temps.** Attendu : un seul
  réveil, pas deux cycles concurrents.

##### A3 — les nombres du pincement, sur une vraie 640×480

Ce lot demande une webcam qui sort **réellement** du 640×480, pas une 1080p
redimensionnée : c'est la résolution basse que les seuils doivent tenir, et
c'est là que le bruit des points est le plus fort.

- **A3.1** Pincer et relâcher **vingt fois** à distance confortable. Relever
  `JarvisBarehands.inspect()` après chaque salve. Attendu : vingt clics, zéro
  double-clic, zéro clic manqué.
- **A3.2** Refaire à 40 cm puis à 100 cm. Attendu : le ratio de pincement est
  normalisé par la paume, donc les deux distances doivent donner le même
  comportement. Un écart ici dit que la normalisation ne tient pas.
- **A3.3** **L'hystérésis.** Approcher pouce et index **très lentement**
  jusqu'au seuil et s'y tenir en tremblant. Attendu : **un** clic, pas une
  rafale. C'est ce que `pressRatio < releaseRatio` existe pour empêcher.
- **A3.4** **Le canal secondaire.** Pincer avec le **majeur** : attendu, un
  `contextmenu` au relâchement, jamais une manipulation. Vérifier que le menu
  contextuel est bien celui de l'objet visé.
- **A3.5** Main partiellement hors cadre, main de profil, main gantée, deux
  mains qui se croisent. Attendu : pas de clic fantôme. Noter la qualité
  (`quality`) sous laquelle le suivi devient inutilisable et comparer au
  plancher `HAND_QUALITY_FLOOR` (0,25).
- **A3.6** **Devant le visage et le torse.** Main ouverte qui passe lentement
  puis vite devant le visage, puis devant le torse, au-dessus d'un bouton.
  Attendu : aucun clic. Pincer, **tenir** en traversant le visage : attendu,
  l'objet n'est pas lâché. Relâcher devant le visage : attendu, relâché en
  moins de 100 ms. Enregistrer la séance (bouton d'enregistrement des réglages
  Bare Hands) : la trace porte `primaryConfidence` et `primaryWorldRatio`, qui
  disent si un faux contact passait la porte de confiance et ce qu'en disait la
  profondeur — c'est sur elles que se règle `worldVetoRatio`.

##### A4 — visée, retour visuel, lisibilité

- **A4.1** Montrer une main ouverte et la bouger comme en parlant : **aucun
  jeton** (décision 46), la pastille dit `MAINS · 1`. Former le C : un jeton
  suit l'index ; deux mains qui visent, deux jetons. Relâcher le C : le jeton
  disparaît. Survoler un bouton du dock en visant : jeton agrandi, bouton cerné.
- **A4.2 — LES ZONES D'UNE FENÊTRE COMPACTE.** Aucun harnais de DOM n'existe
  pour `installJarvisScene` : `data-representation` est vérifié **en lisant la
  source**, donc une fenêtre qui perdrait ses zones serait invisible à tous les
  tests. Réduire la fenêtre du navigateur jusqu'à ce qu'une fenêtre de scène
  soit petite, puis viser son bord et son coin. Attendu : bord et coin restent
  atteignables et distincts du corps. Le corps d'une capsule de 24 px de haut
  doit rester un corps.
- **A4.3** **L'aperçu de cible ne se dessine que sous intention (décision 3).**
  Main ouverte, rien ne doit être surligné. Approcher les doigts : l'aperçu
  apparaît. Éteindre « Aperçu de la cible » : plus rien n'est dessiné, mais le
  clic continue de viser juste.
- **A4.4** **Les trois couleurs (décision 23)** sont-elles distinguables sur le
  thème clair **et** sur le thème sombre, et à 80 cm ? Vérifier aussi sous le
  réglage « mouvement réduit » du système.
- **A4.5** **L'assistance de visée**, à 0 puis à 48 px : la différence doit être
  ressentie sur une petite cible, et ne doit jamais faire sauter le jeton sur
  une cible voisine.
- **A4.6** **La présélection (Slice 05 adaptative).** En visant (C formé),
  passer sur les étoiles de la scène : l'anneau se pose sur l'étoile qui serait
  prise, son nom dessous (au-dessus, ou pas de nom, s'il couvrirait une
  voisine) ; pincer : c'est **elle** qui est prise. En arrivant de loin entre
  deux étoiles très proches, à mi-chemin : aucun anneau ; en venant d'une
  étoile, l'anneau la garde jusqu'à ce que la voisine soit deux fois plus
  proche, jamais jusqu'à 2 px de la voisine. Main posée à mi-chemin de deux
  étoiles espacées d'au moins 12 px : l'anneau ne clignote pas. Pincer après
  une approche où le doigt a glissé vers la voisine : c'est l'étoile sous le
  jeton au moment du contact qui est prise. Un grand panneau ou le fil de
  temps ne s'entourent jamais d'un cadre au survol. Trembler au-dessus d'une
  étoile près de sa voisine : l'anneau ne clignote pas. Survoler un bouton du
  dock en visant : cadre pâle, sans étiquette ; main ouverte qui passe : rien.

##### A5 — la manipulation, au toucher

- **A5.1** Pincer franchement sur le bouton Trace : le panneau s'ouvre (onde de
  clic). Rester pincé : aucun second clic. Rouvrir puis repincer : nouveau clic.
- **A5.2** Ouvrir SET, changer d'onglet et cocher une case au pincement.
- **A5.3 — LA CAMÉRA QUI CLIGNE PENDANT UN GESTE.** Nommément demandé par la
  Slice 06 pour cette séance, mot pour mot : « le clignement de la caméra coûte
  le geste en cours ». Commencer à déplacer une étoile, puis masquer la main
  brusquement, ou passer une seconde devant une lampe. Attendu : l'objet est
  **annulé** proprement (retour à sa position d'origine), et non figé à
  mi-course ni posé au hasard. Refaire pendant un redimensionnement à deux
  mains.
- **A5.4** Déplacer, redimensionner par un bord, par un coin, puis à deux mains.
  Attendu : le cadre ne se retourne jamais, s'arrête à la taille minimale, et
  reste dans la zone de composition sûre.
- **A5.5** **Le défilement et la sélection.** Défiler une liste longue avec
  l'outil `Main` ; sélectionner du texte avec `Sélection` ; vérifier qu'un refus
  d'outil s'écrit bien sous la pastille (`OUTIL INAPPLICABLE`).
- **A5.6** Déposer un objet et vérifier qu'**aucun clic** n'est délivré dessus
  au relâchement. Le clic ne part que d'une capture qui n'a ni déplacé ni
  glissé.

##### A6 — outils, réglages, calibration

- **A6.1** Les **trois** outils de la palette se prennent à la main et le
  changement s'applique à chaud. Aucun outil désarmé ne doit rester visible :
  `Surligneur` et `Dessin` sont hors V1 et ne doivent plus apparaître.
- **A6.2** Chaque réglage s'applique **à chaud** et survit à un rechargement.
  « Réinitialiser les réglages » ne coupe pas la caméra et **ne touche pas** au
  profil de calibration.
- **A6.3** **Le parcours de calibration entier**, ses huit exercices (onze
  étapes mesurées, neuf écrans avec le rapport — Slice 07 adaptative), devant
  une vraie main. Ordre : main au repos, posture de réveil, pincement
  pouce-index, **tenir puis relâcher** (trois pincements tenus une seconde),
  pincement pouce-majeur, viser et cliquer, fenêtre (6A déplacer, 6B
  redimensionner, **6C déposer** dans le cadre en pointillé), bouger sans
  cliquer (7A, 7B). **Après chaque exercice, la revue** : elle ne doit jamais
  avancer seule (attendre une minute mains posées : rien ne bouge, et Bare
  Hands ne repasse pas en veille). Elle montre ce qui a été mesuré en clair
  (aucun nom de paramètre) et propose Refaire, Ajuster, Valider l'étape
  (absente si l'étape a échoué), Passer… (quatre raisons, puis la suivante) et
  Quitter. Refaire une étape déjà franchie (« refais le pincement » à la voix)
  y retourne, puis revient où on en était. Au clavier : Tab parcourt les
  actions, Entrée les déclenche, le focus arrive sur l'action principale de la
  revue et sur le titre de chaque nouvel écran — **jamais** sur une commande
  qui valide, passe ou enregistre : garder Entrée enfoncée ne fait rien de plus
  qu'une pression, et un double-clic sur « Valider l'étape » ne passe pas
  l'écran suivant. Échap referme le choix d'une raison ou « Ajuster » ; sinon
  il demande une seconde pression (dans les deux secondes) avant de quitter. « Viser et cliquer » joue quatre
  manches d'étoiles (petite, deux voisines, groupe serré, étoile mobile) : pincer
  l'étoile en pointillé quand l'anneau l'entoure ; une voisine prise ou un
  pincement dans le vide s'affichent, trois ratés passent la manche, et le
  rapport donne le compte des mauvaises étoiles, pincements dans le vide et
  bascules. Les étoiles n'ont pas de nom (l'anneau seul), et l'anneau
  s'affiche même si « Aperçu de la cible » est éteint, le temps de l'étape ;
  changer ce réglage pendant l'étape reprend la main, et la sortie ne le
  défait pas. Le dernier, « Bouger sans cliquer »
  (Slice 03 adaptative), compte ce qui se déclenche sans le vouloir — faux
  appui, faux clic droit, réveil, cible prise, curseur affiché — pendant huit
  secondes de mouvement ordinaire, puis pendant une visée sans pincement : le
  rapport en donne le compte. Attendu : chaque exercice se solde — réussi,
  échoué avec un motif, ou passé avec une raison — puis attend sa revue. Faire
  échouer une étape exprès (sortir du cadre) : la revue le dit, n'offre pas
  « Valider », et Passer… (une raison) continue le parcours (décision 31). Le
  rapport liste chaque étape (essais, raison d'un passage), « Sera enregistré »
  et « Déjà gardé pendant la séance », avec **Enregistrer** et **Quitter sans
  enregistrer** (ce dernier ne touche pas au profil). Puis vérifier que les
  seuils mesurés sont **appliqués** : le pincement doit changer de sensibilité
  après un enregistrement.
- **A6.4** **Il n'y a plus de parcours de tutoriel** (Slice 07B de l'affinage
  d'UI, décisions 10 et 17). Vérifier qu'aucune entrée Tutoriel n'existe : ni
  section ni case dans les réglages, ni entrée du menu du clic droit. La
  calibration est le seul parcours guidé, et c'est elle qui enseigne.
- **A6.5** Dire « lance le tutoriel » au cerveau : la **calibration** doit
  s'ouvrir, et JARVIS doit annoncer une calibration — jamais un tutoriel. Le
  reçu porte la phrase de dépréciation ; un JARVIS qui dirait « j'ouvre le
  tutoriel » est un défaut, pas une approximation.
- **A6.6** **Un enregistrement de diagnostic**, du début à la fin : le démarrer,
  faire une minute de gestes, l'arrêter, puis rejouer la trace et comparer deux
  configurations. Ouvrir le fichier dans `runtime/barehands-traces/` et
  **vérifier de ses yeux qu'il ne contient aucun point de main** — que des
  nombres et des noms d'un vocabulaire fermé.

##### A7 — le canal vocal (cerveau lancé)

- **A7.1** Dire « active les mains », « calibre », « montre-moi comment faire »,
  « sors de la surimpression », « désactive les mains ». Attendu : chacune
  atteint la page et **le reçu revient au cerveau**, qui répond en connaissance
  de cause. « Montre-moi comment faire » doit ouvrir la **calibration** : c'est
  elle qui enseigne depuis la Slice 07B.
- **A7.2** Demander une commande avec **aucune page ouverte**. Attendu :
  `barehands_no_visible_page`, et le cerveau le dit au lieu d'un succès
  optimiste.
- **A7.3** Demander une commande, puis **fermer l'onglet** aussitôt après sa
  remise. Attendu : `barehands_command_expired` avec `deliveries: 1` — « la page
  l'a prise et n'a pas répondu ». Redemander en une phrase doit marcher.
- **A7.4** **Deux onglets ouverts**, une seule commande. Attendu : **un** seul
  parcours démarre. C'est l'exclusivité de la remise, et elle ne se voit qu'avec
  deux onglets réels.
- **A7.5** Bare Hands éteint, demander « calibre ». Attendu : refus codé, et le
  cerveau propose d'allumer plutôt que de prétendre avoir calibré.

## Confirmation behavior

For a persistent memory write, Jarvis reads a summary of the requested content and waits. Exact accepted forms:

- approve: `oui`, `yes`
- deny: `non`, `no`

Other forms (including `ok`, `confirme`, sentences containing yes/no, or stale confirmations) do not execute the write.

## Memory

Canonical files are Markdown under configured `memory_dir`. Do not rely on `.jarvis/index.sqlite3` as data; it is a derived cache.

Rebuild:

```bash
python -m jarvis reindex
```

It is safe to delete `<memory>/.jarvis/index.sqlite3`; the next rebuild recreates search from Markdown.

## Configuration

Tracked defaults live in `config/jarvis.example.toml`; local `config/jarvis.toml` is ignored by Git.

The Control Center settings window (tab **Config**) lists the audio devices exposed by PortAudio. Select an input and an output, then use **Tester micro + sortie**: Jarvis records two seconds, requires a detected microphone signal, and replays the captured audio through the selected output. Save the selection and restart the Voice runtime to apply it to conversations and Porcupine. Everything else that window offers is described above, under "La fenetre de reglages".

Main environment overrides:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | required live provider credential |
| `OPENAI_BASE_URL` | provider base URL |
| `OPENAI_TRANSCRIPTION_MODEL` | STT model |
| `OPENAI_AGENT_MODEL` | Responses agent model |
| `OPENAI_TTS_MODEL` | speech model |
| `OPENAI_TTS_VOICE` | speech voice |
| `OPENAI_TIMEOUT_S` | provider timeout |
| `JARVIS_PTT_KEY` | global PTT key name |
| `JARVIS_MANUAL_WAKE_KEY` | Realtime Voice wake key; default `f9` |
| `OPENAI_REALTIME_MODEL` | Realtime model |
| `OPENAI_REALTIME_VOICE` | Realtime timbre; default `cedar` |
| `JARVIS_VOICE_TURN_MODE` | `auto` (server VAD, default) or `manual` (second key press) |
| `JARVIS_VOICE_STACK` | `openai_realtime` (default) or `gemini_live` |
| `JARVIS_VOICE_ARCH` | `legacy` (default, computed) or `continuous_brain`; see "Deux architectures vocales" below. The **Architecture** choice of the Control Center (tab Mode vocal) takes precedence; this variable only applies while that choice is left on "Par défaut" |
| `JARVIS_REFLEX_ENABLED` | cerveau réflexe du mode continu : `1` (défaut) ou `0`. La case **Cerveau réflexe (mode continu)** des réglages Voice passe devant ; la variable ne s'applique que tant que cette case n'a jamais été enregistrée |
| `JARVIS_REFLEX_DELAY_MS` | silence toléré avant que le réflexe parle ; défaut 1200. `0` = jamais. Le champ **Délai avant accusé de réception** du Control Center passe devant |
| `JARVIS_REFLEX_REQUIRE_WORK` | retour arrière : `1` n'autorise le réflexe que si Core a publié un `brain.work.started` corrélé. Défaut `0` depuis la remise en route du 18 septembre 2026 — cette exigence rendait le réflexe muet dès que le cerveau répondait sans déclarer de travail de fond |
| `JARVIS_ACTIVE_TIMEOUT_S` | useful-inactivity timeout of an ACTIVE voice session; default 90. `0` = jamais : seule la touche de réveil (F9) ou « Jarvis mute » met fin à la conversation. Toute autre valeur doit être >= 5. Le champ « Délai d'inactivité » des réglages du Control Center passe devant |
| `JARVIS_AGENT_CLI` | `claude` (default) or `codex` |
| `JARVIS_CLAUDE_MODEL` | model passed to `claude --model`; empty means the CLI default |
| `ANTHROPIC_API_KEY` | lists the real Claude models; the CLI itself can run on a subscription |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Gemini Live voice and its model list |
| `JARVIS_DATA_ROOT` | per-PC data root (SQLite state and scene, history, runtime memory); default `~/.jarvis/instances/<checkout>-<hash>/data` (one per checkout of the repo), outside git. First Core start adopts the old `./data` ([local-data.md](local-data.md)) |
| `JARVIS_MEMORY_DIR` | canonical Markdown root (V1 path) |
| `JARVIS_RUNTIME_DIR` | transient signal/log directory |
| `JARVIS_CONFIRMATION_TIMEOUT_S` | pending write confirmation expiry |
| `JARVIS_LOG_LEVEL` | diagnostic level |
| `JARVIS_LOG_CONTENT` | opt-in raw content logging; default false |
| `JARVIS_AUDIO_SAMPLE_RATE` | microphone capture sample rate |
| `JARVIS_AUDIO_INPUT_DEVICE` | explicit input device name (exact/substring match; missing configured device fails clearly) |
| `JARVIS_AUDIO_OUTPUT_DEVICE` | explicit output device name or PortAudio index for Realtime Voice |
| `JARVIS_AUDIO_RECORDING` | explicit audio recording in Core (default `1`); `0` removes the microphone source, starts refused `unsupported_source` ([capture.md](capture.md#audio-recording-slice-06)) |
| `JARVIS_SCREEN_CAPTURE` | desktop screenshot and screen recording in Core (default `1`); `0` removes the `screen` channel (refused `unsupported_source`) ([capture.md](capture.md#screen-capture-slice-07)) |
| `JARVIS_FFMPEG_EXE` | explicit ffmpeg binary for screen recording; default: the one of the `capture` extra (`imageio-ffmpeg`). Missing: recording refused `source_unavailable`, screenshots still work |
| `JARVIS_RECORDING_TRANSCRIPTION_MODEL` | OpenAI model for recording transcription; default `gpt-4o-mini-transcribe` (needs the OpenAI key, else transcription `unavailable`) |
| `JARVIS_CONTEXT_ENRICHMENT` | Context enrichment worker in Core (default `1`): keeps the active Context's `summary.md` from the activity ledger and describes screenshots; `0` turns it off: state `disabled`, no polling ([session-context.md](session-context.md#enrichment-worker-slice-08)) |
| `JARVIS_CONTEXT_ENRICHMENT_MODEL` | Claude CLI model of the enrichment worker; default `haiku`. Needs the configured agent CLI to be Claude **and** a native executable (`claude.exe`), else the worker is `unavailable`. Cost: see *Context enrichment cost* below |
| `JARVIS_TOOL_BRAIN` | Tool Brain runtime in Core, and the **single setting for who owns the screen**: `off` (default, nothing built, Jarvis executes as always), `shadow` (wakes on turns, intents, speech transitions, scene/Board changes and a safety tick, decides and records what it would do, executes nothing, Jarvis still owns the screen; [tool-brain-contracts.md](tool-brain-contracts.md) section 13) or `active` (action queue + executor; once the Tool Brain has completed a decision and stays healthy it owns the screen: Jarvis's screen-action tools are refused with `ui_delegated` and irreversible actions go through the guardrails, section 16). If the Tool Brain stops, its decider is unavailable or fails twice in a row, or its ownership file cannot be written, Jarvis gets the screen back automatically (trace `tool_brain.ownership.changed`, level warning, `fallback: true`; 60 s hold-down before the Tool Brain takes it again). Ownership is published in `runtime/tool-brain-ownership.json` (beat every 5 s, valid 20 s; missing or stale means Jarvis). Needs the configured CLI to be Claude with a native executable, else `unavailable` with backoff (and Jarvis keeps the screen). Whatever it does is on the conversation timeline (dock **CNV**): when it acted, a violet **Tool Brain** lane shows its wakes, decisions, one bar per queued action (queued to executed, cancelled, invalidated or failed) and ownership fallbacks; the events are in the canonical log (actor `tool_brain`, producer `core.tool_brain`, no arguments or reasoning), [tool-brain-contracts.md](tool-brain-contracts.md) section 17 |
| `JARVIS_TOOL_BRAIN_MODEL` / `JARVIS_TOOL_BRAIN_DECIDER` / `JARVIS_TOOL_BRAIN_TICK_S` | Tool Brain model (default `haiku`); `rule` swaps the model for the deterministic reference decider; safety tick period in seconds (default 30, minimum 5) |
| `JARVIS_BOARD_ENABLED` | enable board adapter |
| `JARVIS_BOARD_URL` | loopback board URL only |
| `JARVIS_VISUALIZER_ENABLED` | enable visualizer health/config |
| `JARVIS_VISUALIZER_URL` | loopback visualizer URL only |
| `JARVIS_DRIVE_PROVIDER` | `none` (default) or `google` |
| `GOOGLE_DRIVE_CLIENT_SECRET` | OAuth desktop client JSON; falls back to `GOOGLE_CALENDAR_CLIENT_SECRET` |
| `GOOGLE_DRIVE_TOKEN` | Drive token file, kept separate from the calendar token |

`JARVIS_BOARD_TOKEN` is an internal per-launch secret normally created by `dev_start.py`; do not persist it.

## Diagnostics

Runtime logs are JSONL in the runtime directory. Two different journals exist and
they do not have the same privacy behaviour.

- **V1 push-to-talk diagnostics** (`jarvis/diagnostics/logger.py`): transcript,
  prompt and body-like fields are redacted while `log_content` / `JARVIS_LOG_CONTENT`
  stays false, which is the default. Useful fields remain state/event names,
  durations and exception class.
- **v0.2 runtime journal** (`jarvis/runtime/journal.py`, `runtime/trace.jsonl` and
  `runtime/errors.jsonl`): `JARVIS_LOG_CONTENT` does **not** apply to it. Events
  such as `voice.transcript`, `voice.assistant`, `voice.brain_turn_submitted` and
  `voice.speech.*` deliberately carry up to 300 characters of what was said, because
  the Control Center **TRC** panel is built on reading it back. Nothing leaves the
  machine, and `runtime/` is outside the repository. The latency telemetry added on
  top of this journal carries identifiers, types and durations only - never text.
- **Raw agent reasoning** (Decision 43): the local CLI agent's reasoning is kept on
  this machine on purpose. `jarvis/runtime/claude_local.py:477` journals every raw
  `stream-json` event - `thinking` blocks included - into `runtime/trace.jsonl`, and
  `claude_local.py:284` renders them as `[réflexion] ...` in the Control Center
  console (same for Codex, `codex_local.py:156`). The scoped guarantee is narrower
  than "no chain-of-thought anywhere": no reasoning field exists in Core's domain
  state, none is persisted in conversation turns, none travels in `brain.state.updated`
  or in any speech request, and none reaches the Realtime surface. Inside the machine,
  the trace and the console carry it, which is what the debug console is for.

When troubleshooting provider errors, first run health, then inspect diagnostic
event names/error classes. Avoid turning on V1 content logging unless required and
remove those logs afterwards. If the local trace itself must be content-free, treat
that as a product change to the debug console rather than a setting that exists
today.

### Crashs natifs et morts de processus

Un `except` Python ne s'exécute que si l'interpréteur survit. Un crash natif —
typiquement une violation d'accès dans PortAudio ou Porcupine — tue le processus
sans dérouler la pile, et le code de sortie remonté par Windows est un NTSTATUS
signé : `-1073741819` vaut `0xC0000005` (ACCESS_VIOLATION). Trois mécanismes
capturent ces morts que le code applicatif ne peut pas voir :

| Fichier | Contenu |
| --- | --- |
| `runtime/crash-<role>.log` | dump `faulthandler` du processus vivant ; écrit au moment du signal fatal |
| `runtime/crashes/<role>-<horodatage>.log` | dumps archivés, après réinjection dans le journal |
| `runtime/logs/<role>.log` | sortie d'erreur complète de chaque enfant supervisé |

Les rôles sont `core`, `voice`, `ui` et `supervisor`. Au redémarrage, un dump
laissé par un processus mort est réinjecté dans `runtime/errors.jsonl` sous le
type `process.crashed`, et le superviseur journalise chaque mort d'enfant
(`supervisor.child_failed`) avec le NTSTATUS décodé, la fin de la sortie
d'erreur et le dump. Après cinq échecs en deux minutes, le rôle n'est plus
relancé et `supervisor.giveup` est journalisé plutôt que de boucler en silence.

Ces traces servent à identifier le point de rupture, en lisant les entrées qui
précèdent le crash dans `runtime/trace.jsonl`.

### Règle de sécurité des flux PortAudio

Un flux PortAudio ne doit **jamais** être fermé pendant qu'un thread écrit
dedans : la mémoire est libérée sous les pieds du code natif, ce qui produit une
violation d'accès qui tue le processus sans exception Python. Le piège est que
`asyncio.to_thread` n'interrompt pas son thread : annuler la tâche qui attend
l'écriture rend la main immédiatement alors que PortAudio écrit toujours.

`SoundDeviceRealtimeAudio` (`jarvis/runtime/realtime_audio.py`) applique donc
deux règles, à respecter pour toute évolution du chemin audio :

* écriture et fermeture du flux de sortie sont sérialisées par `_output_lock` ;
* la lecture est découpée en blocs de `OUTPUT_CHUNK_FRAMES` (100 ms) pour que la
  fermeture n'attende jamais plus d'un bloc.

L'arrêt du flux **d'entrée** reste volontairement synchrone sur la boucle :
`stop()` attend les callbacks en vol, et rester sur la boucle garantit que ce
qu'ils y ont planifié est en file avant le marqueur de fin d'entrée. Le déplacer
dans un thread ferait perdre les derniers blocs capturés.

### Lire la trace

Chaque entrée des panneaux **TRC** et **ERR** porte une icône de catégorie à
gauche (🔧 outils, 🎤 parole utilisateur, 💬 réponse, 🔊 audio, 🤖 agent Claude,
📅 agenda, ⚡ superviseur…), une pastille d'état à droite et se déplie sur le
JSON complet. La pastille se lit : vert = abouti, cyan = en cours, orange =
dégradé ou ignoré, rouge = échec. Elle vient du niveau de l'entrée, complétée
par le contenu — un résultat d'outil avec `executed: false` passe en orange même
si l'entrée est de niveau `info`.

### Chronologie de conversation (CNV)

Le bouton **CNV** du dock ouvre, en plein écran sur fond sombre flouté, la
chronologie en direct d'une conversation, lue dans le journal canonique de Core
(jamais dans `trace.jsonl`). Quatre lanes sur un même axe de temps qui descend :
**Utilisateur** (blanc, à gauche), **Jarvis · voix** (bleu clair : paroles en
entier avec une barre de durée exacte, réflexes en petites cartes ; points pour les mises en file ;
barres à droite pour les outils), **Brain** (orange : messages en entier ; points
pour les tours acceptés et paroles demandées ; barres de travaux à droite),
**Sous-agents** (blocs rouges : nom, description, durée, statut). Le texte public
n'est jamais coupé ; survoler ou focaliser un point affiche son libellé. Les
lanes prennent la largeur dont elles ont besoin. Les chevauchements restent visibles : une coupure de parole tombe à
l'intérieur de la parole qu'elle interrompt, un sous-agent couvre les tours qui
se déroulent pendant qu'il tourne. Un silence de plus de 6 s est replié en une
bande « N sans événement · axe replié ».

- **Conversation** : « Plus récente » suit la conversation active ; choisir une
  conversation l'épingle. **Session** fait défiler jusqu'au début d'une session.
- **Tout / Public** : *Tout* montre le diagnostic (travaux, sous-agents, outils,
  repères) ; *Public* ne garde que ce qui a été dit, entendu ou montré.
- **Échelle** : pixels par seconde (60 par défaut).
- **Plusieurs fenêtres** : une seule d'entre elles interroge Core ; les autres
  reçoivent les événements par relais et affichent « En direct · … · relayé par
  un autre onglet ». Un navigateur n'accorde qu'environ six connexions par hôte
  et une lecture en attente en occupe une : sans ce partage, six chronologies
  ouvertes suffisaient à ralentir toute l'interface. Une fenêtre cachée ne
  demande plus rien (« En pause ») et rattrape en revenant au premier plan ;
  fermer ou masquer la fenêtre qui lisait passe la main à une autre sans perdre
  d'événement.
- Clic ou Entrée sur une entrée qui n'est pas de l'utilisateur : détail (ids,
  statut, durée, latence depuis la parole utilisateur, raison d'interruption ou
  d'échec, parent et enfants) et, pour chaque événement, la ligne de trace
  expurgée (`/api/conversations/events/{event_id}/trace`) ou le lien vers la
  trace de la tâche dans le panneau Agents. ↑/↓ : entrée précédente/suivante ;
  ←/→ : lane voisine ; Échap : ferme le détail puis la vue.
- Une parole interrompue affiche le **texte envoyé à la lecture**, en italique,
  avec « coupé après N s entendues » : ce n'est pas le texte entendu.
- **Rechercher** (barre d'outils) : cherche dans ce qui a été dit, entendu ou
  montré, et dans les identifiants, types d'événement et codes d'état (jamais
  dans la trace ni dans le texte diagnostique) ; sans accents ni majuscules
  (« reunion » trouve « Réunion »). Toutes les conversations par défaut. Un
  résultat ouvre sa conversation et place le focus sur l'entrée, entourée.
- **Occupé** : Core ne fait qu'une recherche et deux transcriptions ou exports à
  la fois, pour ne jamais ralentir la voix ; au-delà il répond « Recherche déjà
  en cours » ou « Core est occupé » : réessayer un instant après. Fermer l'onglet
  pendant une recherche l'annule dans Core.
- **Transcription** : texte lisible rendu par Core depuis les seuls événements, aux heures locales du navigateur (fuseau écrit dans l'en-tête),
  *Simple* (ce qui a été dit et montré) ou *Détaillé* (plus travaux,
  sous-agents, outils et échecs avec leurs codes, lignes « -- ») ;
  **Télécharger .txt**. Une parole coupée y est annotée
  « [interrompu après N s entendues] ».
- **Exporter JSONL** : télécharge les événements canoniques de la conversation
  tels que stockés, une ligne JSON chacun, avec une ligne finale de contrôle. Le
  fichier n'est enregistré que s'il est complet ; sinon « Export incomplet » et
  **Réessayer**.

La pastille d'état dit toujours ce qui se passe : « Chargement », « En direct ·
N événements · dernier reçu il y a T », ou le problème réel (« Core
injoignable », « Jeton de session refusé par Core », « Origine refusée »…) avec
le compte à rebours de la prochaine tentative, le numéro d'essai, la durée de la
coupure et **Réessayer maintenant**. Rien n'est perdu pendant une coupure : la
vue reprend à son dernier curseur, sans doublon. Dépannage détaillé (lane voix
vide, sous-agent absent, trace non trouvée, lignes illisibles) :
[Conversation Events](conversation-events.md), « Timeline UI ».

#### Exporter, chercher, récupérer une conversation

- **Adresses directes** (Control Center, boucle locale uniquement) :
  `http://127.0.0.1:17654/api/conversations/export?conversation_id=<id>`,
  `/api/conversations/transcript?conversation_id=<id>&mode=detailed`,
  `/api/conversations/search?q=<mots>`. Sans Control Center : les routes Core
  `GET /v1/conversation-events/{export,transcript,search}` avec le jeton de
  `runtime/core.token`.
- **Lire un export hors ligne** : `read_export` puis `transcript_from_export`
  ou `reconstruct_export` (`jarvis/domain/conversation_event_export.py`) ;
  vérifier `complete` et `invalid_lines` avant de s'y fier. La transcription
  obtenue est identique octet pour octet à celle du Control Center.
- **Après un crash de Core** : rien à faire. Les événements acquittés sont
  durables ; au redémarrage Core réenregistre les tours utilisateur dont
  l'événement a été perdu. Les événements Brain des ~60 ms précédant le crash
  sont perdus (décision documentée). Les compteurs de pertes :
  `GET /v1/health` et `/api/status`, champ `conversation_events`.
- **Lignes illisibles** : jamais réparées ni supprimées ; comptées dans la
  vue, l'export (`skipped_rows`) et la transcription.
- **Ce qui est privé** : tout le journal (paroles de l'utilisateur et de
  Jarvis). Il ne quitte Core que par des routes locales authentifiées. Aucun
  événement ne contient de raisonnement caché, prompt, argument ou résultat
  d'outil, texte d'erreur de fournisseur ni secret : ni la transcription, ni
  l'export, ni la recherche ne peuvent en montrer. Un fichier exporté ou
  téléchargé est une copie hors de ces protections.
- **Taille et rétention** : environ 1,8 Ko par événement sur disque, 5 à 6
  événements par tour (≈ 400 Mo par an à 100 tours par jour). La rétention
  existe mais **n'est pas planifiée** : rien n'est supprimé aujourd'hui.
  Exporter avant de l'activer. Détails : [Conversation Events](conversation-events.md),
  « Operations ».

### Boards : le bouton du haut (liste rapide)

Le bouton **Board** en haut de l'écran montre toujours le Board actif, tel que
le serveur le confirme. Un clic (ou ↓) ouvre la liste de tous les Boards ; c'est
le geste de tous les jours. L'inspection profonde reste dans `WSP` (ci-dessous).

- **Lire la liste** : chaque ligne donne le titre, la nature (Générique,
  Réunion, Présentation) et la dernière ouverture (« ouvert il y a 3 h »,
  « jamais ouvert » ; l'heure exacte au survol). Le Board actif a le point
  plein, le cadre et « Actif » ; « En fond » signale un autre Board dont l'agent
  travaille encore.
- **Basculer** : cliquer un Board. Le bouton du haut compte les secondes
  (« Bascule · N s ») et ne change de titre qu'une fois le serveur d'accord ;
  un refus laisse le Board précédent et dit pourquoi.
- **Créer** : « Nouveau Board », un titre, la nature (Générique par défaut),
  « Créer ». Le Board n'est pas ouvert : choisissez-le ensuite pour y basculer.
- **Renommer ou changer la nature** : le crayon de la ligne ouvre le titre et
  la nature ; « Enregistrer » (ou Entrée) envoie seulement ce qui a changé,
  Échap annule. La ligne n'affiche la nouvelle nature qu'après la réponse du
  serveur. Changer la nature ne démarre ni réunion ni présentation.
- **Archivés** : le filtre « En service / Archivés » montre les Boards archivés
  à part. Ils ne s'ouvrent plus (pas de bascule) mais restent lisibles.
- **Inspecter** : l'icône flèche « ouvrir ailleurs » d'une ligne, archivée ou non, ouvre
  « Sessions & Boards » (bouton `WSP` du dock) directement sur ce Board
  (mémoire, artefacts, liaisons). Échap referme la vue et rend la main au
  bouton Board du haut.
- **Archiver** : l'icône boîte, après confirmation ; impossible pour le Board
  actif (basculez d'abord ailleurs).

Un refus s'affiche dans la liste avec sa phrase et, en petit, son code
(`invalid_board`, `core_unreachable`…). Si « Inspecter » ne peut pas ouvrir la
vue, la liste reste ouverte et le dit (`workspace_manager_missing`).

### Sessions & Boards (bouton `WSP` du dock)

Le bouton **WSP** ouvre « Sessions & Boards », une vue plein écran pour vérifier
où vit la mémoire de chaque Board et ce qu'elle contient. Tout y est lu sur le
serveur ; « Actualiser » relit tout, Échap ferme.

- **Vue d’ensemble** : la Session courante, le Board actif (et l'emplacement de
  sa mémoire, `boards/<board_id>/memory`), le Context actif, la liaison au
  premier plan (l'agent qui parle) et les éventuels problèmes de données.
- **Sessions** : l'historique complet, ouvert et clos, page par page ; une ligne
  dépliée montre ses Boards, ses liaisons, ses Contexts et son journal (les
  écritures de mémoire y apparaissent en `board.memory.*`).
- **Boards** : tous, archivés compris, avec leur nature (Générique, Réunion,
  Présentation) ; « Basculer sur ce Board » fait la même bascule que le bouton
  Board du haut.
- **Relations** : d'une Session vers ses Boards et liaisons, ou d'un Board vers
  sa mémoire, ses artefacts, ses références héritées (legacy) et ses Sessions.
- **Mémoire** : arborescence, lecture, recherche, et pour un Board non archivé
  création, remplacement, ajout, dossier, renommage et suppression. Supprimer
  demande une confirmation rouge dans le panneau : il n'y a pas de corbeille.
  Un Board archivé est en lecture seule.
- **Artefacts** : par Board, Session ou Context, filtrés par nature et date,
  avec leur provenance et les Boards auxquels ils sont liés.

Un refus s'affiche là où il a eu lieu, avec son code (`board_archived`,
`memory_conflict`…) et « Réessayer ». Une « recherche incomplète » veut dire
qu'une limite a arrêté la recherche, pas qu'il n'y a rien : précisez le dossier.

**Mise à jour vers cette version (schéma v8).** Au premier démarrage, Core
copie `jarvis.sqlite3` en `jarvis.sqlite3.v7.bak` (dossier `state/` de la
racine de données, [local-data.md](local-data.md)) puis ajoute la table des
liens Board-artefact ; rien n'est réécrit, la Session ouverte est reprise.
Le journal de Core le dit. Sens unique : un Jarvis d'avant cette version
refuse ensuite la base (« state DB schema 8 is newer than supported 7 ») sans
la modifier. Revenir : arrêter Jarvis, mettre de côté `jarvis.sqlite3` et ses
`-wal`/`-shm`, copier `jarvis.sqlite3.v7.bak` en `jarvis.sqlite3`, relancer
l'ancienne version ; ce qui a été écrit depuis la migration reste dans la base
mise de côté, les dossiers `boards/` restent sur le disque
([boards.md](boards.md#accepted-v1-limits), limite 9).

### Prefab library (bouton `PFB` du dock)

Le bouton **PFB** ouvre la bibliothèque partagée des prefabs de ce poste : les
fenêtres réutilisables que JARVIS et vous placez sur la scène. Tout est lu sur
Core à chaque ouverture ; « Actualiser » relit, Échap ferme (d'abord le
formulaire de fork s'il est ouvert, puis la vue), `/` va à la recherche. La
liste est un seul arrêt de Tab : ↑ ↓ Début Fin changent de prefab. Dans
l'aperçu, le prefab garde le clavier (cadre isolé) : Échap et `/` y restent ;
Tab ou Maj+Tab en sort, puis Échap ferme la vue (ou « × » en haut à droite).

- **Reconnaître d'un coup d'œil** : `Base` (cyan, cadenas) = livré avec
  JARVIS, jamais modifié ; `Base modifiée à votre demande` (ambre, crayon) =
  une base que JARVIS a modifiée parce que vous le lui avez demandé ; `Fork`
  (vert, branche) = une copie, avec « de `<id>` v`<n>` » sous la ligne ;
  `Custom` = créé de toutes pièces. Les mêmes boutons filtrent la liste ; la
  recherche porte aussi sur les alias (« todo », « tableau »…). Si
  l'historique d'un prefab ne peut pas être lu, la ligne affiche `Provenance
  inconnue` (rouge) et reste sous Fork et sous Custom ; choisissez-la pour
  réessayer, ou « Actualiser ».
- **Inspecter** : entrées (props, data, défauts, bornes), événements (`état`
  écrit dans la fenêtre, `signal` prévient JARVIS au tour suivant), versions et
  provenance. Pour une base modifiée, l'historique cite **vos mots exacts**
  et la date ; l'identifiant du témoin (l'événement de conversation qui porte
  vos mots) est replié sous « Témoin ».
- **Aperçu** : le prefab tourne avec ses données d'exemple ; ce que vous y
  cliquez s'affiche dans « Événements de l'aperçu » et n'est envoyé ni à Core
  ni à JARVIS. « Réinitialiser » repart de l'exemple.
- **Placer sur la scène** : une fenêtre avec les données d'exemple, à votre
  nom ; « Fermer et voir la scène » ferme la vue.
- **Forker en nouveau prefab** : identifiant (votre préfixe, par exemple
  `team.checklist-red`), titre, description et réglages simples (couleur
  d'accent…). La copie est publiée en version 1 sous le nouvel identifiant,
  l'original ne change pas. Un identifiant `jarvis.…` est refusé par Core
  (`base_protected`) : ce préfixe est réservé aux bases. Un identifiant qui
  existe déjà est refusé « Identifiant déjà pris » (avant l'envoi s'il est
  dans la liste, sinon par Core) : un fork publie toujours un nouvel
  identifiant. Si vous choisissez un autre prefab pendant la publication,
  elle continue ; son issue (publiée ou refusée) s'affiche dans un avis qui
  reste jusqu'à « Masquer », et la sélection ne bouge pas.

**Modifier un prefab de base** ne se fait pas ici : il n'y a pas de bouton,
exprès. Demandez-le à JARVIS, explicitement (« modifie le prefab de base
tableau : accent orange par défaut ») ; il publie une nouvelle version de la
base seulement si vos mots figurent dans un tour récent de la conversation,
et la vue l'affiche alors en ambre avec votre demande citée
([prefabs.md](prefabs.md), *Base-edit gate*). Un prefab publié par JARVIS
pendant que la vue est fermée apparaît à la prochaine ouverture.

La bibliothèque vit dans la racine de données du poste
(`prefabs/<id>/<version>/`, [local-data.md](local-data.md)) : un worktree ou
`jarvis-dst` a la sienne.

### Plein écran d'une surface (fenêtre de scène, prefab)

Une fenêtre de la scène (et la scène entière) peut passer en **vrai plein écran du navigateur**, sans bordure :
l'élément hôte qui contient le cadre du prefab reçoit `requestFullscreen()`. Ce n'est pas un grand panneau CSS, et
JARVIS ne le dit jamais plein écran avant que le navigateur l'ait constaté. Contrat : `docs/prefabs.md` › *Host
fullscreen*.

**Le plus simple : le menu de la fenêtre.** Un clic droit sur une fenêtre dessinée de la scène (ou la touche Menu)
propose **Plein écran**. C'est un vrai geste de votre part : la fenêtre passe en plein écran tout de suite, sans
invite. Les demandes de la voix ou d'un agent, elles, **arment** une invite (ci-dessous), parce que le navigateur
refuse le plein écran sans clic.

**Le navigateur exige un clic.** Une demande de la voix ou d'un agent n'entre donc pas : elle **arme** une invite
en haut de la fenêtre (« Plein écran demandé », bouton **Passer en plein écran**, **Annuler**, compte à rebours de
30 s). L'invite est dans la couche supérieure du navigateur : elle reste cliquable même quand une boîte de
dialogue du Control Center est ouverte. Un clic sur le bouton entre ; sans clic, l'invite disparaît à l'échéance et
le dit (« Personne n'a cliqué dans les 30 s … »). **Échap** quitte à tout moment, y compris quand JARVIS ne
répond plus : c'est le navigateur qui sort. À la sortie, la fenêtre retrouve sa place et le focus revient où il
était. Seul un onglet **visible** reçoit la demande : un onglet caché ne la prend pas, et son invite périmée
disparaît dès qu'il se remontre si l'armement a été retiré entre-temps.

Les commandes ci-dessous sont en **PowerShell** (Windows). Remplacez `<port>` par le port de votre Control Center.

Lire l'état (le journal du Control Center porte les lignes `fullscreen.*` ; la console du navigateur les lignes
`[fullscreen] …`) :

```powershell
Invoke-RestMethod http://127.0.0.1:<port>/api/fullscreen/state
```

`state` vaut `entered` | `exited` | `needs_gesture` (invite affichée) | `unsupported` | `refused` | `expired`, avec le
`code` et la phrase du navigateur quand il y en a un.

**Où lire l'`object_id` d'une fenêtre** : dans l'instantané de la scène, un objet par ligne (`object_id`, forme et
titre) :

```powershell
(Invoke-RestMethod http://127.0.0.1:<port>/api/scene).snapshot.objects |
  ForEach-Object { [pscustomobject]@{ object_id = $_.object_id; forme = $_.representation; titre = $_.payload.title } }
```

Simuler la demande d'un agent (ne démarrez/arrêtez pas votre JARVIS pour ça ; n'importe quel Control Center de test
sur un autre port et un autre `JARVIS_DATA_ROOT` convient) :

```powershell
$id = "<object_id de la fenêtre>"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:<port>/api/fullscreen/commands `
  -ContentType "application/json" -Body (@{ action = "enter"; object_id = $id } | ConvertTo-Json)
```

Réponse attendue : `state: needs_gesture` (jamais `entered`). Pour sortir : même commande avec
`@{ action = "exit" }`. `504 fullscreen_no_visible_page` = aucun onglet ouvert **et visible** ;
`504 fullscreen_command_expired` = la page a pris la commande et ne répond plus. Le clavier de navigation n'est lu
sur la fenêtre que si la demande porte `keys = "host"` (réservé à la lecture de présentation) ; par défaut
(`keys = "none"`) le plein écran ne touche jamais au focus d'un prefab avec un champ de saisie.

**Recette de vérification Humaine** (le sans-tête de la machine prouve l'entrée par clic, la sortie, la restauration,
l'invite cliquable sous une boîte modale et le bac à sable ; il ne prouve pas ce qui suit) :

1. *Menu.* Clic droit sur une fenêtre prefab, **Plein écran** : elle remplit l'écran sur fond noir, sans titre ni
   poignées, le contenu du prefab est vivant.
2. *Commande d'agent.* Lancer la commande ci-dessus avec l'`object_id` : l'invite apparaît ; cliquer **Passer en
   plein écran** : même résultat.
3. *Sans clic.* Relancer la commande et attendre 30 s : l'invite part avec sa notification d'échéance, rien n'a changé.
4. *Annuler.* Relancer la commande, cliquer **Annuler** (ou Échap dans l'invite) : l'invite part, le focus revient.
5. *Échap physique.* Entrer en plein écran, appuyer sur la touche **Échap** : sortie immédiate, fenêtre à sa place,
   focus rendu, `Invoke-RestMethod …/api/fullscreen/state` répond `exited`.
6. *Clavier (demande avec `keys = "host"`).* En plein écran, flèches, Page haut/bas, Espace, Début et Fin ne
   défilent pas la page et ne déplacent pas la sélection de la scène ; un clic dans le cadre ne les perd pas.
   Sans `keys`, rien n'est capté et un champ de saisie du prefab garde le focus.
7. *Plusieurs écrans.* Avec deux écrans, ajouter `display = "other"` à la commande : Chrome demande l'autorisation de
   gérer les fenêtres ; accepter puis cliquer l'invite : la surface s'ouvre sur l'autre écran
   (`display_selection: granted`). Refuser l'autorisation : le plein écran s'ouvre sur l'écran courant
   (`display_selection: denied`), sans erreur. Si l'autorisation consomme le clic, l'invite reste avec « cliquez de
   nouveau ».
8. *Onglet caché.* Avec deux onglets du Control Center, lancer la commande pendant que l'un est caché : c'est
   l'onglet visible qui reçoit l'invite.
9. *Mode fenêtre.* Après chaque sortie, la scène (taille, position et sélection des fenêtres) est inchangée.

Limites connues : Chrome/Edge seulement pour le choix de l'écran (Firefox et Safari entrent en plein écran sur l'écran
courant) ; les notifications du Control Center (toasts) ne se voient pas pendant le plein écran (seul l'élément
plein écran s'affiche) : les erreurs sont aussi dans le journal et la console ; l'invite d'autorisation « gestion
des fenêtres » est celle de Chrome.

### Rechargement à chaud d'une scène du Studio (recette de vérification Humaine)

Une modification de **source** d'une scène (gabarit, style, comportement, manifeste d'un prefab) se voit tout de suite dans
la fenêtre de cette scène, **sans toucher aux autres** et sans perdre ce que vous aviez réglé ou cliqué dans la scène.
Contrat : [presentation-studio.md](presentation-studio.md#hot-reload-contract-level-3-slice-06). Il n'y a pas encore d'écran
d'édition (Slice 07) : la recette passe par les routes du Control Center et par la lecture (Slice 12). Elle ne démarre pas votre
JARVIS vivant — **n'utilisez pas votre session de travail** : lancez un Core et un Control Center de test, sur un autre
port et une autre racine de données (`JARVIS_DATA_ROOT=<dossier de test>`), puis ouvrez la page de ce Control Center.

Commandes en **PowerShell** ; remplacez `<port>` par le port du Control Center de test, `<pid>`/`<vid>`/`<sid>` par les
identifiants de la Presentation, de la variante et de la scène (l'URL de base est
`$base = "http://127.0.0.1:<port>" + "/api/presentation-studio/presentations"` ; `Invoke-RestMethod "$base/<pid>"` les liste).

1. *Démarrer une lecture* (la scène doit figurer dans la partition de la variante ; la fenêtre est celle de la lecture, il n'y a
   plus de route provisoire) :
   `Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:<port>/api/presentation-studio/playback/start" -ContentType 'application/json' -Body (@{presentation_id='<pid>'; role='rehearsal'} | ConvertTo-Json)`.
   La fenêtre `studio-stage-<run_id>` de la lecture affiche la première scène ; cliquez **+1** dans sa scène plusieurs fois (si le
   prefab a un compteur). Pendant les étapes suivantes, la lecture **ne se met pas en pause et ne change pas de position** ; une
   scène que la lecture n'affiche pas est seulement ré-épinglée (« Version enregistrée », la lecture la vérifiera en y arrivant).
   Arrêtez la lecture à la fin (`.../playback/stop`).
2. *Bonne modification* : dans la console du navigateur, `JarvisStudioReload.instance.applySourceEdit({presentation_id:'<pid>', variant_id:'<vid>', scene_id:'<sid>', revision:<révision de la variante>, title:'Ma scène', files:{style:'.count{color:#ff7a59}'}})`.
   Attendu : une bande en bas à gauche « Rechargement de « Ma scène »… 1 s / 50 s » avec un bouton « Arrêter d'attendre », puis
   « Scène « Ma scène » rechargée » (verte, disparaît seule) ; **seule** cette fenêtre est redessinée, les autres ne clignotent
   pas ; la valeur cliquée est conservée ; la couleur a changé.
3. *Mauvaise modification qui ne monte pas* : même appel avec `files:{behavior:'function ( {'}`. Attendu : la fenêtre **ne
   change pas** (pas de cadre blanc, pas de bande dans la fenêtre), la bande reste rouge « Modification … annulée … retour à la
   dernière version valide », une notification apparaît ; la scène reste éditable (refaites l'étape 2).
4. *Refus avant publication* : `files:{template:'<iframe src=https://example.com></iframe>'}` → bande rouge « refusée avant
   publication · Rien n'a changé ».
5. *Valeurs qui ne tiennent plus* : un manifeste qui retire une valeur que la scène utilise est **refusé** ; avec
   `allow_state_reset:true` la scène est rechargée et la bande orange (qui reste) **nomme** ce qui a été retiré.
6. *Journal* : `Invoke-RestMethod "$base/<pid>/reloads"` liste les derniers (et `versions` : par scène, les versions vivantes et
   archivées de sa source, sans suppression ; l'archive se vide à la main, Core arrêté)
   rechargements (sans contenu) ; le visualiseur d'erreurs montre les échecs (`core.presentation_studio.reload_rolled_back`,
   niveau `warning`) ; la chronologie montre « Scène rechargée ».

Cas qui n'ont pas de recette automatique : un vrai redémarrage de Core entre deux étapes (couvert par un sous-processus tué dans
les tests), l'allure sur un vrai écran, et un navigateur dont l'onglet est caché. Ce dernier cas n'est pas prouvé par un test : ce qui l'est, c'est qu'une page qui
ne rapporte rien dans le délai donne « montage non confirmé » (`pending_mount`), jamais un faux succès, et qu'un rapport tardif
confirme ou annule ensuite. Si un onglet caché retarde le montage d'un cadre, vérifier à l'écran que c'est bien ce résultat qui
s'affiche, sans supposer le moment où le rapport arrivera.

### Presentations du Studio : sauvegarde et restauration

Les Presentations vivent dans la racine de données du poste, sous
`presentations/<presentation_id>/` (`presentation.json`, un fichier par variante dans
`variants/`, la partition dans `scores/`, la direction artistique dans `art_directions/`), jamais dans le dépôt ni dans une base SQLite
([local-data.md](local-data.md), [presentation-studio.md](presentation-studio.md)).

- **Sauvegarder** : copier le dossier `presentations/` entier, JARVIS arrêté (ou, à chaud, après
  une écriture terminée : chaque fichier est remplacé atomiquement, une copie ne voit jamais un
  fichier à moitié écrit, mais deux fichiers copiés à deux instants peuvent différer d'une
  révision). Copier aussi `prefabs/` : les scènes ne stockent que la référence exacte
  `(id, version)` des prefabs.
- **Restaurer** : remettre le dossier à sa place, sous la racine de données voulue, puis
  démarrer Core. Il retire seulement les restes d'écritures interrompues
  (`.staging-*`, `*.tmp`, trace `core.presentation_studio.swept`) ; il ne supprime ni ne réécrit
  jamais un document.
- **Vérifier** : `GET /v1/presentation-studio/presentations` rend les Presentations lisibles et, dans
  `problems`, chaque dossier refusé avec son code (`presentation_studio_corrupt_document`,
  `presentation_studio_unsupported_schema_version`). Une restauration faite avec une version de JARVIS
  plus ancienne que celle qui a écrit les fichiers est refusée document par document, sans perte :
  mettre JARVIS à jour.
- **Ne jamais** éditer un fichier à la main ni le supprimer sans en avoir fait une copie
  (règle du dépôt, `CLAUDE.md`) ; un dossier sans `presentation.json` est signalé, pas réparé.
- **Après un arrêt brutal ou une coupure** (Slice 08) : chaque commit acquitté est durable (fichier `fsync`é,
  remplacement atomique, dossier vidé), donc la Presentation est à la dernière révision acquittée, ou à celle
  qui était en cours si son remplacement avait eu lieu ; jamais en arrière, jamais tronquée. Au démarrage Core
  retire les `*.tmp` et `.staging-*` (jamais « promus », même plus récents que le document), puis recharge, derrière le démarrage
  (il ne le retarde jamais ; `last_recovery.complete` / `pending` disent où il en est), la
  variante active de chaque Presentation : bilan `core.presentation_studio.recovered`, et, par document
  illisible, `core.presentation_studio.recovery_failed` au niveau `error` (visible dans le visualiseur
  d'erreurs) avec son code typé (`presentation_studio_corrupt_document`,
  `presentation_studio_unsupported_schema_version`). Le bilan est `last_recovery` du service. Aucun repli
  silencieux : ni variante plus ancienne, ni `*.tmp`, ni `.bak` n'est chargé à la place. Restaurer une copie
  (`.bak` ou sauvegarde du dossier `presentations/`) est une décision humaine, JARVIS arrêté, après avoir copié
  le fichier abîmé. Une coupure de courant est protégée par le vidage du dossier après le remplacement ; si le
  disque ou le système de fichiers ment sur ses caches, aucune écriture applicative n'y peut rien.
- **Annuler / rétablir** : l'historique est en mémoire (bornes dures, évictions visibles) et ne survit pas à un
  redémarrage : `history_unavailable` avec la raison. Il n'est donc pas une sauvegarde ; la sauvegarde est le dossier
  `presentations/` (aucun instantané durable n'est conservé). `GET .../variants/{id}/history` dit ce qui est annulable,
  les bornes et ce qui a été évincé.

### Variantes du Studio : archive, restauration et reprise

Une branche (une variante) ne se supprime pas : **elle s'archive**, ce qui déplace son fichier de
`presentations/<presentation_id>/variants/` vers `presentations/<presentation_id>/archive/`
([local-data.md](local-data.md), [presentation-studio.md](presentation-studio.md#variant-graph-and-operations-contract-level-3)).
Archiver une branche archive aussi tous ses descendants ; la variante active ne s'archive pas tant qu'une autre n'est pas choisie.

- **Archiver** : toujours en deux temps. D'abord un plan, qui ne change rien et rend l'ensemble exact
  (numéros et titres) avec un jeton de confirmation valable 10 minutes, dans ce processus seulement :
  `POST /api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/archive-plan`. Puis, après
  avoir montré l'ensemble à l'utilisateur, `POST /api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/archive`
  avec ce jeton (`confirmation`). Sans jeton, ou avec le jeton d'un autre ensemble, d'un autre titre, d'une autre révision ou périmé, Core refuse
  (`presentation_studio_confirmation_required` / `presentation_studio_confirmation_stale`) et n'écrit rien.
- **Voir** : `GET /api/presentation-studio/presentations/{presentation_id}/graph?archived=1` liste les noeuds vivants et archivés
  (numéro, titre, parent, raison, auteur). `?check=1` ajoute un rapport complet en lecture seule (orphelins, fichiers manquants, doublons).
- **Restaurer (outil)** : `POST /api/presentation-studio/presentations/{presentation_id}/variants/{variant_id}/restore` remet la variante et ses
  ancêtres archivés (avec `{"with_descendants": true}`, aussi ses descendants archivés) ; c'est l'inverse exact de l'archivage, le numéro d'affichage est conservé.
- **Restaurer à la main** (Core arrêté, **après avoir copié** tout le dossier `presentations/<presentation_id>/` ailleurs) : déplacer
  `archive/<variant_id>.json` vers `variants/`, puis, dans `presentation.json`, déplacer l'objet de ce noeud de la liste `archived` vers la liste
  `variants` en retirant ses clés `parent_variant_id`, `archived_at`, `archived_by` et `batch_id` (garder `variant_id`, `variant_number`,
  `rationale`, `created_by`, `sources`, `preview_id`) ; ne jamais toucher `variant_counter`. Un noeud vivant doit avoir un parent vivant : restaurer d'abord les ancêtres.
  Au moindre doute, utiliser l'outil ci-dessus : il vérifie le graphe avant d'écrire.
- **Copie du manifeste v1** : la première opération du graphe sur une Presentation créée avant la Slice 16 réécrit `presentation.json` en schéma 2 et garde l'ancien
  texte exact dans `presentation.json.v1.bak` (une seule fois, jamais remplacée, jamais supprimée par Core). Pour revenir à une version de JARVIS d'avant la Slice 16 : Core arrêté, copier
  le dossier, puis remettre ce fichier sous le nom `presentation.json` (les variantes créées depuis sont alors des orphelins à garder ou à copier ailleurs).
- **Un seul Core par racine de données** : deux Core (ou deux services) sur la même racine se disputent le compteur : chaque appelant reçoit « créé », un numéro est donné à
  plusieurs variantes et le manifeste en liste moins que créées ; les fichiers en trop sont des orphelins rapportés au démarrage suivant.
- **Après un arrêt brutal** : au démarrage Core accorde les fichiers au manifeste (`core.presentation_studio.reconciled`, `warning`) : un
  archivage ou une restauration interrompus *avant l'écriture du manifeste* n'a pas eu lieu, les fichiers déjà déplacés retournent à leur place. Un
  numéro d'affichage réservé par un branchement interrompu est perdu (un trou, jamais une réutilisation).
- **Orphelins** (`core.presentation_studio.reconcile_orphans`, `warning`) : un fichier de variante ou un document lié (`scores/`, `art_directions/`) que le manifeste ne
  nomme pas est le reste d'un branchement interrompu. Core le **rapporte et n'y touche pas** (jamais adopté, jamais supprimé). Pour le garder :
  le copier ailleurs. Pour le retirer : le copier d'abord, puis le supprimer à la main, Core arrêté. Un noeud dont le fichier est introuvable
  (`missing`, niveau `error`) est une perte : restaurer le dossier depuis une sauvegarde.

### Assemblage d'une présentation (studio, Slice 11)

Contrat : [presentation-studio.md](presentation-studio.md#authoring-contract-slice-11). Le cerveau soumet **un** brouillon (brief, scènes, partition,
direction artistique) ; Core le vérifie avec une porte de qualité (48 règles codées, tableau dans le contrat) puis le stocke en **une seule transaction**.
Il n'y a pas encore d'outil MCP (Slice 21) : les deux routes servent aux tests et au futur outil, le relais du Control Center force l'acteur `user`.

- **Vérifier sans rien écrire** : `POST /api/presentation-studio/authoring/check` rend le rapport (`failures` bloquent, `warnings` informent, `skipped` dit
  ce qui n'a pas pu être contrôlé). `POST /api/presentation-studio/authoring/assemble` livre (201, tous les identifiants créés) ou refuse (400 `presentation_studio_draft_refused`,
  rapport complet, **rien d'écrit**).
- **Ce qu'un arrêt brutal peut laisser** (preuve : `test_presentation_studio_authoring_crash.py`, vrai `kill`) : rien ; des versions de prefab publiées
  sous `presentation-studio.*` qu'aucune variante n'épingle (inoffensives, immuables) ; un dossier `presentations/.staging-*` sans manifeste. Jamais une présentation à moitié écrite :
  le dossier entier, partitions et directions artistiques comprises, est publié par un seul renommage.
- **Au démarrage** : le balayage de Core retire les `.staging-*` (`core.presentation_studio.swept`). Les versions de prefab que rien n'épingle se **rapportent à la demande** :
  `GET /v1/presentation-studio/authoring/reconcile` (Core, jeton porteur ; lecture seule, pas relayé à la page ; `core.presentation_studio.authoring_reconciled`, `warning` s'il y en a). Elles ne sont jamais adoptées ni supprimées ;
  la rétention (docs/prefabs.md) archive une version `presentation-studio.*` que rien n'épingle. Un échec en cours d'assemblage écrit
  `core.presentation_studio.authoring_unreferenced` (`warning`, les `id@version` concernés).
- **Rien du contenu du brouillon n'est journalisé** (ni titre, ni phrase, ni valeur) : seulement des identifiants, des codes et des comptes.
  Les réponses ne portent pas non plus le texte de l'auteur : un nom de clé inconnu est compté, une valeur refusée est remplacée par `<value>`.
- **Adopter une direction d'un brouillon exploratoire** : `POST /api/presentation-studio/authoring/finalize` (la porte `directed` sur la variante stockée ; sans elle, rien ne garantit qu'un candidat léger soit un exposé complet). `activate` seul reste le choix de l'utilisateur.
- **Ce que les tests automatiques ne prouvent pas** : que le vrai modèle suive la politique (appels d'outils, questions posées, qualité du premier jet). C'est la porte des Slices 21 et 22 ;
  la preuve de cette Slice est un banc scripté (`tasks/jarvis-interactive-presentation-studio/slices/11-authoring-planner-first-draft/evidence/`), pas une trace de Claude.

### Lecture d'une présentation (studio, Slice 12) : vérification humaine

Contrat : [presentation-studio.md](presentation-studio.md#playback-runtime-contract-level-3-slice-12). Les tests automatiques couvrent
la machine d'états, la fenêtre de stage, les fenêtres annexes, le clavier (fenêtré et plein écran, sur la VRAIE page du Control Center servie
par un Core isolé) et le plein écran dans un vrai Chrome sans tête ; ce que le sans-tête
ne prouve pas est à regarder une fois, sur un vrai poste, dans une instance isolée (`JARVIS_DATA_ROOT` à part, jamais le Jarvis vivant) :

1. **Clavier réel** : lancer une lecture (rôle « Vous présentez »), cliquer la fenêtre de la scène, puis flèches, Espace, Début, Fin, `P`, Échap
   (pause) : la bande dit où l'on en est à chaque touche, une touche n'agit qu'une fois, et les mêmes touches avec le focus ailleurs (un champ de
   saisie, une autre fenêtre) ne font rien. La bande ne recouvre pas le sélecteur de mode (en bas à gauche).
2. **Plein écran** : « Plein écran » dans la bande (un clic) ; la scène remplit l'écran, la bande n'y est pas, les touches agissent une fois ; **Échap**
   (la vraie touche) sort du plein écran, la bande revient, la lecture n'a **pas** changé d'état (ni pause surprise, ni saut).
3. **Deux écrans** : même essai avec un second écran branché (l'invite « gestion des fenêtres » est celle de Chrome) ; la bande reste sur l'écran du Control Center.
4. **Détour** : demander à la voix une ressource annexe, la voir apparaître, revenir : elle disparaît de la scène, la lecture reprend à la même place.
5. **Arrêt brutal** : pendant un détour, tuer Core (`taskkill` de CE processus seulement, jamais le Jarvis vivant), le relancer : au démarrage, la ligne
   `core.presentation_studio.playback_reclaimed` dit combien d'objets ont été repris et la scène n'a plus ni fenêtre de stage ni fenêtre annexe ; le fichier
   `state/presentation-studio-stage-ledger.json` a disparu.
6. **Mode** : « Jarvis présente » passe le mode en SIMPLE pendant la lecture et le rétablit à l'arrêt ; changer le mode à la main pendant la lecture
   l'arrête (« mode changé par vous ») sans le remettre de force ; la préférence enregistrée du Board n'a pas bougé.
7. **Cues** (pile vocale OpenAI seulement, sinon l'écoute d'ambiance est sourde) : dire la phrase de la cue suivante déclenche l'élément, le dire deux fois
   ne le déclenche qu'une fois (suiveur : Slice 13). Noter la pile utilisée. Recette complète : *Suivi des cues à la voix* ci-dessous.

8. **Suivi vocal absent** (architecture `legacy` ou `duplex`, ou pile ambiante sans suiveur) : lancer « Vous présentez » ; 10 s plus tard la bande
   dit « Suivi vocal indisponible » avec la raison, le sélecteur de mode dit « Refusé par la voix », et la lecture continue au clavier. Noter l'architecture.
9. **Séquence verrouillée** : arriver à un élément qui héberge une séquence ; « Suivant » est refusé pendant qu'elle tourne (Core l'exécute, la bande
   montre l'étape et le temps) ; « Sortir de la séquence » (ou `S`) continue après elle, toujours.
10. **Registre illisible** (instance isolée) : après un arrêt brutal, abîmer `state/presentation-studio-stage-ledger.json` (le tronquer), relancer Core : la
   scène n'a plus de fenêtre `studio-stage-*` / `studio-aux-*`, le fichier est resté à côté en `.corrupt-<horodatage>`, la ligne
   `stage_ledger_scan_reclaimed` dit combien d'objets ont été repris.

Après un arrêt brutal, une fenêtre `studio-stage-*` ou `studio-aux-*` encore visible est un défaut à signaler avec la ligne `playback_reclaim_failed` du
journal ; ne pas la supprimer à la main avant d'avoir copié `scene.sqlite3` (règle du dépôt).

### Présentation par Jarvis (studio, Slice 14) : vérification humaine

Contrat : [presentation-studio.md](presentation-studio.md#jarvis-presenter-and-locked-sequences-level-3-slice-14). Les tests automatiques couvrent le pilote avec une
fausse pile vocale et une horloge simulée, la VRAIE pile de parole (`SpeechScheduler`, sa porte de présentation, l'observateur de mode) avec une surface vocale
factice, un Core réel et la page réelle dans un vrai Chrome sans tête. **Rien n'a été dit sur une vraie voix** : l'audible est à vérifier par vous, dans une instance
isolée (`JARVIS_DATA_ROOT` à part, jamais le Jarvis vivant), avec un casque ou des haut-parleurs et un micro réels :

1. **Une ligne dite** : préparer une présentation dont les éléments « Jarvis » portent un `text` court, lancer « Jarvis présente » (le clic ou la voix, demande
   explicite). La bande dit « Jarvis présente », le mode passe en SIMPLE (rétabli à l'arrêt), la voix dit la ligne **telle qu'écrite** (pas reformulée), la bande
   affiche « Jarvis parle » pendant la ligne, puis l'élément suivant démarre tout seul après la fin de la ligne. Un élément « silence » ne dit rien et dure sa
   cible. Un élément « vous » (note) : Jarvis se tait et attend votre « Suivant ».
2. **Une séquence verrouillée** (et la fenêtre « démarrage ») : arriver à un élément qui héberge une séquence avec une première étape parlée. La bande dit « attente du début de la parole »,
   puis la séquence démarre **quand la voix a commencé à générer les premiers mots** ; les étapes visuelles arrivent à leurs décalages (regarder le chronomètre de la bande
   contre l'écran), la dernière étape parlée est dite à son décalage (la voix peut avoir une latence propre : la noter), la fin tombe à la durée exacte. **Fenêtre connue** : le départ (t0) est la *demande de génération* de la première
   ligne, pas le premier son ; noter l'écart entre le premier visuel et le premier son (le worst case : la ligne annulée dans cette fenêtre, par exemple en
   parlant par-dessus dès l'apparition du premier visuel : les visuels de l'étape 0 sont déjà là, la lecture est en pause). Refaire l'essai avec une ligne
   d'étape remise tôt pendant qu'une précédente parle encore (même clé de parole) : elle démarre en retard, sans fausse erreur de départ avant 10 s après la fin de la précédente.
3. **Interruption** (parler par-dessus Jarvis, à voix haute, pendant une ligne) : la ligne est coupée, la lecture passe **en pause** (« Interrompu : Jarvis attend
   votre continuer »), elle ne repart **pas** toute seule, même après votre question et la réponse. « Continuer » (le bouton, ou la voix) : la ligne reprend **depuis
   son début**, jamais au milieu d'une phrase. Sur un élément « non interruptible » (`refuse`), parler par-dessus ne met pas en pause (la chorégraphie continue).
4. **Séquence interrompue** : interrompre pendant une séquence `pause_resume` (la pause prend effet à la frontière de l'étape, les décalages restants sont
   conservés au « Continuer ») ; avec `abort_to_recovery`, « Continuer » ramène au point de reprise déclaré.
5. **Échecs visibles** : (a) débrancher le micro/la voix ou couper Voice, lancer une ligne : au bout de 10 s la bande dit pourquoi (« La voix n'a pas commencé la
   ligne à temps ») et propose « Continuer » ; (b) redémarrer Core juste avant de lancer : « Jarvis n'a pas pu prendre la ligne » (aucune conversation en cours) ;
   (c) dans l'instance isolée, forcer PRESENTATION à la main pendant la lecture : la lecture s'arrête (« mode changé par vous ») et Jarvis ne dit plus rien.
6. **Fin et arrêt** : à la dernière ligne la lecture s'arrête d'elle-même (`last_run.reason: completed`), le mode précédent est rétabli ; « Arrêter » coupe tout
   (une ligne déjà partie finit ou est coupée par votre voix) et rétablit le mode ; Core tué au milieu : au redémarrage le mode est celui du Board, jamais le
   mode temporaire.

Noter la pile vocale utilisée (OpenAI Realtime, GPT-Live, autre) et la latence entre l'envoi d'une ligne et ses premiers mots (`presenter_sequence_started`,
`lag_ms`). Un défaut se signale avec les lignes `core.presentation_studio.presenter_*` du journal de Core ; elles ne contiennent jamais le texte.

### Suivi des cues à la voix (studio, Slice 13) : vérification humaine

Contrat : [presentation-studio.md](presentation-studio.md#cue-following-contract-level-3-slice-13) ; règle d'autorité : [presentation-addressed-turn.md](presentation-addressed-turn.md) §12, *Amendment (Slice 13)*.
Les tests automatiques couvrent le comparateur, le suiveur, les garde-fous structurels et un rejeu complet (lane réelle, suiveur réel, service de lecture réel) ; **ils ne prouvent pas** une vraie salle, un vrai micro ni
la transcription OpenAI. **Environnement requis : la pile vocale OpenAI** (sans elle la lane ambiante est sourde : seul l'appel explicite marche, et la bande doit dire `suiveur : absent`). Instance isolée
(`JARVIS_DATA_ROOT` à part, **jamais** le Jarvis vivant), score d'essai à 3 ou 4 éléments dont deux avec une cue (phrases courtes et distinctes, par exemple « passons à la suite », « voilà la conclusion »).

1. **Noter la pile** (fournisseur, modèle de transcription) et lancer une lecture « Vous présentez » ou une répétition silencieuse. La bande passe `suiveur : en attente` puis `connecté` en quelques secondes.
2. **La bonne phrase** : dire la phrase de la cue suivante comme une indication de scène (« Bon, passons à la suite. »). L'élément avance, une fois ; la dire deux fois de suite n'avance qu'une fois. Noter le délai entre la fin de la phrase et l'avancée (transcription incluse).
3. **Ce qui ne doit rien faire** : parler normalement pendant une minute ; dire la phrase au milieu d'une longue phrase ; la citer (« quand je dis passons à la suite... ») ; la nier ou la demander en question ; la dire à une autre personne dans la pièce ; une phrase de la cue d'après (non armée) ; « Merci Jarvis, passons à la suite » (le nom de Jarvis n'importe où dans la phrase met le suivi en pause). Aucune avancée.
4. **L'adresse explicite gagne** : dire « Jarvis, passons à la suite » (ou appuyer sur la touche et la dire) : Jarvis répond à la demande adressée comme d'habitude, la cue **n'avance pas** par ce chemin ; attendre 4 s, redire la phrase seule : elle avance.
5. **Pause et reprise** : mettre en pause ou lancer un détour, dire la phrase armée avant : rien ; reprendre : la cue est de nouveau possible (nouvelle génération).
6. **Pannes visibles** : arrêter Core (`taskkill` de CE processus seulement) pendant une lecture : la ligne `presentation.studio.follower_degraded` apparaît **une fois**, aucune avancée, et `follower_recovered` quand Core revient ; couper le micro : le suiveur reste `following` sans rien entendre (la bande ne peut pas le savoir, c'est une limite).
7. **Vie privée** : dans `runtime/trace.jsonl` de l'instance, chercher un mot rare de ce qui a été dit dans la pièce (hors phrases adressées à Jarvis) : il ne doit apparaître **nulle part**. Les seules lignes du suiveur sont `presentation.studio.*` (id de cue, règle, deux positions, comptes).
8. **Rapporter** : pile utilisée, nombre de bonnes phrases dites / avancées, faux déclenchements (la phrase dite par quelqu'un d'autre, ou au milieu d'une phrase ordinaire) avec ce qui a été dit **en mots**, jamais l'enregistrement.

Une cue dite avec un complément (« passons à la suite de l'enquête... »), répétée dans la même phrase ou après un long préambule **ne se déclenche pas** : c'est voulu (un cue manquée se rattrape au clavier, un faux déclenchement non) ; le noter, ne pas le corriger. Limites connues à ne pas « corriger » en vérification : la lane n'a pas d'identité de locuteur (une personne qui dit exactement la phrase comme indication de scène la déclenche) ; le suiveur est en français ; il y a toujours la latence de la transcription.

### Agenda : réel ou en mémoire

Sans `JARVIS_CALENDAR_PROVIDER=google` (avec `GOOGLE_CALENDAR_CLIENT_SECRET` et
`GOOGLE_CALENDAR_TOKEN`), Core démarre sur un agenda **en mémoire**. Les
rendez-vous y sont bien créés, mais ils ne rejoignent aucun agenda réel et
disparaissent à l'arrêt de Core.

Ce n'est plus silencieux : Core journalise `calendar.backend` au démarrage
(niveau `warning` si l'agenda est en mémoire), et **chaque résultat d'outil
calendrier porte un bloc `calendar`** :

```json
"calendar": {"backend": "in-memory", "persisted": false}
```

Le modèle Realtime le reçoit avec le résultat, ce qui lui permet de dire où le
rendez-vous a réellement atterri au lieu d'annoncer une création trompeuse.

### Google Drive

Drive est **désactivé par défaut** : `JARVIS_DRIVE_PROVIDER=none`. Une fois
activé, le même adaptateur sert deux consommateurs — la voix Jarvis, et Claude
Code via un serveur MCP local. Un seul client OAuth, aucun service tiers dans la
boucle.

#### Mise en place (une fois)

1. Dans la [console Google Cloud](https://console.cloud.google.com/), créer (ou
   réutiliser) un projet, puis **activer l'API Google Drive**.
2. Écran de consentement OAuth : type « Externe », et s'ajouter comme
   utilisateur de test — sans cela le consentement est refusé tant que l'app
   n'est pas publiée.
3. « Identifiants » → « Créer des identifiants » → « ID client OAuth » →
   **Application de bureau**. Télécharger le JSON.
4. Renseigner `.env` à la racine du projet :

```
JARVIS_DRIVE_PROVIDER=google
GOOGLE_DRIVE_CLIENT_SECRET=C:\Users\<vous>\.jarvis\google_client_secret.json
GOOGLE_DRIVE_TOKEN=C:\Users\<vous>\.jarvis\google_drive_token.json
```

5. Autoriser une fois, navigateur à l'appui :

```powershell
.\.venv\Scripts\python.exe -m jarvis drive-auth
```

La commande écrit le jeton (permissions 600 quand la plateforme le permet) et
compte les fichiers visibles pour confirmer que l'accès fonctionne.

Le client OAuth est partageable avec l'agenda (`GOOGLE_DRIVE_CLIENT_SECRET`
retombe sur `GOOGLE_CALENDAR_CLIENT_SECRET` s'il n'est pas défini), mais **les
jetons restent séparés** : un jeton porte les portées accordées, et les mélanger
invaliderait silencieusement l'un des deux accès.

#### Portée

Une seule portée est demandée : `https://www.googleapis.com/auth/drive`, soit la
lecture **et** l'écriture sur tout le Drive. Pour restreindre, remplacer
`GoogleDriveBackend.SCOPES` par `.../auth/drive.readonly` (lecture seule) ou
`.../auth/drive.file` (uniquement les fichiers créés par Jarvis), puis supprimer
le fichier de jeton et relancer `drive-auth` : changer une portée exige un
nouveau consentement, qu'un simple rafraîchissement ne demande jamais.

#### Ce que Jarvis peut faire à la voix

`drive_search`, `drive_get`, `drive_read` sont en lecture seule et s'exécutent
directement. `drive_create`, `drive_update`, `drive_delete` et `drive_share`
**demandent confirmation** (`oui`/`non` exact), y compris la création : un
fichier de trop dans un espace distant et partagé n'est pas rattrapable par
Jarvis, contrairement à un fichier local. Pour assouplir, passer `confirm=False`
sur l'entrée voulue de `POLICIES` dans `jarvis/security/v2_policy.py`.

`drive_delete` **met à la corbeille** au lieu de supprimer : le fichier reste
récupérable 30 jours depuis l'interface Drive. Le résultat renvoie
`trashed_file_id`, pas `deleted_file_id`, pour que la voix dise ce qui s'est
réellement passé.

Les documents natifs (Docs, Sheets, Slides) n'ont pas d'octets à télécharger :
`drive_read` les exporte automatiquement en markdown, CSV ou texte. Ils ne
peuvent pas être écrasés par `drive_update`, qui le refuse explicitement.

Comme pour l'agenda, chaque résultat porte un bloc d'origine :

```json
"drive": {"backend": "google", "persisted": true}
```

Sans Drive configuré, les outils répondent `deny` avec un message explicite
plutôt que d'échouer sur une trace technique. Il n'y a **aucun repli en
mémoire** : un faux Drive donnerait la certitude d'avoir déposé un fichier qui
n'existe pas.

#### Le même Drive depuis Claude Code

`python -m jarvis drive-mcp` sert les sept mêmes outils en MCP stdio. Enregistré
une fois :

```powershell
claude mcp add jarvis-drive --scope user -- C:\Projects\jarvis\.venv\Scripts\python.exe -m jarvis drive-mcp
```

`--scope user` le rend disponible dans tous les projets ; `--scope local` le
limiterait à Jarvis. Vérifier avec `claude mcp list`, retirer avec
`claude mcp remove jarvis-drive --scope user`.

Côté MCP, la politique de confirmation de Core **ne s'applique pas** : c'est le
système d'autorisations de Claude Code qui arbitre les appels d'outils. Le
serveur construit l'adaptateur au premier appel et refuse de lancer une
autorisation OAuth interactive : en stdio, tout ce qui s'écrit sur la sortie
standard est du protocole, et une fenêtre de consentement bloquerait le serveur
sans qu'aucun message n'atteigne l'utilisateur. D'où `drive-auth` d'abord.

### Agent Claude local : deux vues, une conversation

`ClaudeLocalAgent` lance `claude -p --input-format stream-json` : le même agent
que Claude Code interactif (33 outils, Bash, édition de fichiers, MCP), avec une
conversation continue tant que stdin reste ouvert — un seul `session_id` sur
tous les tours. Ce qu'il n'a pas, c'est une interface texte : stdio est branché
sur des tuyaux, il n'existe donc **aucune fenêtre à afficher**.

| Vue | Ce que c'est | Bouton |
| --- | --- | --- |
| **Console Windows** | le vrai `claude` interactif, TUI complète, dans sa propre fenêtre | 🖥️ Console Windows |
| **Historique** | représentation lisible du flux `stream-json` (réflexion, outils, coût), dépliable | Historique |

La console relance `claude --resume <session_id>` avec `CREATE_NEW_CONSOLE`, donc
sur **la même conversation**. Une session Claude ne pouvant pas être écrite par
deux processus à la fois, l'agent piloté par tuyaux est arrêté au passage : la
console prend la main, et la rend à sa fermeture (l'agent redémarre alors sur la
même conversation, `--resume` étant automatique). Tant que la console est
ouverte, relancer l'agent est refusé explicitement plutôt que de corrompre la
session.

Endpoints : `POST /api/agent/console/open`, `POST /api/agent/console/close`,
`GET /api/agent/transcript?limit=`.

### Subtask state in Core

The Control Center relays the normalized state of Claude subtasks to Core,
which also records its own jobs there (`docs/ARCHITECTURE.md`, "Core work
state"). The Agents panel and the brain both read Core's copy (see "What the
Agents panel shows" below). To see it raw, with Core running:

```powershell
$token = Get-Content runtime\core.token
Invoke-RestMethod http://127.77.0.1:17653/v1/work/snapshot -Headers @{ Authorization = "Bearer $token" }
```

(`JARVIS_CORE_HOST`, `JARVIS_CORE_PORT` and `JARVIS_CORE_TOKEN_FILE` change these
defaults.) It holds no prompt and no trace, only status, label, activity,
summary, model and counters, 64 items at most. It lives in memory: after a Core
restart it is rebuilt within about 30 s from the Control Center; subtasks of a
Control Center that was killed stay `running` there until the Control Center is
started again. Order of starts does not matter, and Core being down never slows
the agent: the trace shows `work.ingress_unavailable` (warning, once) then
`work.ingress_restored`. An `agent.work_state_failed` or `work.ingress_rejected`
error in the ERR panel is a relay bug, not an agent failure.

### What the Agents panel shows

The sub-agent cards (status, label, current activity, model, start/end, elapsed
time, summary, error class) come from Core through the Control Center's
read-only `GET /api/work`: the same store, `store_id` and revision the brain
reads for "où en sont mes tâches ?". Elapsed time is computed in the browser
from Core's `started_at` / `ended_at` and the current time. The brain card (the
agent process itself: PID, session, console) is not Core work and still comes
from the Control Center.

| What you see | Meaning |
| --- | --- |
| "Source : état normalisé Core · révision N" above the list | normal: cards are Core's state; N is the revision to compare with `/v1/work/snapshot` and `core.brain.work_context` in the trace |
| Details view, "État normalisé · Core (fait foi)" | Core's fields, including `error_class` (e.g. `process_stopped`, `producer_restarted`, `timeout`) and the Core identifier (`external_id`) |
| Details view, "Diagnostic fournisseur · brut, non autoritaire" | what only the Claude stream knows: sub-agent type, last tool, depth, provider id, `tool_use_id`; never used as the task's state |
| Trace view, "Trace brute du fournisseur · diagnostic" | the raw stream-json of that subtask (`/api/agent/tasks/{task_id}/trace` — the segment accepts a provider task id or a Core `work_key`) |
| Yellow banner "Core indisponible : … Affichage dégradé : projection locale du Control Center …" | Core is stopped, restarting, or refused the read. The cards shown are the Control Center's own tracker, labelled non-authoritative; the brain does not see them. Start Core; within one poll the banner disappears |
| "Aucune trace fournisseur pour ce travail" in the trace view | Core knows the work but the Control Center has no stream for it (Control Center restarted, subtask pruned from its history, or a Core job) |
| "Autres travaux Core" section | Core work that is not a brain sub-agent (Core jobs) |
| "Aucun sous-agent suivi pour ce CLI." | Codex is the active agent: it publishes no verified subtask format, so nothing is invented |
| The subagent count on the dock badge and in the top bar | not always Core's. It follows the cards only while the Agents tab is open with Core readable; otherwise it is the Control Center's own tracker (`/api/status`), which can differ from the list below it for one poll. Hover it: the tooltip says "décompte local du Control Center, non autoritaire" whenever it is not Core's |

After a Core restart the revision restarts low under a new `store_id`; the panel
treats it as a new store, not as an old answer, and relearns the subtasks within
about 30 s (the relay's resend). A late HTTP answer carrying an older revision of
the same store is ignored, so a card never goes back from "terminé" to "en
cours". `/api/agent/tasks` is still served unchanged for compatibility and
diagnostics.

## La boucle voix → Claude → voix

C'est la fonction fondamentale de JARVIS : une interface vocale vers un agent
qui agit sur cet ordinateur.

> Cette section décrit l'architecture **`legacy`**, celle qui tourne par défaut.
> En mode `continuous_brain`, l'outil `claude_task` n'existe plus et
> `ClaudeGateway` n'est même pas construite : c'est Core qui joint l'agent. Voir
> « Deux architectures vocales » plus bas.

```
votre voix ──► OpenAI Realtime (oreilles)
                    │  outil claude_task
                    ▼
              processus Voice ──HTTP──► Control Center ──► agent Claude
                    │                                          │
                    │◄────────── texte de la réponse ──────────┘
                    ▼
          OpenAI Realtime (voix) ──► vous
```

Le modèle Realtime ne répond pas de lui-même aux demandes portant sur la machine
ou le projet : sa consigne (`OPERATING_RULES`) lui impose d'appeler l'outil
`claude_task` en transmettant la demande au plus près de vos mots, d'annoncer
brièvement qu'il s'en occupe, puis de restituer le résultat à voix haute. Les
rappels et l'agenda gardent leurs outils Core dédiés.

`claude_task` est le seul outil qui **ne va pas à Core** : il est intercepté
dans `RealtimeConversationBridge` et transmis à `ClaudeGateway`, qui joint le
Control Center sur `POST /api/agent/ask`. Toute panne (agent arrêté, Control
Center injoignable, délai dépassé) revient sous forme de phrase prononçable
plutôt qu'en exception qui casserait le tour.

| Variable | Rôle |
| --- | --- |
| `JARVIS_UI_PORT` | port du Control Center joint par Voice (défaut 17654) ; Core en tire l'adresse de retour OAuth des plugins MCP (« Plugins MCP externes ») |
| `JARVIS_CLAUDE_TIMEOUT_S` | délai maximum d'une tâche Claude (défaut 600) |
| `JARVIS_CLAUDE_PERMISSION_MODE` | mode d'autorisation du CLI (défaut `bypassPermissions`) |

### Tâches longues

Une tâche réelle (écrire un document, analyser des logs) dépasse couramment la
minute. Deux garde-fous existent pour qu'elle ne soit pas tuée en route :

* **Le délai d'activité utile ne s'applique pas pendant une tâche Claude.**
  Le bridge rafraîchit le compteur toutes les `CLAUDE_KEEPALIVE_S` secondes tant
  que `claude_task` est en vol. Sans cela, `JARVIS_ACTIVE_TIMEOUT_S` (90 s par
  défaut) coupait la session vocale avant que le résultat n'ait où revenir.
* **Un tour abandonné n'empoisonne pas le suivant.** Quand le délai est dépassé,
  Claude continue son travail et son `result` arrive en retard : il est
  explicitement ignoré au lieu d'être livré comme réponse à la question suivante.

* **La connexion Realtime est maintenue pendant l'attente.** Après le commit du
  micro, plus rien n'est écrit sur le websocket : une tâche d'une minute le
  laisse silencieux assez longtemps pour qu'il soit fermé, et le résultat
  n'a alors plus où revenir. Le bridge le ping au même rythme que le battement
  d'activité.
* **Une connexion perdue termine le tour, elle ne tue pas Voice.** Elle est
  journalisée en `provider.disconnected` (niveau `warning`, donc absente de la
  liste d'erreurs) et le runtime repart en veille, prêt pour le prochain réveil.
  Une vraie erreur du fournisseur (`realtime.error`) continue de remonter.

### Console de debug et voix : qui tient la conversation

Ouvrir la console pendant qu'une tâche vocale tourne **l'interrompt** : la
console prend la main sur la session, l'agent piloté est arrêté. C'est
volontaire, et le tour vocal est débloqué immédiatement avec un message
prononçable (`agent.console_interrupt`, niveau `warning`) au lieu d'attendre le
délai complet.

En revanche, **la voix n'est jamais bloquée**. Une session Claude ne pouvant pas
être écrite par deux processus, une demande vocale arrivant pendant que la
console tient la conversation ouvre simplement une **nouvelle** session
(`agent.session_forked`, niveau `warning`) au lieu d'échouer. La console garde
la conversation que vous êtes en train de regarder, la voix continue sur la
sienne, et la reprise avec `--resume` redevient automatique dès que la console
est fermée — que ce soit par le bouton du panneau ou en fermant la fenêtre.

### Autorisations : pourquoi le défaut est « tout autoriser »

En headless, **personne ne peut répondre à une demande d'approbation**. Avec le
mode `default` du CLI, Claude répond « j'ai besoin de votre autorisation pour
créer ce fichier » et n'agit pas : l'agent devient inutile en vocal. JARVIS
lance donc le CLI avec `--permission-mode bypassPermissions`.

**Cela signifie que l'agent exécute sans confirmation tout ce que vous lui
demandez à la voix** — écriture de fichiers, commandes shell, suppression.
Le mode se change dans Settings (« Autorisations Claude ») ou via
`JARVIS_CLAUDE_PERMISSION_MODE` ; les valeurs acceptées sont `bypassPermissions`,
`acceptEdits`, `dontAsk`, `auto`, `manual`, `plan`. Le mode retenu est journalisé
à chaque démarrage de l'agent (`agent.start`, champ `permission_mode`) et la
console de debug hérite du même, pour que les deux vues se comportent pareil.

### Nettoyer la liste d'erreurs

Le panneau **ERR** du Control Center archive les erreurs traitées (`Archiver`)
et affiche l'archive (`Erreurs archivées`). L'archivage déplace les entrées de
`runtime/errors.jsonl` vers `runtime/errors-archive.jsonl` en les horodatant :
le badge se vide, rien n'est perdu, et `runtime/trace.jsonl` reste intact.

### Scène constellation — vue d'ensemble

Point d'entrée pour l'utilisateur ; chaque paragraphe renvoie à la section qui
détaille.

**Ce que c'est.** Une carte persistante du travail de JARVIS, dessinée derrière
les commandes du Control Center : chaque sous-agent devient une **étoile**, ses
résultats deviennent des **artefacts** reliés à l'étoile (liens trouvés,
fichiers, e-mails…), et le cerveau peut y montrer une note ou une fenêtre. La
scène appartient à Core (fichier `data/state/scene.sqlite3`) : un rechargement,
un autre onglet ou un redémarrage retrouvent la même scène. Le travail terminé
**reste** jusqu'à ce que vous le rangiez.

**L'activer.** **Allumée par défaut** : sur une installation neuve, sans réglage
enregistré ni variable d'environnement, la scène est rendue et le cerveau reçoit
ses outils d'affichage à son prochain démarrage. Rien à faire pour s'en servir.

1. **SET** → onglet **Expérimental** → section « Scène constellation » : la case
   « Afficher la scène et donner ses outils au brain » est déjà cochée. La
   décocher éteint la scène dans toutes les fenêtres ouvertes en une seconde,
   sans recharger ; la recocher la rallume aussi vite. Le choix est enregistré,
   et un `false` enregistré l'emporte sur le défaut.
2. L'encadré dit si le brain en cours a les outils **et** la consigne
   d'affichage. Sinon, « Redémarrer le brain… » puis confirmer : le brain repart
   sur une **nouvelle conversation** (la conversation en cours n'est pas reprise,
   parce qu'une conversation reprise garde son ancienne consigne) ; les
   sous-agents en cours sont interrompus, la confirmation dit combien. Un brain
   lancé avant la première lecture du réglage n'a pas besoin de ce redémarrage :
   avec le défaut allumé, il part déjà avec ses outils.
3. Pour éteindre : décocher (la scène disparaît aussitôt de la page), puis même
   redémarrage pour retirer les outils au brain.

Si la case est grisée avec « Imposé par la variable d'environnement
JARVIS_SCENE_ENABLED », la variable du Control Center décide : la retirer et
relancer le Control Center pour choisir dans l'onglet. Seul le brain **Claude**
reçoit les outils ; avec Codex, seul l'affichage suit la case. Détail :
« Scène constellation : outils d'affichage du cerveau », paragraphe **Activer**.

**Ce qui apparaît tout seul** (sans tour du cerveau, allumée ou non) : une étoile
par sous-agent Claude et par tâche de fond de Core, reliée à son parent ; son
état en signal secondaire (anneau, pastille) ; un signal d'attention en cas
d'échec, de blocage ou d'interruption. Jamais une étoile par commande shell,
fichier ou URL. Voir « ce que Core y projette tout seul » et « ce que l'on voit
dans le Control Center ».

**Ce que le brain peut faire** (outils `jarvis-display`) : lire la scène et le
détail d'un objet, trouver des objets, créer et modifier notes, fenêtres et
capsules, les masquer ou les relier, grouper le résultat d'un travail terminé en
**un** artefact par travail et par catégorie, et, pour une vérification
visuelle (« regarde l'écran »), capturer la scène. Depuis le 19/09/2026 il
**dispose** aussi de la scène comme vous : il archive, épingle, désépingle et
déplace un objet que vous avez épinglé, dès que vous le lui demandez et sans
vous renvoyer au Control Center. La règle est celle que vous avez posée : ce que
vous pouvez faire dans l'interface, JARVIS doit pouvoir le faire sur commande.
Ce qui lui reste refusé n'est plus une question de propriété mais de couche : il
ne recrée pas une étoile `agent`/`job` (elles naissent du runtime seul),
il n'écrit ni `exec_state` ni `work_ref` (ils reflètent Core, ils se lisent), et
il n'**arrête** rien depuis la scène — arrêter une tâche n'est pas un geste de
scène, il n'existe pas d'opération d'arrêt dans le domaine. Voir « outils
d'affichage du cerveau » et « les artefacts ».

**Ce que vous pouvez faire** (souris, clavier, Barehands ; détail : « agir sur les
objets ») :

| Geste | Comment |
| --- | --- |
| déplacer (et donc épingler) | glisser, ou Maj+flèches |
| épingler / désépingler | menu (clic droit, appui long au doigt ou au stylet, Maj+F10) |
| masquer, puis réafficher | menu « Masquer » ; pastille « N objets masqués · afficher » |
| changer de forme | menu « Afficher en point / capsule / fenêtre » |
| archiver un objet | menu « Archiver… » ; une étoile emporte ses signaux, **pas** ses artefacts |
| archiver en groupe | « Archiver les travaux terminés (N objets)… » (terminés, en échec, annulés, interrompus) et « Archiver les artefacts orphelins (N)… » (artefacts dont l'étoile est archivée) |
| arrêter | « Arrêter la tâche… » pour une tâche de Core seulement ; un sous-agent du brain ne s'arrête qu'avec le brain entier |

Aucune archive ne s'annule en V1.

**Redémarrages.** Rechargement : même scène, rien n'est replacé. Core redémarré,
Control Center allumé : les étoiles en cours passent un instant « état inconnu »,
puis reprennent leur vrai état ; le travail terminé et les artefacts restent
identiques. Voir « redémarrages et « état inconnu » ».

**Captures.** Seul le brain en demande une, jamais un bouton ; seule une page du
Control Center **ouverte et visible** la dessine (sans page : refus au bout de
5 s). Image de la scène seule (ni dock, ni panneaux, ni chronologie), au plus
1280×720, gardée dans `runtime\scene-captures\` (5 fichiers, 24 h). Voir
« outils d'affichage du cerveau », **Capture visuelle**.

**Confidentialité.** Tout reste sur la machine : titres des sous-agents, résumés,
adresses des artefacts sont enregistrés dans `data/state/scene.sqlite3` même
quand l'affichage est éteint, et l'historique des objets archivés n'est jamais
élagué en V1. La trace (`runtime/trace.jsonl`) ne garde que des identifiants et
des comptes, jamais le texte d'une note ni une image. Ce que le brain lit de la
scène (texte, capture) part vers son modèle comme le reste de la conversation.
Limites de confiance : `docs/SECURITY.md` §13.

**Limites connues.** 512 objets actifs (≈ 400 étoiles) : au-delà, la pastille
« Scène pleine » propose l'archivage groupé et les nouvelles étoiles attendent.
Zone de composition prévue à partir de 1280×720 : une fenêtre plus petite peut
cacher des bords sous les commandes. Glisser au doigt (tactile) jamais vérifié.
**Bare Hands glisse** depuis la Slice 06 — voir « ce qu'une main peut saisir, et
les deux façons de tirer » — mais **n'ouvre pas de lien** : un pincement n'est
pas une activation utilisateur au sens du navigateur, donc rien qui demande un
nouvel onglet ne part d'une main. Une page par profil de navigateur tient
la lecture de la scène : avec la chronologie ouverte dans cinq fenêtres ou plus,
la page ralentit. Un Control Center arrêté sans être relancé laisse ses
sous-agents « en cours ». Le brain juge lui-même : il peut parler d'un résultat
de mémoire plutôt qu'en relisant l'artefact. Une question sur l'écran
(« regarde l'écran », « est-ce que ça se chevauche à l'écran ») demande une
capture, une question de structure passe par la lecture ; la consigne le dit
depuis le Slice 11, mais c'est le modèle qui tranche.

**Dépanner en premier.**

| Symptôme | Que faire |
| --- | --- |
| rien ne s'affiche, case cochée | recharger la page ; si la case est grisée, voir la variable d'environnement ci-dessus |
| l'encadré « brain » reste orange | « Redémarrer le brain… » ; un échec s'affiche en rouge avec la cause, et dans la console `[scène] scene.brain_restart_failed` |
| « Réglage de scène non enregistré » | lire la cause affichée ; les réglages refusés sont aussi dans `runtime/trace.jsonl` (`settings.agent.rejected`) |
| le brain a les outils mais ne crée aucun artefact | conversation reprise avec l'ancienne consigne (`agent.start` `resumed: true`) : « Redémarrer le brain… » depuis l'onglet Expérimental, pas depuis le panneau Agents |
| « Scène figée — Core injoignable » | démarrer Core ; la page reprend seule |

Tables complètes : dans chaque section « Scène constellation » ci-dessous.

### Scène constellation : ce que Core y projette tout seul

Sans attendre le cerveau, Core pose dans la scène une **étoile** par travail
réel (voir `docs/ARCHITECTURE.md`, « Runtime scene projection »). La projection
tourne dès que Core démarre, que l'affichage de la scène soit activé ou non.

| Ce qui tourne | Dans la scène |
| --- | --- |
| un sous-agent lancé par l'agent Claude (outil `Agent`, tâche `local_agent`) | une étoile `agent`, identifiant `claude:<id de la tâche>`, titre = description de la tâche |
| un job de Core (y compris une tâche de fond du back brain) | une étoile `job`, identifiant `job:<id du job>`, titre = nature du job |
| un sous-agent lancé par un sous-agent | une étoile de plus, reliée à son parent par un lien `parent_of` |
| une commande shell de fond (`local_bash` : `npm test`, `git log`…), une lecture de fichier, une recherche, une URL | **rien** |
| un travail en échec, interrompu ou bloqué | un signal `attention` accroché à son étoile (titre = classe d'erreur, court message) |

**Pourquoi une commande shell n'apparaît pas.** C'est voulu (décision 4 du
handoff) : une étoile représente un travail que l'on peut suivre et relire, pas
chaque appel d'outil. Un agent lance des dizaines de commandes par tâche ; les
dessiner noierait les sous-agents. Elles restent visibles dans le panneau
**Agents** du Control Center et dans la trace de l'agent. Si une tâche est
d'abord vue sans nature puis reconnue comme sous-agent, son étoile apparaît à
ce moment-là.

Ce que la projection **ne fait jamais** :

- elle ne retire pas une étoile terminée : une étoile finie reste en place, son
  état (`exec_state`) passe à `completed`, `failed`, `cancelled` ou
  `interrupted` ; la ranger est un geste délibéré — le vôtre depuis le Control
  Center, ou celui du cerveau quand vous le lui demandez — jamais un effet de la
  projection ;
- elle ne place, ne masque, ne déplace ni n'archive rien : la position est
  décidée par l'affichage, le cerveau ou l'utilisateur ;
- elle ne ressuscite pas une étoile archivée, même si le travail donne encore
  des nouvelles ;
- elle ne change jamais la catégorie d'une étoile après sa création, et ne
  réécrit pas une charge (titre, résumé) que le cerveau ou l'utilisateur ont
  modifiée — sauf un cas : après un redémarrage de Core, une charge dont seul le
  résumé a été réécrit (titre gardé) peut être remplacée au rafraîchissement
  suivant du travail.

Signaux. Un seul signal par travail, mis à jour sur place. Quand le travail
repart (bloqué puis relancé, interruption levée), le signal est **retiré** : son
lien vers l'étoile disparaît, l'objet reste avec l'état atteint. Un échec
définitif garde son signal.

**Scène pleine.** La scène garde au plus 512 objets actifs, et une étoile
terminée n'est jamais retirée automatiquement : après quelques centaines de
sous-agents, la scène se remplit. Tant que Core tourne, rien n'est perdu :

- les nouvelles étoiles (et les signaux sur des étoiles existantes) sont mises
  **en attente** (au plus 1 024 ; au-delà, les plus anciennes terminées sont
  oubliées d'abord) ;
- **limite : cette attente est en mémoire.** Si Core redémarre, elle est
  perdue ; ne reviennent que les travaux encore connus de Core ou renvoyés par
  le Control Center (qui renvoie l'état de ses sous-tâches à Core après un
  redémarrage) ;
- `/v1/health` le dit : `scene.saturated: true`, `scene.objects` et
  `scene.object_limit` (même bloc dans `/api/scene` du Control Center) ; le
  cerveau et l'utilisateur ne peuvent plus rien créer non plus (`scene_full`) ;
- **que faire** : archiver des étoiles terminées. Dès qu'une place se libère,
  les étoiles en attente apparaissent sans attendre de nouvelle activité (au
  plus tard 30 s) : d'abord les sous-agents encore en cours, puis les travaux
  terminés, les plus anciens d'abord dans chaque groupe.

Vérifier dans `runtime/trace.jsonl` (niveau info sauf mention) :

| Entrée | Sens |
| --- | --- |
| `core.scene.projection_reconciled` | la projection a relu tout l'état de travail : au démarrage (`reason: start`), après des événements perdus (`revision_gap`), après une réinitialisation du travail (`store_changed`) ou au retour de la scène (`scene_unavailable`) |
| `core.scene.star_created` | une étoile est née (`object_id`, `kind`, `source`, `status`) |
| `core.scene.star_finished` | une étoile a fini (`object_id`, `source`, `status`) : à l'écran, anneau vert et coche pour une fin normale, rouge et croix pour un échec ; une seule ligne par étoile, rien d'autre ne bouge |
| `core.scene.signal_raised` / `core.scene.signal_retired` | un signal posé / retiré |
| `core.scene.projection_unavailable` (avertissement, une fois par panne) | la scène ne répond pas (fichier refusé au démarrage, écriture en échec) : le travail continue, la projection réessaie jusqu'à 30 s d'intervalle |
| `core.scene.projection_restored` | la scène répond de nouveau ; `suppressed` compte les tentatives manquées ; la projection a tout réconcilié |
| `core.scene.projection_failed` (erreur, panneau **ERR**, une fois par type) | un travail n'a pas pu être projeté (défaut logiciel) ; les autres continuent |
| `core.scene.projection_conflict` (avertissement) | un objet du cerveau ou de l'utilisateur porte déjà l'identifiant que la projection voulait utiliser : il est laissé intact |
| `core.scene.projection_saturated` (avertissement, au plus une fois toutes les 10 minutes) | scène pleine : `objects`, `object_limit`, `pending` ; `suppressed_episodes` compte les épisodes de saturation tus depuis le précédent avertissement (par exemple une étoile archivée par nouveau sous-agent) ; les créations attendent |
| `core.scene.projection_pending_overflow` (avertissement, une fois par épisode) | plus de 1 024 créations en attente : les plus anciennes sont oubliées |
| `core.scene.projection_desaturated` | plus aucune création en attente (rattrapées, ou abandonnées) ; `deferred` et `dropped` comptent l'épisode ; seulement pour un épisode annoncé par un avertissement |

Dépannage :

| Symptôme | Cause probable | Que faire |
| --- | --- | --- |
| un sous-agent tourne mais aucune étoile | l'agent n'est pas celui du Control Center (Codex, sous-agent interne d'un job : pas d'observation), ou Core ne reçoit pas l'état des sous-tâches (`work.ingress_unavailable` côté Control Center) | vérifier `GET /v1/work/snapshot` : pas d'élément `kind: agent` → problème d'ingestion, pas de scène |
| l'élément existe dans `/v1/work/snapshot` mais pas d'étoile | `kind` n'est pas `agent`/`job`, ou l'étoile a été archivée (`archived_ids`), ou la scène est indisponible (`projection_unavailable`) | lire `/v1/health` (`scene.state`) et la trace |
| de nouveaux sous-agents tournent mais aucune étoile n'apparaît, `scene.saturated: true` dans `/v1/health` | scène pleine (`core.scene.projection_saturated`) | archiver des étoiles terminées ; les étoiles en attente arrivent aussitôt |
| après un redémarrage de Core, une étoile affiche « état inconnu depuis le redémarrage » | normal pendant la grâce (60 s) : l'état de travail de Core est reparti vide, le Control Center n'a pas encore redit ses sous-agents | attendre ; si le Control Center tourne, l'état revient en une trentaine de secondes. Sinon l'étoile passe « interrompu » avec un signal à la fin de la grâce |
| une étoile passe « interrompu » avec le signal « non revu après le redémarrage de Core » alors que le sous-agent tournait | le Control Center n'a rien renvoyé pendant la grâce (arrêté, ou Core injoignable pour lui : `work.ingress_unavailable` dans sa trace) | vérifier le Control Center ; dès qu'il redit ce travail, l'étoile reprend son état et le signal est retiré |
| après un arrêt brutal du **Control Center**, des étoiles restent « en cours » | le Control Center n'a pas été relancé (Core n'a aucun délai d'expiration pour lui), ou la nouvelle instance ne joint pas Core (`work.ingress_unavailable` dans sa trace) | relancer le Control Center : sa première connexion à Core interrompt les anciens sous-agents en une seconde environ |

### Scène constellation : redémarrages et « état inconnu »

La scène est enregistrée sur disque ; l'état des travaux de Core ne l'est pas.
Voici ce qui se passe à chaque redémarrage (détail : `docs/ARCHITECTURE.md`,
« Restart reconciliation »).

| Ce qui redémarre | Ce que montre la scène |
| --- | --- |
| **le navigateur** (rechargement de la page) | la même scène, relue d'un coup, puis les changements au fil de l'eau |
| **Core**, le Control Center restant allumé | les étoiles encore en cours passent un instant à « état inconnu depuis le redémarrage » (anneau pointillé pâle, point atténué, badge « ? ») ; le Control Center redit l'état de ses sous-agents en une trentaine de secondes, et chaque étoile reprend son vrai état, sans signal |
| **Core et le Control Center**, ou Core seul pendant que le Control Center reste arrêté | « état inconnu » pendant la **grâce** (60 s), puis **interrompu** avec un signal « non revu après le redémarrage de Core » ; si le travail est redit plus tard, l'étoile reprend son état et le signal est retiré |
| **une tâche de Core** (job) en cours au moment de l'arrêt | **interrompue** avec le signal « Core redémarré », dès le démarrage ; un job qui s'était terminé juste avant l'arrêt garde sa vraie issue (terminé, en échec…) |
| **le Control Center** seul | dès que la nouvelle instance joint Core (environ une seconde), Core interrompt les sous-agents de l'ancienne (signal « Control Center redémarré »), même si rien n'a encore été relancé ; si le Control Center reste arrêté, ils restent « en cours » |
| **le cerveau** (CLI Claude) | ses sous-agents en cours passent **interrompu** avec un petit signal « processus arrêté » |

Ce qui **ne change jamais** au redémarrage : une étoile terminée, ses artefacts,
les notes et fenêtres du cerveau ou de l'utilisateur, les positions, les
épingles, ce qui est masqué, et ce qui a été archivé. Rien n'est supprimé.

**« État inconnu depuis le redémarrage »** veut dire : Core ne sait plus si ce
travail tourne, et personne ne le lui a encore redit. Ce n'est ni « en cours »
ni une panne : pas d'animation, pas d'alerte. Le menu de l'étoile le rappelle
(« État inconnu depuis le redémarrage de Core ») et ne propose pas d'arrêt ;
« Archiver les travaux terminés » ne la prend pas, puisque le travail peut
reprendre. On peut l'archiver seule.

**La grâce** dure 60 s par défaut : deux fois la période à laquelle le Control
Center renvoie tout son état. Réglage de diagnostic uniquement :
`JARVIS_SCENE_RESTART_GRACE_S` (secondes, dans ]0, 3600] : plus de 0, au plus 3600) dans
l'environnement de `python -m jarvis core` ; sous 30 s, des sous-agents vivants
seraient interrompus à tort. Une valeur refusée garde 60 s et laisse
`core.scene.restart_grace_invalid` (avertissement) dans la trace.

Dans `runtime/trace.jsonl` :

| Entrée | Sens |
| --- | --- |
| `work.ingress_token_refreshed` (info, côté Control Center, une fois par redémarrage de Core) | le Control Center a relu le jeton de Core et renvoyé aussitôt l'état de ses sous-agents |
| `core.scene.restart_marked` (info, une fois au démarrage, juste après que Core est prêt) | `marked` étoiles passées à « état inconnu », `already_unknown` déjà inconnues (arrêt brutal pendant une grâce précédente), `tracked` suivies, `terminal_untouched` terminées laissées telles quelles, `job_outcomes` jobs dont l'issue a été relue en base, `grace_s`, `sample` (16 identifiants au plus) |
| `core.scene.restart_grace_expired` (info, une fois à la fin de la grâce) | `reobserved` redites à temps, `interrupted` interrompues avec signal, `deferred` en attente d'une place (scène pleine), `left` archivées ou tranchées entre-temps, `failed` |
| `core.scene.restart_star` (niveau `debug`, une par étoile) | le détail : `unknown`, `reobserved`, `interrupted`, `left`, `failed` |
| `core.scene.signal_raised` avec `error_class: core_restarted_unobserved` | le signal posé à la fin de la grâce |

**Scène pleine au redémarrage.** Le marquage ne prend aucune place. Un signal de
fin de grâce en demande une : sans place, l'étoile reste « état inconnu » (le
signal passe toujours avant l'état) et attend un archivage, derrière les
sous-agents en cours. Cette attente est en mémoire : si Core redémarre encore,
l'étoile est simplement remarquée et une nouvelle grâce commence.

### Scène constellation : lecture HTTP et dépannage

Core sert la scène par trois routes de lecture et de commande, plus deux routes
de capture (voir « Capture visuelle ») (jeton de `runtime\core.token`, comme
`/v1/work/snapshot`) ; le navigateur passe toujours par le Control Center, qui
n'a pas besoin du jeton côté page (`docs/ARCHITECTURE.md`, « Scene transport ») :

| Control Center | Core | Rôle |
| --- | --- | --- |
| `GET /api/scene` | `GET /v1/scene/snapshot` | instantané complet : `scene_id`, `epoch`, `revision`, `snapshot` |
| `GET /api/scene/patches?scene_id=…&epoch=…&after=N&wait_s=25` | `GET /v1/scene/patches` | attente longue des patchs après la révision `N` (25 s au plus côté Control Center, 30 s côté Core) |
| `POST /api/scene/commands` | `POST /v1/scene/commands` | une commande de scène ; côté Control Center l'acteur est toujours `user` |
| `POST /api/scene/captures/{capture_id}` | `PUT /v1/scene/captures/{capture_id}` | envoi de l'image d'une capture par la page meneuse visible (la demande, `POST /v1/scene/captures`, ne vient que du brain) |
| `POST /api/jobs/cancel` | `POST /v1/work/cancel` | arrêt d'une tâche de Core depuis le menu de son étoile |

Voir la scène brute, Core démarré :

```powershell
$token = Get-Content runtime\core.token
$h = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://127.77.0.1:17653/v1/health -Headers $h            # champ scene : state, code, saturated, objects, object_limit
$s = Invoke-RestMethod http://127.77.0.1:17653/v1/scene/snapshot -Headers $h
Invoke-RestMethod "http://127.77.0.1:17653/v1/scene/patches?scene_id=$($s.scene_id)&epoch=$($s.epoch)&after=$($s.revision)&wait_s=5" -Headers $h
Invoke-RestMethod http://127.0.0.1:17654/api/scene                          # même chose, vue par le Control Center
```

`epoch` change à **chaque démarrage de Core** : un client qui tenait l'ancienne
époque reçoit `resync_required: true` et relit l'instantané, même si
`scene_id` et la révision n'ont pas bougé (cas d'une sauvegarde de
`scene.sqlite3` restaurée). `revision` d'une réponse de patchs est la révision
atteinte en les appliquant ; `more: true` veut dire « réponse bornée à 1 Mio,
redemander tout de suite ».

Acteurs : Core accepte `brain` et `user` ; `runtime` est refusé (403
`scene_actor_forbidden`), la projection runtime écrit depuis l'intérieur de
Core. Le Control Center pose `user` quand l'acteur manque et refuse tout autre
acteur (403). Un refus **du domaine** n'est pas une erreur HTTP : une archive
demandée par le cerveau rend 200 avec `outcome: rejected_authority`,
`reason: op_not_allowed`. Limite assumée : le cerveau tourne sous le même
compte Windows et pourrait lire `runtime\core.token` ; l'interdiction
d'archiver tient au catalogue d'outils du cerveau et au réducteur, pas à une
barrière de sécurité locale.

Dépannage, d'après `error.code` et la trace. En lecture, `/api/scene` et
`/api/scene/patches` répondent 400 à une requête mal formée ; sinon 200, que
Core ou la scène soient disponibles ou non, avec `error` renseigné. Les
messages montrés à la page ne contiennent jamais de chemin de fichier
(`<chemin>`) : le chemin exact est dans la trace (`data.error`).

| Ce que vous voyez | Cause | Que faire |
| --- | --- | --- |
| `not_configured` | Control Center lancé sans relais de scène (tests, intégration partielle) | lancer le Control Center par `python -m jarvis control-center` |
| `core_unreachable`, trace `scene.view_unavailable` (avertissement, une fois) | Core arrêté, jeton absent, ou pas de réponse dans le délai (`n'a pas répondu en N s`) | démarrer Core ; au retour, `scene.view_restored` (info) apparaît et la page relit la scène |
| `core_refused` | Core a refusé l'appel (jeton périmé encore après relecture, version de protocole) | redémarrer le Control Center après Core ; lire le statut et le code dans le message |
| `scene_unavailable` avec `scene.code` (`corrupted`, `schema_newer`, `storage_io`…) | Core tourne, mais la scène est refusée au démarrage ou devenue indisponible | voir « Scène constellation : fichier et refus » ci-dessous ; `/v1/health` montre le même `scene` |
| `invalid_scene_response`, trace `scene.view_invalid_response` (erreur, panneau **ERR**, une fois par type de lecture jusqu'au retour à la normale) | Core a répondu hors contrat (versions de Core et du Control Center différentes) | redémarrer les deux sur la même version |
| `patch_waits_busy` avec `retry_after_ms`, trace `scene.view_busy` (avertissement, au plus une fois par minute) | plus de 32 attentes de scène en cours dans ce Control Center (beaucoup d'onglets ou une page qui boucle) | rien à faire pour un pic : la page réessaie après le délai ; si cela dure, fermer les onglets en trop |
| commande : 400 `invalid_request` | corps illisible (JSON, clé en double, `NaN`, champ inconnu, valeur hors borne) | lire `error.message` : il nomme le champ |
| commande : 413 `payload_too_large` | corps de plus de 64 Kio | réduire la charge (16 Kio au plus en UTF-8) |
| commande : 503 `scene_persist_failed` | écriture SQLite échouée ; `error.scene` dit si la scène reste servie | voir `core.scene.persist_failed` dans la trace |
| commande : 503 `command_not_sent` | connexion à Core non obtenue en 3 s | **rien n'a été appliqué** : renvoyer la commande est sûr |
| commande : 503 `core_unreachable` (« commande non envoyée ») | Core arrêté ou jeton absent | démarrer Core, puis renvoyer |
| commande : 504 `core_timeout` | requête partie, pas de réponse de Core en 10 s | **l'issue est inconnue** : relire `/api/scene` avant de renvoyer la commande |

Chaque commande relayée laisse `scene.command` (info : op, issue, motif,
révision) dans `runtime/trace.jsonl` ; un échec, `scene.command_failed`
(avertissement, cause complète dans `data.error`) ; un acteur refusé,
`scene.command_forbidden` (au plus une fois par minute par valeur d'acteur,
`data.suppressed` compte les refus tus).

### Scène constellation : fichier et refus

La scène (étoiles, artefacts, positions, épingles, archivage) appartient à Core
et survit à son redémarrage. Elle vit dans son propre fichier,
`state/scene.sqlite3` sous la racine locale du PC (`JARVIS_DATA_ROOT`, défaut `~/.jarvis/instances/<dépôt>-<empreinte>/data`, voir [local-data.md](local-data.md)), à côté de
`jarvis.sqlite3` mais séparé de lui (voir `docs/ARCHITECTURE.md`,
« Constellation scene store »). Il est servi par les routes décrites dans
« Scène constellation : lecture HTTP et dépannage » ci-dessus.

Au démarrage, `runtime/trace.jsonl` dit ce qui s'est passé :

- `core.scene.loaded` (info) : scène créée (`created: true`) ou rechargée, avec
  `scene_id`, `revision` et le nombre d'objets, de relations et d'archivés ;
- `core.scene.unavailable` (erreur, aussi dans le panneau **ERR**) : fichier
  refusé. `data.code` en donne la raison, `data.error` le message exact.

Un refus ne bloque pas Core : conversations, jobs et rappels continuent, seule
la scène est indisponible. Le fichier n'est **jamais** effacé ni réparé
automatiquement : son contenu (tables, lignes, version) n'est jamais modifié,
réécrit ni recréé. Seuls des changements physiques peuvent survenir (SQLite
reverse son journal WAL dans le fichier à la fermeture, ou passe l'en-tête en
mode WAL), sans rien changer au contenu. Aucune copie de la scène n'est faite. Seul un fichier **absent** fait créer une nouvelle scène (si un `scene.sqlite3-wal` est resté sans sa base, il est d'abord mis de côté intact en `scene.sqlite3-wal.orphan-<horodatage>.bak`, journalisé `core.scene.orphan_wal_set_aside`) ;
un fichier vide (0 octet) ou sans table est refusé. Que faire selon
`data.code` :

| Code | Cause | Action |
| --- | --- | --- |
| `schema_newer` | fichier écrit par une version plus récente de JARVIS | revenir à cette version (ou attendre sa mise à jour) ; ne pas supprimer le fichier |
| `schema_unknown` | version illisible, ou fichier qui n'est pas une base de scène | vérifier qu'aucun autre fichier n'a été copié à cet emplacement |
| `corrupted` | fichier vide ou tronqué, illisible par SQLite ou contenu invalide | Core arrêté, déplacer le fichier **et** `scene.sqlite3-wal` / `-shm` s'ils existent hors de `data/state/`, les garder pour analyse, redémarrer Core : une scène vide est recréée |
| `storage_io` | fichier ou dossier non inscriptible (lecture seule, droits), verrou d'écriture tenu par un autre processus plus de 5 s, erreur d'E/S, chemin qui est un dossier | corriger l'accès (par exemple retirer l'attribut lecture seule, arrêter l'autre Core), redémarrer Core |

Au démarrage, Core retire aussi les fichiers `scene.sqlite3.<aléa>.creating`
d'une création interrompue, **dans `data/state/` seulement**, s'ils ont plus de
10 minutes et sont des fichiers ordinaires (jamais un lien ni une jonction).
Rien d'autre, et rien hors de ce dossier, n'est jamais touché. Ce qui a été
retiré est journalisé `core.scene.swept` (info) ; ce qui n'a pas pu l'être,
`core.scene.sweep_failed` (avertissement, chemin et cause), à supprimer à la
main si le message persiste.

En cours de route, `core.scene.persist_failed` (erreur) signale une commande de
scène non écrite : la révision n'a pas bougé et aucun lecteur ne l'a vue. Il
n'apparaît **qu'une fois par panne** : les échecs identiques suivants (même
code, même type d'erreur, par exemple les nouvelles tentatives de la projection)
sont seulement comptés jusqu'à la première écriture réussie, qui laisse
`core.scene.persist_restored` (info, `suppressed` = échecs tus) ; un échec d'une
autre nature est journalisé à nouveau avec ce compte. Avec
`code: revision_conflict` (deux Core sur le même dossier de données, par
exemple), ou si la connexion reste bloquée dans une transaction (`storage_io`,
message « left inside a transaction »), la scène devient indisponible jusqu'au
prochain redémarrage de Core. Cas limite : une erreur d'E/S à la toute fin d'un
`COMMIT` peut signaler un échec alors que la commande est déjà écrite ; la
commande suivante échoue alors en `revision_conflict`, et le redémarrage
recharge ce qui est réellement sur disque.

### Scène constellation : outils d'affichage du cerveau

Le cerveau conversationnel (Claude CLI) peut lire et composer la scène par
treize outils MCP du serveur `jarvis-display` : trois lectures, `scene_inspect`
(toute la scène en lignes compactes), `scene_query` (trouver des objets par
filtres) et `scene_get` (lire le détail d'un objet), la capture exceptionnelle
`scene_capture`, puis `scene_create_object`, `scene_update_object` (un objet,
masquer ou réafficher compris), les outils d'**ensemble** `scene_update_many`
(le même changement), `scene_move` (déplacer d'un même écart), `scene_archive`
et `scene_pin`, et enfin `scene_link`, `scene_unlink` et `scene_add_artifact`
(artefacts, voir « Scène constellation : les artefacts »).

**Un ensemble = un appel = une commande.** Depuis la Slice 05 de
`jarvis-mcp-semantic-batch-inspector` (25/09/2026), les quatre outils
d'ensemble envoient **une seule** commande de sélection à Core : tout est
appliqué en une révision, ou rien (le refus nomme chaque objet fautif et son
motif, et la révision ne bouge pas). Plus de boucle objet par objet, plus de
`best_effort`, plus de délai de 15 s ni de plafond à 32 ou 128 : la borne est
512 objets. « Montre toute la constellation de cette tâche » ou « déplace-la
vers la gauche » : un appel (`select {"constellation": {...}}`) ; la
constellation est celle du domaine (liens dans les deux sens, signaux compris,
objets masqués compris). Le résultat dit combien d'objets ont changé et
`hidden_count`, le nombre de membres qui étaient masqués. Une panne de
transport est une seule erreur qui dit « tout ou rien, relis la scène ».
`scene_set_visibility` n'existe plus : une conversation reprise qui l'appelle
reçoit une erreur « outil inconnu » et la nouvelle liste.

**Lire la scène en détail.** `scene_query` combine des filtres : nature, catégorie,
état d'exécution, origine (runtime, cerveau, utilisateur), visible ou masqué, texte
du titre, travail Core (`work` : identifiant externe, `work_id` ou
`source:identifiant`), ce qui explique un objet (`explains`), et les objets placés à
moins d'une distance d'un autre (`near` : la distance est donnée au millième, un
écart réel n'est jamais affiché 0, et la colonne `overlap` dit si les surfaces se
chevauchent vraiment ; c'est ainsi que le cerveau vérifie un chevauchement). Comme
à l'écran, `near` ignore les objets masqués, sauf `include_hidden`. `scene_get`
rend, pour 1 à 8 objets, le titre, le résumé, les entrées d'un artefact avec, pour
chaque adresse, l'hôte et `link` selon la même règle que la page (une adresse que
la page affiche en simple texte a `host: null`), le travail Core, la forme, la
place, la couche, l'épinglage, les liens entrants et sortants, les artefacts qui
l'expliquent, ce qu'il explique et ses signaux. Après un redémarrage du cerveau,
c'est par là qu'il relit ce qu'une recherche a donné. Les deux réponses ne
dépassent jamais 20 Ko et disent ce qu'elles coupent (`truncated`, compteurs
`*_omitted`, `summary_truncated`) ; le premier objet demandé est toujours rendu.
Elles ne modifient rien.

**Capture visuelle (exceptionnelle).** « Vérifie visuellement… » ou « regarde
l'écran » : le cerveau appelle `scene_capture`. Sa consigne sépare les deux cas :
une question de **structure** (voisinage, place, « est-ce que X chevauche Y »)
passe par `scene_query near` ou `scene_inspect` ; une question sur **l'écran**
(« regarde l'écran », « est-ce lisible », « est-ce que ça se chevauche à
l'écran ») passe par la capture, parce que la géométrie enregistrée et les pixels
dessinés peuvent différer — une capsule plus haute que sa forme dessinée, un
objet compact — et qu'une affirmation sur ce que vous voyez doit s'appuyer sur
l'image. Ce n'est pas une copie
d'écran du système : la page du Control Center **ouverte et visible** (l'onglet
meneur) redessine sa couche de scène sur une image PNG de 1280×720 au plus et
l'envoie à Core, qui la range dans `runtime/scene-captures/` (noms
`capture-<date UTC>-<8 hex>.png`, sans texte de l'utilisateur ; on garde les 5
dernières, et rien au-delà de 24 h, nettoyage à chaque capture et au démarrage de
Core). L'image contient uniquement la scène (fenêtres, capsules, étoiles, liens) :
ni commandes, ni panneaux, ni chronologie, ni texte vocal, ni visage. Le cerveau
reçoit le chemin et l'image. Personne d'autre ne peut demander une capture : pas
de bouton, pas de route du Control Center. Pour un simple chevauchement, le
cerveau utilise `scene_query` (near, rayon 0), sans image. L'image est dessinée
aux mêmes places et tailles que la page (même calcul des formes), texte lisible
même réduit.

**Limite de confiance.** Le canal de la page n'a pas de jeton : un autre programme
local, ou une page servie en local, peut lire la demande de capture et envoyer une
autre image, ou la garder sans répondre (le cerveau reçoit alors `no_visible_page`).
Une capture est une vérification sur une machine de confiance, pas une preuve
(voir `docs/SECURITY.md`).

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| erreur d'outil `no_visible_page` après 5 s | aucune page du Control Center ouverte et visible (fermée, onglet caché, fenêtre réduite, scène éteinte dans la page) | ouvrir le Control Center au premier plan, puis redemander |
| erreur d'outil `scene_disabled` | `scene.enabled` faux (réglage ou `JARVIS_SCENE_ENABLED`) | allumer la scène |
| erreur d'outil `capture_busy` | une capture est déjà en cours | attendre quelques secondes |
| erreur d'outil `capture_cancelled` | la capture a été annulée (Core arrêté pendant l'attente, ou appel du cerveau abandonné) | redemander ; un appel abandonné libère la place tout de suite |
| `core.scene.capture_abandoned` | l'appel du cerveau est parti avant la réponse (CLI tué, outil annulé) | normal ; la capture suivante est servie |
| erreur d'outil `capture_unavailable` | Core lancé sans dossier de captures (outil de test) | lancer Core par `python -m jarvis core` |
| `core.scene.capture_store_failed` (erreur) | `runtime/scene-captures/` non inscriptible | corriger les droits du dossier runtime |
| `scene.capture_upload_refused` (avertissement) | envoi d'une image invalide (bloc PNG corrompu, image animée, bloc inconnu), trop grande (> 2 Mio, > 1280×720), pour un identifiant inconnu ou déjà utilisé (404), ou expiré (410 `capture_expired`) | normal si ce n'est pas la page ; sinon relever le code |
| `agent.stream_line_too_long` (erreur) | une ligne du CLI (Claude ou Codex, sortie ou erreurs) dépasse 16 Mio | relever l'outil concerné ; la ligne est ignorée en entier, la lecture continue |
| `agent.read_failed` (erreur, `codex_read_failed`) | la lecture de la sortie de Codex a échoué | relever le message ; Codex est arrêté, le tour échoue au lieu de rester bloqué |
| un `agent.event` porte `journal_truncated: true` | l'événement dépassait 256 Kio : la trace n'en garde que le type, la taille et un aperçu | normal ; les images n'y figurent jamais (`omitted_bytes` à la place) |

Vérifier dans la trace : `core.scene.capture_requested`, puis
`scene.capture_uploaded` (Control Center), `core.scene.capture_stored` et
`display.capture` (tailles et durée, jamais l'image) ; dans la console du
navigateur, `[scène] scene.capture_started` / `scene.capture_sent`.
« Réaffiche tout » passe par `scene_update_many` avec `select {"visibility":
"hidden"}` et `visibility: "visible"` : une commande, tout ce qui est masqué au
moment où Core l'applique ; masquer la moitié ou plus des objets visibles
demande `confirm: true` (garde-fou du cerveau, rien n'est envoyé sans). Quand la scène a bougé
depuis la dernière lecture du cerveau, les résultats de commande listent ce qui
a changé (apparu, archivé, masqué ou réaffiché, état), dix lignes au plus.
Il agit toujours comme acteur `brain`. **`scene_archive` et `scene_pin`
existent** (20/09/2026) : le cerveau retire des objets de la scène — actifs,
masqués ou épinglés par vous, sans exception — et il épingle ou désépingle, en
une commande par appel (512 objets au plus). Core ne le lui refuse plus : `ALLOWED_SCENE_OPS` donne à `brain`
exactement la main de `user`, parce que vous avez demandé que JARVIS fasse ce
que vous faites dans l'interface plutôt que de vous y renvoyer.
Détail technique : `docs/ARCHITECTURE.md`, « Brain display MCP ».

**Activer.** Interrupteur `scene.enabled`, **allumé par défaut** : une
installation neuve, sans clé `scene` dans `runtime/control-center-settings.json`
et sans variable d'environnement, est allumée. Pour l'éteindre : **SET →
Expérimental → « Scène constellation »**, décocher (enregistré immédiatement),
ou dans `runtime/control-center-settings.json` :

```json
{ "scene": { "enabled": false } }
```

ou par l'API du Control Center, `POST /api/settings` avec
`{"scene": {"enabled": false}}` (lecture : `GET /api/settings`, bloc `scene` :
`enabled`, `source` = `settings` ou `env`, `stored` = ce que vaudrait
l'interrupteur sans la variable — la valeur du fichier, ou le défaut quand le
fichier n'en dit rien de lisible —, `env` = nom de la variable quand elle
l'emporte). Seul un booléen enregistré compte : une clé `scene` absente, nulle
ou d'un autre type (`"true"`, `1`) retombe sur le défaut allumé plutôt que
d'éteindre la scène sur un fichier abîmé ; seul un `false` enregistré
l'éteint. `JARVIS_SCENE_ENABLED=1` (ou `0`) dans
l'environnement du Control Center l'emporte sur le fichier ; tant qu'elle est
posée, toute écriture est refusée (400, en-tête `X-Jarvis-Error-Code:
scene_env_override`, trace `settings.agent.rejected`) et la case de l'onglet est
en lecture seule, avec l'explication.

**Quand ça s'applique.** L'affichage suit en une seconde (la page relit
l'interrupteur dans `/api/status`). Les outils **et** la consigne du cerveau ne
changent qu'à son prochain démarrage : le CLI lit ses serveurs MCP et sa consigne
système à son lancement, et **une conversation reprise (`--resume`) garde la
consigne enregistrée à son premier tour** — seuls les outils suivent. Constaté au
Slice 11 sur le vrai CLI : conversation commencée scène éteinte, reprise scène
allumée → dix outils présents, aucun artefact créé à la fin d'une recherche.
C'est pourquoi « Redémarrer le brain… » de l'onglet Expérimental repart sur une
**nouvelle conversation** (`POST /api/agent/restart` avec
`{"new_conversation": true}`), alors que « Redémarrer » du panneau Agents reprend
la conversation. L'onglet compare le réglage à `GET /api/status` → `agent` :
`display_tools` (outils du processus en cours) et `display_prompt` (consigne de
la conversation en cours), et ne propose le redémarrage que s'ils diffèrent.
Éteint, le cerveau est lancé exactement comme avant ; un cerveau lancé scène
allumée garde ses outils après extinction, jusqu'à son redémarrage.

Rien à enregistrer avec `claude mcp add` : JARVIS écrit
`runtime/display-mcp.json` à chaque lancement du cerveau et le passe en
`--mcp-config`. Vos serveurs MCP personnels (`jarvis-drive`…) restent chargés à
côté ; seul le profil conversationnel reçoit ce serveur, jamais les jobs de fond
ni l'analyse spéculative. Le fichier contient l'interpréteur Python, le port de
Core et le **chemin** du jeton, jamais le jeton.

**Vérifier que les outils sont visibles.**

1. `runtime/trace.jsonl` : `agent.start` avec `data.display_mcp: true`, puis
   `agent.prompt` avec `program_id` = `backend.claude.conversation.display_session` ;
2. au premier tour, l'événement `agent.event` de type `system` / `init` liste
   `jarvis-display` dans `mcp_servers` avec `status: connected`, et les outils
   `mcp__jarvis-display__scene_*` ;
3. `display.server_started` (info) quand le CLI lance le serveur ;
4. demander « montre-moi à l'écran une note qui résume … » : `display.tool`
   `scene_create_object : applied`, et l'objet (`origin: brain`) dans
   `GET /api/scene`.

**Dépanner.**

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| `agent.start` dit `display_mcp: false` alors que l'interrupteur est vrai | cerveau pas redémarré, `JARVIS_SCENE_ENABLED=0`, ou brain non Claude (Codex n'a jamais ces outils) | SET → Expérimental → « Redémarrer le brain… » ; lire `GET /api/status` → `agent.display_tools` et `GET /api/settings` → `scene.source` |
| le cerveau a les outils mais ne crée pas d'artefact et ne relit pas la scène (ou cherche des outils de scène alors qu'elle est éteinte) | conversation reprise (`agent.start` `resumed: true`) qui garde la consigne de son premier tour ; `GET /api/status` → `agent.display_prompt` différent du réglage | SET → Expérimental → « Redémarrer le brain… » (nouvelle conversation), ou redémarrer JARVIS |
| « Réglage de scène non enregistré » dans l'onglet Expérimental, code `scene_env_override` | `JARVIS_SCENE_ENABLED` est posée pour le Control Center | la retirer et relancer le Control Center, ou garder la valeur imposée |
| `scene.display_mcp_unconfigured` (avertissement) | Control Center lancé sans coordonnées de Core (hors `python -m jarvis control-center`) | lancer par la commande normale |
| `agent.display_mcp_failed` (erreur, panneau ERR) | `runtime/display-mcp.json` non inscriptible | corriger les droits du dossier runtime, redémarrer l'agent ; la voix marche sans l'écran en attendant |
| `mcp_servers` montre `jarvis-display` en `failed` | interpréteur introuvable, paquet `mcp` absent (`pip install -e .[mcp]`), variable d'environnement invalide | lancer à la main la commande de `runtime/display-mcp.json` avec son `env` : l'erreur s'affiche |
| erreur d'outil `core_unreachable` / `command_not_sent` | Core arrêté ou jeton absent | démarrer Core ; rien n'a été appliqué |
| erreur d'outil `core_refused` avec `401` | Core redémarré, jeton relu mais toujours refusé | vérifier `JARVIS_CORE_TOKEN_FILE` du Control Center et de Core |
| erreur d'outil avec `reason=runtime_owned` | le cerveau a voulu retirer un lien de parenté entre étoiles ou le lien d'un signal de tâche | normal : ces liens sont au runtime, pas un refus adressé au cerveau ; il masque le signal (`scene_update_object`, `visibility`) ou le retire pour de bon (`scene_archive`) |
| erreur d'outil `Arguments inconnus refusés` | le modèle a inventé un argument (`archived`, `pinned_by_user`…) | normal : rien n'est parti ; `display.tool_failed` code `unknown_argument` nomme les champs |
| le cerveau décrit un écran qui n'est plus à jour | il n'a pas relu la scène dans le tour | chercher `mcp__jarvis-display__scene_inspect` dans le tour de la trace ; les résultats de commande portent `scene_changed` quand la scène a bougé |
| erreur d'outil `scene_unavailable` | scène refusée par Core | voir « Scène constellation : fichier et refus » |
| erreur d'outil avec `reason=pinned_by_user` | **placement automatique** sur un objet que vous avez épinglé : l'épingle protège sa place, et elle seule | normal, et ce n'est pas « il appartient à l'utilisateur » : une commande explicite passe. Le cerveau redonne la géométrie qu'il veut, ou désépingle avec `scene_pin` |
| erreur d'outil avec `reason=scene_full` | 512 objets actifs | archiver ce qui ne sert plus. Le cerveau le fait lui-même (`scene_archive`, par exemple `select {"exec_state": "completed"}`) — l'erreur le lui dit —, vous depuis « Archiver les travaux terminés… » |
| `display.tool_failed` niveau erreur `display_internal_error` | défaut du serveur | remonter le message (type et texte) |
| erreur d'outil `scene_query (near) … reason=unplaced` | l'objet de référence n'a pas encore de géométrie enregistrée (placement automatique pas encore fait par une page) | normal : ouvrir le Control Center le place en quelques secondes ; sinon `scene_get` |
| erreur d'outil `scene_query (explains) … reason=object_archived` | l'objet a été archivé | normal : rien à expliquer dans la scène active |
| le cerveau répond « je ne vois que le titre » d'un artefact | cerveau lancé avec une version plus ancienne, ou conversation reprise (`agent.start` `resumed: true`) qui garde l'ancienne consigne | SET → Expérimental → « Redémarrer le brain… » ; la trace doit montrer `mcp__jarvis-display__scene_get` et `display.read` |
| erreur d'outil `attach_artifact refusé … reason=object_archived` | l'utilisateur a archivé l'étoile du travail | normal : pas d'artefact pour un travail rangé, rien n'a été envoyé |

Tous les appels laissent `display.tool` / `display.read` (lectures `scene_query`
et `scene_get` : noms des filtres ou identifiants, comptes) / `display.tool_refused` /
`display.tool_failed` dans `runtime/trace.jsonl` (identifiants et issues, jamais
le texte des notes ni un chemin de fichier). `display.server_stopped` n'apparaît
que si la session se termine proprement : un arrêt du cerveau tue d'ordinaire le
serveur sans cet événement, ce n'est pas une panne. Les actions d'affichage sont silencieuses à l'oral : le
cerveau ne décrit pas ce qu'il place.

### Catalogue des outils MCP (lecture seule)

Le Control Center décrit les outils MCP de JARVIS sans jamais en exécuter un
(contrat `docs/mcp/tool-contract.md` §4.3, §8, §10.6) :

- `GET /api/mcp/tools` — serveurs (`jarvis-tools`, `jarvis-display`,
  `jarvis-console` — réglages seuls —, `jarvis-workspace` — Boards, Sessions,
  mémoire et liens des Boards, `python -m jarvis workspace-mcp`,
  `runtime/workspace-mcp.json` —, `jarvis-capture`, `jarvis-barehands`,
  `jarvis-drive`) avec leur disponibilité du moment, puis une
  carte compacte par outil (nom, serveur, catégorie, libellé, résumé, classe
  d'effet, atomicité, état, dépréciation, nombre de paramètres) ;
- `GET /api/mcp/tools/{server}/{name}` — le descripteur complet (paramètres,
  schémas d'entrée et de sortie, annotations, coût de contexte) et sa
  disponibilité.

État d'un serveur : `advertised` (le cerveau en cours l'a reçu), `configured`
(le prochain lancement le déclarera : l'agent tient sa cible), `disabled`
(interrupteur éteint, cible absente ou agent Codex, qui ne reçoit jamais les
serveurs natifs), `known` (`jarvis-drive`, déclaré par l'opérateur : jamais
prouvable). `condition_value` affiche l'interrupteur tel qu'enregistré.
`pending_restart: true` = une session cerveau **vivante** (Claude en cours,
Codex en cours ou prêt) n'a pas la configuration du prochain lancement →
« Redémarrer le brain… ». Cerveau arrêté : jamais `pending_restart`, son
prochain démarrage prend la configuration courante. Tout autre méthode que
`GET` sous `/api/mcp` répond `405` `method_not_allowed`, tout chemin inconnu
`404` `mcp_tool_unknown` (JSON dans les deux cas).

| Symptôme | Cause | Que faire |
| --- | --- | --- |
| `503` `mcp_catalog_unavailable` | le catalogue n'a pas pu être construit (classe d'erreur dans le corps) | lire `mcp.catalog_failed` dans `runtime/trace.jsonl` ; un outil enregistré sans métadonnées (`mcp_tool_meta.py`) donne `LookupError` |
| `503` `mcp_server_unavailable` sur un outil `jarvis-drive` | le module ne s'importe pas (dépendance absente) ; la liste le marque `described: false` | installer les dépendances Drive, redémarrer le Control Center |
| `404` `mcp_tool_unknown` | serveur ou outil inexistant (le corps ne répète pas la demande) | relire la liste |
| display `configured` alors que la scène est allumée et le cerveau lancé | cerveau lancé avant l'allumage (`pending_restart: true`) | « Redémarrer le brain… » |
| `condition_value: false` mais `next_launch: configured` | réglages modifiés dans le fichier sans passer par le Control Center : l'agent tient encore la cible | enregistrer depuis SET (ou redémarrer le Control Center) |
| `advertised: null` sur un serveur natif | instantané de l'agent illisible (`mcp.availability_failed`) ou cerveau Claude sans le drapeau | lire la trace ; redémarrer le brain |

`mcp.catalog_built` (info) part une fois par processus au premier catalogue.

#### Inspecteur MCP (bouton `MCP` du dock)

Le bouton **MCP** du dock de droite (entre `SET` et `AGT`, avec les autres vues
d'inspection) ouvre une vue plein écran qui lit ces deux routes, en `GET`
seulement : **aucun outil n'est exécuté d'ici** (contrat
`docs/mcp/tool-contract.md` §10.7).

- **À chaque ouverture**, la liste des serveurs et leur disponibilité est
  relue (un redémarrage du brain se voit) ; les descripteurs déjà lus restent
  en mémoire tant que l'ensemble des outils ne change pas.
- **En-tête** : recherche, « Tout déplier / Tout replier », « Actualiser », état
  du catalogue (chargement avec compteur de secondes, `Catalogue lu`,
  `Redémarrage en attente` ou l'erreur), fermeture. Un bandeau orange nomme les
  serveurs `pending_restart` : « À prendre en compte au prochain (re)démarrage
  du brain ».
- **Serveurs** : une pastille par serveur (pastille verte `Annoncé`, bleue
  `Configuré`, vide `Désactivé` / `Connu`, rouge `Non descriptible`), nombre
  d'outils et coût de contexte en octets ; un clic ouvre l'onglet du serveur.
- **Onglets** `Général` (vue d'ensemble : serveurs, déclaration, légende des
  badges ; outils transversaux : `list_tools` et `call_tool` de la passerelle
  `jarvis-tools`, plugins MCP Slice 04), `Étoiles / Scène`, `Réglages`,
  `Bare Hands`, `Externe`, avec le nombre d'outils (`correspondances/total`
  pendant une recherche).
- **Lignes compactes** : libellé, nom du fil, résumé d'une ligne, nombre de
  paramètres, badges `Lecture` / `Écriture` / `Destructif`, `Lot atomique`,
  `Idempotent`, `Déprécié`, et l'état du serveur quand il n'est pas `Annoncé`.
- **Détail** (clic, Entrée ou Espace ; lu à la demande puis gardé) :
  description, nom complet, effet, atomicité, idempotence, coût de contexte,
  table des paramètres (type, requis/facultatif, défaut — « — » = aucun défaut,
  différent de `null` —, contraintes, description, structure des paramètres
  objets), règles entre paramètres, résultat (format, notes, arbre du schéma de
  sortie) et, en dernier, « Schéma brut (JSON) » replié.
- **Recherche** : nom, libellé, résumé et noms de paramètres, clés imbriquées
  comprises (`radius` trouve `select.near.radius`). La première recherche lit
  tous les descripteurs ; l'état affiche `paramètres indexés n/28` tant que ce
  n'est pas fini.
- **Clavier** : `/` recherche, flèches gauche/droite entre onglets, haut/bas
  entre outils, Début/Fin, Entrée/Espace pour déplier, Échap ferme et rend le
  focus au bouton MCP (même si le focus est retombé sur la page). Le reste de
  la page est inerte tant que la vue est
  ouverte ; les raccourcis de la page ne la traversent pas.

| Ce que l'on voit | Cause | Que faire |
| --- | --- | --- |
| « Catalogue MCP indisponible » · `mcp_catalog_unavailable · HTTP 503` | voir le tableau ci-dessus | lire `mcp.catalog_failed`, puis « Réessayer » |
| « Outil inconnu du catalogue » dans un détail | le catalogue a changé depuis l'ouverture | « Actualiser » |
| « Pas de réponse » après 15 s | Control Center bloqué ou arrêté | « Réessayer » ; vérifier le processus |
| bandeau rouge « Actualisation impossible — … » au-dessus d'une liste | la relecture a échoué ; la liste affichée est la dernière lue | « Réessayer » dans le bandeau |
| état « n illisible(s) » pendant une recherche | descripteurs en échec, non cherchables | « Actualiser » |
| une ligne `Configuré` + bandeau orange | serveur allumé après le lancement du brain | « Redémarrer le brain… » |

La console du navigateur garde `mcp.inspector.failed` (code, statut, message)
pour chaque échec vu par la vue ; côté serveur, les refus du catalogue sont
déjà journalisés (`mcp.catalog_failed`).

#### Plugins MCP externes (onglet « Plugins externes » du même dialogue)

En haut du dialogue MCP, deux onglets : « Exposition interne » (l'inspecteur
ci-dessus) et « Plugins externes » : les serveurs MCP distants ajoutés par leur
adresse (contrat `docs/mcp/plugins.md` §9). Core garde leur registre, leurs
accès et leurs connexions ; l'écran n'en garde rien.

- **Carte** : icône (ou initiale), nom, hôte, pastilles connexion et accès,
  interrupteur « Activé / Désactivé » (désactivé : ses outils quittent le brain
  sans perdre l'accès), nombre d'outils, « Gérer », et l'action utile du
  moment (« Connecter », « Reconnecter », « Relancer l’autorisation »).
- **Ajouter un plugin** : adresse `https://…`, nom facultatif, « Ajouter et
  connecter ». Si le serveur demande OAuth, sa page s'ouvre dans un nouvel
  onglet ; l'écran attend le retour 5 minutes au plus (compteur, lien
  « Ouvrir la page d’autorisation » si le navigateur a bloqué l'onglet, « Ne
  plus attendre »). La page de retour dit « Autorisation reçue, vous pouvez
  fermer cet onglet » ou le code de l'échec.
- **Jeton ou clé** (« Gérer » → « Saisir un jeton ») : Bearer ou en-tête
  personnalisé. Le champ est masqué, vidé dès l'envoi, jamais réaffiché ; la
  fiche s'ouvre d'elle-même sur ce formulaire quand le serveur refuse ce
  qu'OAuth a obtenu.
- **Gérer** : fiche (adresse, identifiant, serveur, accès, outils découverts),
  « Actualiser les outils », « Reconnecter », « Déconnecter » (confirmé si un
  accès est gardé : il est oublié), « Supprimer » (toujours confirmé), et les
  outils du plugin rendus comme dans l'inspecteur. Échap revient d'un cran
  (formulaire, fiche) avant de fermer le dialogue.

| Ce que l'on voit | Cause | Que faire |
| --- | --- | --- |
| « Cœur de JARVIS injoignable » · `core_unreachable · HTTP 503` | Core arrêté ou jeton relu en échec | relancer Core, puis « Réessayer » ; l'onglet interne reste utilisable |
| « Adresse interdite » · `mcp_endpoint_forbidden` | adresse privée ou locale | une adresse publique `https` |
| « Nouvelle autorisation nécessaire » · `mcp_plugin_reauthorization_required` (accès `expired`) | jeton expiré sans rafraîchissement (Circuit Toolbox n'en délivre pas), ou refusé | « Reconnecter » : une nouvelle autorisation OAuth ; pour un Bearer/en-tête, « Saisir un jeton » |
| « Coffre de secrets indisponible » · `mcp_vault_unavailable` | pas de DPAPI sur ce poste | seuls les plugins sans authentification fonctionnent |
| « Erreur interne de JARVIS » · `mcp_plugin_internal_error` | défaut local de la connexion | lire `mcp.plugin.owner_crashed` dans la trace de Core |
| « Autorisation non reçue » · `mcp_oauth_timeout` (accès `failed`, connexion `error`) | aucun retour du navigateur en 5 min (onglet fermé, consentement jamais donné) | « Relancer l’autorisation » ; jamais de formulaire de jeton : ce n'est pas un refus |
| « Autorisation interrompue » · `mcp_remote_timeout` après l'ouverture de la page | le serveur n'a pas répondu à temps après le consentement | « Relancer l’autorisation » |

La console du navigateur garde `[mcp-plugins] mcp.plugins.action_failed`
(code, statut, `plugin_id`) ; côté Control Center, `mcp.plugin.relayed`,
`mcp.plugin.core_unreachable` et `mcp.oauth.callback` (jamais un corps, jamais
un secret).


##### Exploiter les plugins (Slice 08)

**Ce que voit le cerveau.** Un plugin activé et connecté est visible au
prochain `list_tools` de `jarvis-tools`, sans relancer le cerveau ; le
désactiver le retire aussitôt de `list_tools` (l'accès est gardé). Le cerveau
Claude en conversation, ses sous-agents délégués et Codex l'atteignent tous par
la passerelle (contrat `docs/mcp/plugins.md` §10).

**Cycle de vie** (onglet « Plugins externes ») :

1. **Ajouter** : « Ajouter et connecter » avec l'adresse `https://…`. Core
   valide l'adresse (aucune requête réseau), crée le plugin **activé**, puis
   tente la connexion : sans authentification il est connecté ; avec OAuth la
   page d'autorisation s'ouvre ; un serveur non standard demande « Saisir un
   jeton ».
2. **Connecter / Reconnecter** : seule action qui peut ouvrir une autorisation
   OAuth (délai 5 min, un seul consentement par clic). Un appel d'outil, un
   redémarrage ou une reconnexion automatique n'ouvrent jamais le navigateur.
3. **Déconnecter** : ferme la session, oublie l'accès scellé (révocation
   envoyée au serveur d'autorisation s'il en annonce une ; Circuit Toolbox
   n'en annonce pas : oubli local seulement). Le plugin reste dans la liste, et
   reste activé.
4. **Supprimer** : déconnecte, puis efface la ligne et ses accès en une seule
   transaction.

**Redémarrages.**

- **Core** relancé : chaque plugin connecté est d'abord noté « déconnecté »,
  puis ceux qui sont activés se reconnectent seuls, sans écran : sans
  authentification (`not_required`), par Bearer/en-tête dont l'accès n'a pas
  échoué (`unknown`/`authorized`), ou OAuth `authorized` avec un jeton encore
  valide ou rafraîchissable ; tout autre état attend l'utilisateur
  (`mcp.plugins.boot_reconnect` liste les reconnexions lancées). Un jeton OAuth échu
  sans rafraîchissement passe à `expired` **sans aucune requête**
  (`mcp.plugin.expired_at_boot`) : cliquer « Reconnecter ». Un plugin désactivé
  n'est jamais touché.
- **Control Center** relancé : rien ne change pour les plugins (il n'en garde
  aucun état) ; une autorisation en cours pendant le redémarrage se relance par
  « Relancer l’autorisation ».
- Preuve : `tests/integration/test_mcp_plugin_restart.py`.

**Port de l'écran et adresse de retour OAuth.** L'adresse de retour enregistrée
auprès du serveur d'autorisation est
`http://127.0.0.1:<JARVIS_UI_PORT>/api/mcp/oauth/callback` (défaut 17654). Core
la calcule depuis **sa propre** variable `JARVIS_UI_PORT` : lancer Core et le
Control Center avec la même valeur (Core journalise l'adresse utilisée dans
`mcp.plugins.connector_ready`). Changer de port : relancer Core **et** le
Control Center ; l'ancien enregistrement client OAuth ne correspond plus, Core
l'ignore et en refait un au prochain « Reconnecter » (une nouvelle autorisation
est demandée).

**Drapeau de développement `JARVIS_MCP_ALLOW_LOOPBACK_HTTP=1`.** Lu par Core
au démarrage (journalisé dans `mcp.plugins.connector_ready` et
`mcp.plugins.started`, `allow_loopback_http`). Il autorise `http://` vers
`127.0.0.1`/`localhost` pour les faux serveurs des tests et des validations
isolées ; jamais sur un poste d'utilisateur. Il n'assouplit jamais la règle des
icônes.

**Récupérer un plugin bloqué.**

| État | Que faire |
| --- | --- |
| accès `expired` (`mcp_plugin_reauthorization_required`) | « Reconnecter » ; tant que ce n'est pas fait, `call_tool` répond ce code tout de suite, sans réseau |
| `mcp_oauth_timeout` (« Autorisation non reçue ») | « Relancer l’autorisation », puis consentir dans les 5 min ; aucune reprise automatique |
| accès `failed` après un refus (`mcp_oauth_denied`) | « Relancer l’autorisation » ou, pour un serveur non standard, « Saisir un jeton » |
| base copiée sur un autre poste ou compte Windows | les accès scellés (DPAPI) ne s'y ouvrent pas : « Reconnecter » chaque plugin |

**Sauvegarde et retour arrière (schéma v4).** Au premier démarrage d'un Core
qui porte le schéma v4, la base existante est copiée une fois en
`jarvis.sqlite3.v3.bak`, à côté d'elle (répertoire de données local, voir
`docs/local-data.md`), avant d'ajouter `mcp_plugins` et `mcp_credentials`
(`CLAUDE.md` : une base n'évolue que par migration, jamais recréée). Revenir à
un Core antérieur : arrêter Core, mettre la base v4 de côté (ne jamais effacer
une base, son `-wal` ou son `-shm` sans copie), copier
`jarvis.sqlite3.v3.bak` en `jarvis.sqlite3`, retirer `-wal`/`-shm` de la base
remplacée, lancer l'ancien binaire — procédure complète dans
`docs/state-model.md` › *Bounded ledger registry and persistence*. Les plugins
et leurs accès écrits après la sauvegarde sont perdus dans la base restaurée.

**Fait connu, antérieur à ce chantier.** Le cerveau de conversation Claude
n'est pas lancé avec `--strict-mcp-config` : les serveurs MCP de niveau
utilisateur (`jarvis-drive`, connecteurs claude.ai, `claude-in-chrome`) se
chargent aussi, à côté des quatre serveurs de JARVIS. `list_tools` ne les
propose jamais ; le modèle peut encore les charger par ToolSearch.

### Scène constellation : ce que l'on voit dans le Control Center

Quand `scene.enabled` est vrai (case de l'onglet Expérimental, voir « outils
d'affichage du cerveau » pour le détail), la page du Control Center dessine la scène **par-dessus le visage**
(circuit imprimé ou Cosmos) et **sous toutes les commandes** : barre du haut,
dock, panneaux, pastilles, réglages, notifications, menu contextuel et
Barehands restent cliquables au-dessus. L'interrupteur est relu à chaque
sondage de `/api/status` (chaque seconde) : l'allumer ou l'éteindre agit sur la
page ouverte sans la recharger. Éteint, la page est exactement celle d'avant :
aucun calque, aucune requête de scène (seul l'onglet Expérimental des réglages
montre l'interrupteur).

**Ce qui est dessiné.**

- **Couleur = catégorie** de l'objet (sous-agent blanc, tâche Core bleu pâle,
  note ou document vert, recherche cyan, code violet, courriel ou roadmap
  jaune, erreur rouge, interruption orange, blocage ambre ; une autre catégorie
  reçoit toujours la même teinte tirée de son nom). L'état d'exécution ne
  change jamais la couleur : il se lit à un **indice secondaire** — anneau qui
  respire (en cours), anneau pointillé (en attente), double anneau (bloqué),
  anneau fin et fixe (étoile terminée, pas encore rangée), pastille « × »
  (échec), « ‖ » (interrompu), « – » (annulé), « ✓ » sur les capsules et
  fenêtres terminées, anneau pointillé pâle et badge « ? » pour une étoile
  d'« état inconnu depuis le redémarrage » de Core (voir « redémarrages »). Un anneau ne bouge que pendant les 12 secondes qui
  suivent l'apparition de l'objet ou un changement de son état (24 à la fois
  au plus, les alertes d'abord) ; ensuite il reste fixe et la scène au repos ne
  consomme rien.
- **Étoile** (point) : sous-agent ou tâche, reliée à son parent par un trait.
  Son titre et son état apparaissent au survol ou au focus clavier, sans
  sortir de l'écran.
- **Signal** (losange près d'une étoile) : **vivant**, il est plein avec un
  anneau qui s'élargit — vite pour un échec, lentement pour un blocage, **sans
  mouvement et plus petit pour `process_stopped`** (arrêt du CLI du cerveau :
  peu urgent). **Retiré** (le travail a repris), il ne reste qu'un contour de
  losange, sans anneau ni trait. Son titre reprend les mots des cartes d'agents
  (« processus arrêté », « Core redémarré ») ; une classe d'erreur technique
  (`TimeoutError`) reste telle quelle.
- **Capsule** : pastille avec le titre ; **fenêtre** : catégorie, titre,
  résumé et liste d'éléments. Un objet épinglé porte une punaise. Un objet
  masqué n'est pas dessiné. **Un travail terminé reste affiché** : seul
  l'archivage le retire (voir « agir sur les objets »).
- Les couches se superposent comme le cerveau ou l'utilisateur l'ont voulu : une
  fenêtre de couche 240 recouvre une fenêtre de couche 220.
- **Petite fenêtre du navigateur** : une fenêtre de scène trop petite pour être
  lue (moins de 180 × 96 pixels) s'affiche en capsule titrée, une capsule trop
  étroite en point avec son titre au survol. C'est un affichage de la page :
  la scène enregistrée ne change pas, et une fenêtre plus grande rend la forme
  d'origine.
- **Clavier** : Tab entre une seule fois dans la scène ; les flèches passent à
  l'objet voisin dans leur direction, Début et Fin au premier et au dernier,
  Échap sort de la scène.

**Repère.** Origine (0, 0) au centre de la fenêtre, x vers la droite, y vers le
bas. La zone x −160…160, y −90…90 est toujours entièrement visible, quelle que
soit la taille de la fenêtre (même échelle en largeur et en hauteur) ; une
fenêtre plus large ou plus haute que 16:9 montre de la scène en plus. Un objet
placé au-delà du bord n'est jamais déplacé : l'indicateur dit « N objets hors
champ ». Les commandes de la page (barre du haut, dock, indication vocale,
indicateurs) couvrent les bords du cadre : la **zone sûre** x −152…138,
y −72…68 reste toujours dégagée (vérifié à 1920 × 1080, 1366 × 768 et
1280 × 720 dans les deux thèmes). Le placement automatique n'utilise qu'elle,
et le cerveau la connaît (« haut gauche ≈ x −150, y −70 »).

**Placement automatique.** Un objet sans position (étoile d'un nouveau
sous-agent, note créée sans géométrie par le cerveau) est placé par la page :
les étoiles **autour du visage**, en couronne (la première en haut, puis à
droite, en bas, à gauche, et ainsi de suite : le ciel se remplit de partout, pas
d'un seul côté), un enfant près de son parent, un signal contre son étoile, les
résultats à droite. La page **enregistre ce placement une seule
fois dans Core** (commande `set_geometry`, `placed_by = resolver`, journalisée
`scene.command`) : après un rechargement, dans un autre onglet ou après un
redémarrage, la disposition est identique. Un objet placé par le cerveau ou par
vous, ou épinglé, n'est jamais déplacé par la page. Avec plusieurs onglets
ouverts, un seul à la fois (un onglet visible) enregistre les placements.

**Étoiles et orbites** (**Réglages › Apparence**, sous la version Cosmos ; avant
le 2026-09-20, un petit bouton en forme d'étoile en bas à droite de l'écran).
Cette section règle *comment* la constellation se montre ; chaque changement se
voit tout de suite et reste enregistré dans ce navigateur. Elle est là même quand
la scène est éteinte : c'est un réglage d'apparence, pas un interrupteur.

| Réglage | Ce qu'il change |
| --- | --- |
| `Taille des étoiles` | le cœur lumineux, sa lueur et les anneaux d'état (0,6 × à 2,4 ×). La zone sensible au clic ne change pas : une étoile minuscule reste aussi facile à attraper |
| `Halo` | le voile large autour de l'étoile (0 × = plus de halo du tout) |
| `Halo qui respire` | éteint, le halo garde une seule intensité |
| `Gravitation` | éteinte, les étoiles sont parfaitement immobiles (aucune animation ne tourne) |
| `Ampleur de l'orbite` | la taille de l'ellipse parcourue (0,3 × à 2,5 ×). À 1 ×, d'une dizaine de pixels à 38 px selon l'éloignement du centre. Elle reste bornée par la place libre : une étoile ne sort jamais de la zone sûre |
| `Vitesse de l'orbite` | 0,25 × à 4 × ; un tour dure 26 s à 1 ×, la même durée pour toutes les étoiles — une étoile et son signal ne se séparent donc jamais |
| `Fils entre les objets` | masque ou montre les traits qui relient une étoile à son parent, à son signal, à ses résultats |
| `Afficher les tâches éphémères` | allumé par défaut. Éteint, les tâches éphémères (voir plus bas) ne s'affichent pas du tout — panneau Agents et scène, y compris pendant qu'elles tournent. Un échec reste toujours visible |

Seules les **étoiles** (les points) gravitent : une capsule ou une fenêtre reste
fixe. Un objet **épinglé gravite comme les autres** — l'épingle protège sa place
(ni le résolveur ni le cerveau ne la changent), pas son dessin, et la dérive
n'écrit jamais rien. Comme tout déplacement à la main épingle l'objet, une scène
rangée par vous serait sinon entièrement immobile (retour utilisateur du
18/09/2026). Si Windows a les effets d'animation désactivés
(`prefers-reduced-motion`), la gravitation et la respiration du halo ne tournent
pas, quel que soit le réglage : c'est voulu.

« Réinitialiser » revient aux valeurs livrées (tout à 1 ×, tout allumé) et ne
s'allume que si quelque chose a été changé. Un réglage sans effet (l'ampleur de
l'orbite quand la gravitation est éteinte) est grisé mais garde sa valeur.
Échap ou un clic ailleurs ferme la fenêtre.

Ce sont des préférences **de ce navigateur** : rien n'est envoyé à Core. Ni la
scène enregistrée, ni les positions, ni ce que voit le cerveau (`scene_capture`
dessine toujours les tailles de référence) ne changent — deux écrans de la même
scène montrent les mêmes objets aux mêmes places. Les autres fenêtres du même
navigateur suivent le réglage aussitôt. En navigation privée, ou si le site n'a
pas le droit d'enregistrer, les réglages fonctionnent mais repartent des valeurs
livrées à chaque ouverture (`[scène] scene.view_not_saved` en console).

**Tâches éphémères.** Quand vous demandez un travail rapide dont vous n'attendez
aucun compte rendu (« fais-moi une todo-liste de mes tâches et nettoie l'écran »),
le cerveau le lance en sous-agent *éphémère* : il préfixe la description de
l'`Agent` par le marqueur exact `[éphémère]` (en minuscules, avec ses accents,
suivi d'un espace). Le marqueur est retiré du libellé affiché ; un marqueur mal
écrit, absent ou collé au texte donne une tâche **ordinaire** (échec sûr).

- **Pendant qu'elle tourne** : une couleur à part (bleu franc, pastille
  « éphémère ») et un halo sombre, dans le panneau Agents comme sur la scène.
  `prefers-reduced-motion` arrête la respiration.
- Au tout début, l'étoile peut paraître une seconde dans sa couleur ordinaire :
  le bleu arrive avec la lecture suivante des travaux Core. Le libellé
  accessible dit « éphémère » dès qu'il est connu.
- **Quand elle réussit** : rien n'est dit à l'oral et aucune notification ne
  s'affiche. C'est le code qui le décide (`ClaudeLocalAgent._push_notice`), pas
  la docilité du modèle : le tour que le CLI ouvre pour la fin du sous-agent est
  consigné `agent.unsolicited_result` (`ephemeral: true`, `spoken: false`) et
  son texte est jeté. Le travail reste rattaché (`work_id` pris comme pour
  n'importe quel relais), donc le relais suivant n'est pas ambigu. Si plusieurs
  tâches finissent dans le même tour, le silence ne vaut que si **toutes** sont
  des éphémères réussies.
- **Elle disparaît d'elle-même** : `EPHEMERAL_LINGER_MS` = 6 s après sa fin
  (`control_center_scene_view.js`), la carte quitte le panneau Agents (et ne va
  pas dans « Terminés ») et l'étoile quitte la scène. Rien n'est supprimé :
  la base, la scène enregistrée, le journal et la timeline gardent le travail ;
  la page ne l'*affiche* simplement plus.
- **Un échec, un arrêt, une interruption ou un blocage ne sont jamais
  éphémères** : la tâche redevient ordinaire, reste visible dans « Terminés »
  (ou sur la scène avec son signal), le cerveau l'annonce et `WorkAttentionPolicy`
  le réveille — « une tâche ne doit jamais mourir en silence ». Cela vaut même
  avec `Afficher les tâches éphémères` éteint.
- **Le réglage est local au navigateur** (`jarvis.scene.view`, comme les autres
  réglages d'apparence) : le cerveau et Core voient toujours ces tâches, dans
  leur état de travail et dans la timeline (`subagent.*` porte l'attribut
  booléen `ephemeral`).

Aucune base SQLite ne change pour cela : l'état de travail de Core est en mémoire
et le drapeau `ephemeral` voyage dans l'observation de travail.

**Indicateur discret** (en bas à gauche, sur la ligne de l'indication vocale ;
au-dessus du badge Barehands quand il est affiché). Le compteur (durée, prochain
essai) change chaque seconde mais n'est jamais lu par le lecteur d'écran : seuls
les changements d'état sont annoncés.

| Texte | Sens | Que faire |
| --- | --- | --- |
| `Scène · chargement…` | première lecture en cours | rien |
| `Scène figée · Core injoignable` `42 s · réessai 8 s` | la lecture a échoué ; la dernière scène connue reste affichée ; nouvel essai automatique (1 s, 2 s, 4 s… jusqu'à 30 s), immédiat quand le Control Center répond de nouveau | démarrer Core ; la page reprend seule |
| `Scène indisponible · …` | même chose, mais aucune scène n'a encore été lue | idem |
| `Scène pleine — archiver des travaux terminés` `512/512` | 512 objets actifs : Core met les nouvelles étoiles en attente et refuse toute nouvelle note | cliquer la pastille : archivage groupé des travaux terminés, avec confirmation |
| `N objets masqués` `afficher` | des objets masqués restent dans la scène | cliquer la pastille : liste, « Afficher » ou « Tout réafficher » |
| `N signaux d'échec sous une fenêtre` / `N signaux à vérifier sous des fenêtres` | un signal d'échec ou de blocage est caché : son étoile est sous une fenêtre de résultat, et le signal suit son étoile | masquer ou déplacer la fenêtre (le cerveau peut le faire), ou ouvrir le panneau Agents |
| `N objets hors champ` | des objets sont placés au-delà du bord de la fenêtre | agrandir la fenêtre, ou demander au cerveau de les rapprocher |

**Onglets et ressources.** Un navigateur n'ouvre qu'environ six connexions à la
fois vers le Control Center. Pour que plusieurs fenêtres ouvertes ne bloquent
pas le reste de la page (statut, agents), **une seule fenêtre visible par profil
de navigateur tient la requête longue** vers `/api/scene/patches` : la
« meneuse ». Elle transmet chaque changement aux autres fenêtres du même profil,
qui se mettent à jour sans requête longue ; elles ne font que de courtes lectures
quand il leur manque quelque chose (première ouverture, changement manqué,
redémarrage de Core). Si la meneuse est fermée, masquée, réduite ou quitte la
page, une autre fenêtre visible prend le relais en moins de deux secondes et
rattrape ce qui a changé entre-temps. Si la meneuse reste visible mais se fige
(onglet bloqué), les autres fenêtres le remarquent seules et relisent la scène :
elles ont au plus une quarantaine de secondes de retard, et les placements
automatiques attendent que la meneuse reprenne. C'est aussi la meneuse, et elle seule, qui
enregistre les placements automatiques.

Mesuré avec 5, 6, 8 et 10 fenêtres visibles : statut en 2 à 8 ms, bascule de
l'interrupteur vue par toutes les fenêtres en moins de 1,2 s, dispositions
identiques. Un onglet caché ne fait aucune requête de scène et rattrape en
revenant. Deux profils (ou deux navigateurs) différents ont chacun leur meneuse.
Un navigateur sans Web Locks ou BroadcastChannel revient à une requête longue
par onglet : au-delà de six fenêtres, le statut ralentit. Si trop de pages sont
ouvertes (tous profils confondus), le Control Center répond « réessayer » et la
page attend le délai indiqué.

**Budget de connexions avec la chronologie.** La chronologie de conversation
partage sa lecture longue de la même façon (meneur Web Lock, relais
`BroadcastChannel`) : un verrou par conversation, un canal à part. Les deux
meneurs ne se gênent pas — les noms de verrous (`jarvis.scene.leader` et
`jarvis.timeline.<conversation>`) et de canaux (`jarvis.scene`,
`jarvis.timeline`) sont distincts, et une même fenêtre peut tenir les deux.
Mesuré avec la scène allumée **et** la chronologie ouverte partout : deux
lectures longues tenues (une par fonction) à 1, 6 et 10 fenêtres, `/api/status`
à 3-4 ms, un événement qui atteint les dix fenêtres en quelques dizaines de
millisecondes. Sans partage (vieux navigateur), c'est une lecture longue par
onglet **et par fonction** : le budget d'environ six connexions par hôte tombe
alors dès trois fenêtres.

**Dépanner.**

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| aucune scène alors que l'interrupteur est vrai | page servie avant la mise à jour, ou `JARVIS_SCENE_ENABLED=0` | recharger la page ; l'onglet Expérimental dit si la variable impose l'état (`GET /api/status` → `scene.source`) |
| la scène reste figée après le retour de Core | la page attend son prochain essai (≤ 30 s) | attendre ; la console du navigateur montre `[scène] scene.view_restored` puis `scene.snapshot_loaded` |
| un objet apparaît puis bouge une fois | placé localement, puis position enregistrée différente (autre navigateur ou autre profil ouvert en même temps) | sans conséquence ; la position enregistrée fait foi ensuite |
| `scene.command set_geometry` en grand nombre dans `runtime/trace.jsonl` | première ouverture d'une scène pleine d'objets jamais placés : une commande par objet, une seule fois | normal |
| la page n'enregistre aucun placement (console : `scene.resolver_commit_retry`) | Core refuse ou ne répond pas ; trois essais par objet au plus (2 s, 8 s) | démarrer Core puis recharger la page |
| animations absentes | réglage système « réduire les animations », ou état inchangé depuis plus de 12 s | normal : anneaux fixes, pas de glissement |
| une fenêtre reste figée alors qu'une autre suit la scène | fenêtre d'un autre profil sans meneuse visible, ou onglet caché | rendre la fenêtre visible : elle rattrape seule ; la console montre `[scène] scene.role` |
| le statut ou les agents répondent lentement avec beaucoup de fenêtres | navigateur sans Web Locks/BroadcastChannel (repli par onglet), ou plusieurs profils | fermer des fenêtres, ou utiliser un seul profil ; la console montre `scene.enabled` avec `mode: solo` |

Détail technique : `docs/ARCHITECTURE.md`, « Scene renderer ».

### Scène constellation : agir sur les objets

Vous agissez sur la **même scène** que le cerveau : chaque geste est enregistré
dans Core, puis retrouvé à l'identique après un rechargement, dans un autre
onglet ou après un redémarrage. Le geste se dessine tout de suite. Si Core le
refuse ou ne répond pas, l'objet revient à sa place et une notification dit
pourquoi, en distinguant « rien n'a été envoyé » (réessayer est sûr) de « issue
inconnue » (la page relit la scène). Aucune boîte de dialogue du navigateur : les
confirmations s'affichent dans la page, et tant qu'une confirmation est ouverte
le reste de la page ne réagit plus (ni clic, ni raccourci, ni geste).

| Pour… | Souris | Clavier (objet sélectionné) |
| --- | --- | --- |
| sélectionner | clic ; la poignée d'une capsule ou fenêtre sélectionnée reste visible | Tab jusqu'à la scène, puis flèches |
| déplacer | glisser l'objet ; **il est épinglé** : le cerveau ne le bougera plus | Maj+flèches (Ctrl+Maj+flèches : grands pas) |
| redimensionner une capsule ou une fenêtre | glisser la poignée du coin bas droit ; **l'objet est épinglé aussi** | Ctrl+flèches |
| ouvrir les actions | clic droit, appui long (doigt ou stylet), ou clic sur l'objet déjà sélectionné | touche Menu ou Maj+F10 |
| annuler un déplacement en cours, fermer un menu ou une confirmation | Échap | Échap |

Un objet déplacé ou redimensionné reste **dans la zone de composition sûre** (la
partie de l'écran qu'aucune commande ne recouvre) : on ne peut plus le glisser
sous la barre du haut, le dock ou les indicateurs du bas. Avec la main de
Barehands, un appui qui tremble ne déplace rien : il faut glisser nettement
(10 pixels).

Actions du menu :

- **Afficher en point / capsule / fenêtre** : même objet, autre forme ;
- **Épingler ici / Désépingler** : un objet épinglé ne bouge que sous votre
  main ; désépinglé, le cerveau peut de nouveau le déplacer ;
- **Masquer** : l'objet reste dans la scène mais n'est plus dessiné. La
  notification propose de l'afficher de nouveau ; la sélection passe à l'objet
  voisin ;
- **Archiver…** : après confirmation, l'objet quitte la scène active (il reste
  dans l'historique ; pas d'annulation en V1). Une étoile emporte **son signal
  d'attention** (vivant ou retiré). Le travail d'une étoile archivée ne la fait
  plus revenir, même s'il avance encore ;
- **Arrêter la tâche…** : seulement pour une tâche Core (étoile « tâche »), après
  confirmation. Pendant l'arrêt, l'étoile porte un anneau orange en tirets et la
  pastille « Arrêt de « … » en cours » compte les secondes ; la réponse arrive au
  plus après le délai réel du Control Center (24 s par défaut). Issues possibles :
  « Tâche arrêtée » ; « La tâche s'était déjà terminée » (elle a fini, normalement
  ou en échec, avant que l'arrêt ne l'atteigne : son résultat est gardé) ;
  « Arrêt demandé » (Core n'a pas
  encore confirmé la fin) ; « Arrêt demandé, nettoyage non confirmé » (tâche de
  fond du brain dont l'exécution n'a pas pu être nettoyée : elle reste en cours).
  **Un sous-agent du brain ne s'arrête pas seul** : son menu l'indique
  (« Arrêt impossible : sous-agent du brain », lu par le lecteur d'écran) ; seul
  l'arrêt du brain entier, depuis le panneau Agents, les interrompt ;
- **Archiver les travaux terminés (N objets)…** : voir ci-dessous.

**Retrouver ce qui est masqué.** Tant qu'un objet est masqué, la pastille
« N objets masqués · afficher » apparaît en bas à gauche. Un clic (ou Entrée)
ouvre la liste : « Afficher « titre » » pour un objet, « Tout réafficher » pour
tous.

**Archiver les travaux terminés.** Depuis le menu d'une étoile, ou directement
depuis la pastille « Scène pleine — archiver des travaux terminés » quand la scène
atteint 512 objets. La confirmation donne les comptes : étoiles terminées, en
échec, annulées, interrompues, et les signaux qui partent avec elles. Ne sont
**jamais** pris : le travail en cours, en attente ou bloqué, les notes et
fenêtres du cerveau, vos propres objets. Core revérifie chaque objet : si la
scène a changé pendant la confirmation (une étoile a repris), rien n'est archivé
et la page propose de reconfirmer avec les nouveaux comptes ; si elle change
encore, la notification propose « Cliquer ici pour réessayer ». La place libérée
est aussitôt reprise par les étoiles que Core avait mises en attente pendant la
saturation.

**Plusieurs onglets.** Chaque onglet peut agir ; les autres voient le
changement en moins d'une seconde. Un objet que vous avez déplacé n'est jamais
replacé par la page.

**Dépanner.**

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| l'objet revient à sa place après un glisser, notification « Déplacement impossible · Core injoignable : rien n'a été envoyé » | Core arrêté | démarrer Core, recommencer ; `runtime/trace.jsonl` : `scene.command_failed` |
| « … issue inconnue, la scène se relit » | la liaison a été coupée après l'envoi | attendre la relecture : la scène dit ce qui a été appliqué |
| un objet ne va pas jusqu'au bord de l'écran | zone de composition sûre | normal : le bord est sous les commandes de la page |
| « Arrêt impossible » dans le menu | l'étoile est un sous-agent du brain | arrêter le brain entier depuis le panneau Agents si nécessaire |
| « Arrêt impossible : Core ne connaît pas ce job » | job terminé et oublié, ou Core redémarré | rien à arrêter |
| « Arrêt non confirmé … après N s » | Core n'a pas vu la tâche se terminer dans le délai | ouvrir le panneau Agents ; relancer l'arrêt si l'étoile est toujours en cours |
| « Archivage groupé impossible : la scène change encore » | du travail reprend ou se termine en continu | cliquer la notification pour réessayer un peu plus tard |
| déplacement au clavier sans effet | la sélection n'est pas sur un objet de la scène, l'objet est déjà au bord de la zone sûre, ou c'est un point (qui ne se redimensionne pas) | Tab jusqu'à la scène ; changer la forme depuis le menu |

Détail technique : `docs/ARCHITECTURE.md`, « Scene user interaction ».

### Scène constellation : les artefacts

Un **artefact** est ce que JARVIS garde d'un travail de fond terminé quand le
résultat mérite d'être retrouvé : les liens trouvés par une recherche, les
fichiers modifiés, les tests lancés, les e-mails envoyés, les changements de
roadmap ou de Trello, un document produit. C'est le cerveau qui le crée, en
silence, **un seul par travail et par catégorie** : toutes les URL d'une recherche
sont les entrées d'un même artefact, jamais un objet par lien. Il est relié à
l'étoile du sous-agent par un trait pointillé de sa couleur. Une seconde fin de
travail du même genre complète l'artefact existant au lieu d'en créer un autre :
une adresse déjà présente est mise à jour, pas répétée. Quand le cerveau complète
un artefact, il ne change jamais sa forme ni sa place (celles que vous avez
choisies) ; il peut en revanche remplacer son titre. Une tâche dictée qui a juste
été faite (« note ce retour ») n'en crée pas, et le cerveau ne parle pas de
l'artefact à l'oral, sauf si vous l'interrogez dessus.

Catégories conseillées, chacune avec sa couleur : `research` (liens et faits),
`fichiers`, `tests`, `api`, `roadmap`, `email`, `document`, `autre`. Le cerveau
peut en choisir une autre ; elle prend alors une couleur stable tirée de son nom.

**Lire un artefact.**

- En point (forme par défaut) : une étoile de la couleur de sa catégorie, près
  de l'étoile qu'il explique ; son titre au survol.
- En capsule (menu de l'objet → « Afficher en capsule ») : sa catégorie puis son
  titre, près de l'étoile.
- En fenêtre (menu de l'objet → « Afficher en fenêtre », ou « montre-moi le
  résultat de la recherche » au cerveau) : catégorie et nombre d'entrées, titre,
  un bouton qui ramène à l'étoile expliquée (titre et état du sous-agent), le
  résumé, puis la liste des entrées, qui défile à la molette, au clavier (PageBas,
  PageHaut) ou en passant d'un lien à l'autre. Depuis le menu, la fenêtre s'ouvre
  dans une place libre près de son étoile, hors du visage et des autres objets.
- Une entrée avec une adresse web `http`/`https` simple est un **lien**. Le **nom de
  l'hôte est écrit en premier** : quand la place manque, il est raccourci par la
  gauche (« …evil-login.example »), jamais par la droite, pour que la vraie
  destination reste lisible ; l'hôte complet est dans l'infobulle. Un clic ouvre un
  nouvel onglet, sans transmettre la page d'origine ; le clic droit donne le menu
  habituel du navigateur (copier l'adresse). Reste du texte : une adresse avec
  identifiants (`https://nom@hôte/`), un nom de domaine international (accents,
  lettres non latines ou `xn--`), une barre oblique inverse, un `%` ou un point
  pleine chasse dans l'hôte, un hôte numérique déguisé (`0x7f.1`), ou tout autre
  schéma. Le cerveau applique exactement la même règle quand il relit les
  entrées. Le pincement
  Barehands n'ouvre pas de lien (le navigateur l'interdit sans vrai clic).
- Au clavier : Tab jusqu'à la scène, flèches jusqu'à la fenêtre, puis Tab parcourt
  le bouton d'origine et les liens ; Échap revient à la fenêtre.
- On peut aussi demander au cerveau « qu'est-ce que la recherche a donné ? » : il
  répond en quelques phrases, en relisant l'artefact avec `scene_get`, y compris
  après un redémarrage (il ne propose pas de refaire la recherche).

**Ranger.** Un artefact reste dans la scène jusqu'à ce que vous l'archiviez
(menu de l'objet → « Archiver… »). Archiver l'étoile du travail **ne l'emporte
pas** : la confirmation le dit (« Son artefact reste dans la scène, à archiver à
part. »), le trait disparaît et l'artefact devient **orphelin**. « Archiver les
travaux terminés » ne prend jamais d'artefact, mais sa confirmation dit combien
en resteront sans lien. Pour les ranger d'un coup : menu d'un artefact ou d'une
étoile → « Archiver les artefacts orphelins (N)… » ; la confirmation donne le
nombre et quelques titres, et **seuls les artefacts qui n'expliquent plus aucun
objet** partent (un artefact encore relié à une étoile reste ; un artefact que le
cerveau n'a jamais relié compte comme orphelin). Le cerveau ne peut ni archiver un
artefact ni en créer un pour un travail que vous avez déjà archivé.

**Vérifier dans la trace** (`runtime/trace.jsonl`) : `display.artifact` (info :
`action` `created` ou `updated`, `id`, `target`, `category`, nombre d'entrées,
jamais le texte) après le tour spontané `agent.unsolicited_result` qui suit la fin
du sous-agent ; `GET /api/scene` montre l'objet `kind: artifact`, `origin: brain`,
et une relation `explains` vers l'étoile.

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| un travail terminé n'a pas d'artefact | le cerveau a jugé qu'il n'y avait rien à retrouver, ou la scène est éteinte | normal ; sinon demander « garde le résultat à l'écran » |
| deux artefacts de même catégorie pour une étoile | créés à la main (`scene_create_object` + `scene_link`), ou par deux cerveaux (deux processus) en même temps ; les appels simultanés d'un même cerveau sont mis en file | archiver le doublon ; l'outil complète ensuite le premier |
| `display.tool_refused` `reason=object_archived`, `sent: false` | l'étoile a été archivée avant que le cerveau ajoute l'artefact | normal : rien n'a été envoyé ni créé |
| `display.tool_refused` `reason=object_archived` sans `sent` | l'étoile a été archivée pendant l'envoi : Core a refusé la commande | normal : un seul refus, rien n'a été créé |
| `link refusé … reason=signal_shape` | le cerveau a donné à un lien `explains` l'identifiant de sa source | normal : omettre `relation_id` |
| « Archiver les artefacts orphelins » absent du menu | aucun artefact orphelin, ou menu d'une fenêtre ou d'une note | normal ; l'entrée est sur les artefacts et les étoiles |
| un libellé d'entrée n'est pas cliquable | adresse non `http(s)`, avec identifiants ou caractères invisibles | normal : lien refusé par sécurité, l'adresse reste lisible |
| `invalid_argument` « … at most 32 » | l'artefact aurait plus de 32 entrées | le cerveau regroupe ou remplace la liste (`items_mode=replace`) |


## Deux architectures vocales : `legacy` et `continuous_brain`

L'architecture choisit le chemin de code de la voix. Voice la lit au démarrage,
dans cet ordre : le réglage **Architecture** du Control Center (`voice_arch`
dans `runtime/control-center-settings.json`), puis `JARVIS_VOICE_ARCH`, puis
`default_voice_arch()`. Le réglage laissé sur « Par défaut » n'écrit rien de
l'environnement dans le fichier : le retour arrière par le `.env` reste donc
possible tant que l'interface n'a rien imposé. L'origine retenue est
journalisée dans `voice.stack` (champ `arch_source` : `settings`, `env` ou
`default`).

| | `legacy` (défaut) | `continuous_brain` (opt-in) |
| --- | --- | --- |
| Session | un réveil, un tour, retour au fond dès la fin de la réponse | une session ACTIVE couvre plusieurs tours |
| Micro | fermé dès que le fournisseur clôt le tour | reste ouvert entre les tours |
| Outils de la surface | catalogue Core complet (agenda, rappels, Drive) + `claude_task` | **vide** |
| Modèle fort | joint par Voice, `ClaudeGateway` → `POST /api/agent/ask` | joint par Core, à travers un `BrainBackend` |
| Parole du cerveau | c'est la réponse du tour Realtime | évènements `brain.speech.requested` sur `/v1/events`, rendus par le `SpeechScheduler` |
| Piles vocales | OpenAI Realtime et Gemini Live | OpenAI Realtime seulement |
| Fin de tour | `auto` ou `manual` | `auto` obligatoire |
| Retour au fond | fin de réponse, mute, délai, panne | mute (touche de réveil ou « Jarvis mute »), délai d'activité utile (sauf `JARVIS_ACTIVE_TIMEOUT_S=0`), panne irrécupérable |

### La surface a les réflexes, le cerveau a la vérité

En mode continu, le modèle Realtime n'est plus qu'une bouche et des oreilles. De
lui-même il ne peut qu'accuser réception par une phrase courte, réparer une
écoute (« je n'ai pas bien entendu ») ou poser une question portant strictement
sur ce qu'il a entendu. Il lui est interdit d'annoncer un résultat, une
progression, un succès ou un échec, et il **n'a aucun outil** : le tour complet
part déjà au cerveau, donc « supprime ce fichier du Drive » s'exécuterait deux
fois, ou s'exécuterait pendant que le cerveau décide qu'il ne faut pas. Aucune
formulation de prompt n'empêche cela ; seule l'absence de l'outil l'empêche.

Le cerveau, lui, vit dans Core (`BrainOrchestrator`). Il possède l'intention,
l'état public du travail et les identifiants de travail, et il parle par
demandes de parole typées. Couper la parole à JARVIS n'annule jamais un travail :
l'arrêt est local d'abord (PortAudio), l'annulation et la troncature côté
fournisseur ensuite, et le tour suivant porte simplement
`interrupted_speech_id` — c'est le cerveau qui décide de retenir, remplacer ou
annuler. `Jarvis Mute` arrête la voix, jamais le travail de Core, et ne réveille
jamais la voix pour prononcer un résultat que vous avez coupé.

### Le cerveau réflexe : faire patienter pendant que le cerveau réfléchit

En mode continu, la surface prononce au plus **une** phrase courte par tour
(« Je regarde ça. ») quand le cerveau n'a toujours rien dit au bout du délai
d'accusé. Le déclencheur est le silence, pas une déclaration de travail : le
cerveau répond le plus souvent lui-même, sans tâche de fond, et exiger un
`brain.work.started` corrélé l'a laissé muet du 13 au 18 septembre 2026
(51 décisions `work_unconfirmed` dans `runtime/trace.jsonl`, aucun réflexe
prononcé).

Ce qui l'empêche de parler à contretemps n'a pas changé : une réponse du cerveau
déjà prête annule le préambule avant qu'il ne commence à jouer
(`useful_content_ready`), un travail déjà terminé le retient (`work_terminal`),
un seul par tour (`already_used`), rien avant l'échéance
(`answer_may_arrive_quickly`), rien pendant que l'utilisateur parle, et rien sur
un simple « OK », une correction ou un « attends je réfléchis ». Chaque décision
est journalisée en `voice.reflex.decided` (action, `reason`, `phase`).

Trois réglages, dans cet ordre de précédence : le Control Center (onglet
**Mode vocal**, section Conversation : la case **Cerveau réflexe (mode continu)**
et le champ **Délai avant accusé de réception**), puis `JARVIS_REFLEX_ENABLED`
et `JARVIS_REFLEX_DELAY_MS`, puis les défauts (activé, 1200 ms). Un délai de `0`
ou la case décochée rendent le silence complet. `JARVIS_REFLEX_REQUIRE_WORK=1`
restaure l'ancienne porte. Le mode `legacy` n'a pas de réflexe : il reçoit
toujours un délai nul.

### Basculer, et revenir

Le plus simple : onglet **Mode vocal** du Control Center, champ
**Architecture**, puis redémarrage de Voice. Revenir en arrière, c'est choisir
« Un tour par appui » ou « Par défaut ». La variable reste le chemin sans
interface :

```powershell
# activer, dans le .env du projet ou l'environnement du processus Voice
$env:JARVIS_VOICE_ARCH = "continuous_brain"

# revenir en arrière : retirer la variable (ou la remettre à "legacy")
Remove-Item Env:\JARVIS_VOICE_ARCH
```

Core et Voice lisent la variable au démarrage : il faut relancer les deux
processus (le réglage du Control Center, lui, n'est lu que par Voice). Sans
`OPENAI_REALTIME_MODEL`, le modèle Realtime conseillé suit l'architecture
effective, y compris quand elle vient du Control Center. Le mode retenu est journalisé dans `voice.stack` et `voice.active`
(champ `arch`), et `surface_reflex_only` de `voice.stack` dit si le catalogue
d'outils envoyé au fournisseur était vide.

Le retour arrière n'est pas une écriture inverse : le défaut est **calculé** par
`default_voice_arch()`, seul endroit qui en décide. Retirer la variable ramène
donc mécaniquement à `legacy`.

### La porte bloquante : le mode continu ne peut pas devenir le défaut

`CONTINUOUS_BRAIN_DEFAULT_BLOCKERS`, dans `jarvis/v2_config.py`, contient
aujourd'hui `brain_calendar_access_unverified` et
`brain_reminder_access_unverified`. Tant que ce tuple n'est pas vide,
`default_voice_arch()` rend `legacy`, et un test échoue si le défaut bascule
alors qu'un bloqueur subsiste.

La raison est directe : en mode continu la surface perd **tous** les outils Core,
donc plus personne ne crée de rendez-vous ni de rappel par la voix — sauf si le
cerveau sait le faire. Or **son accès à l'agenda et aux rappels n'est pas
vérifié**. Seul Drive lui est atteignable, et uniquement si vous avez enregistré
le serveur MCP vous-même (`claude mcp add jarvis-drive …`, voir « Le même Drive
depuis Claude Code » plus haut) ; rien dans JARVIS ne l'enregistre pour vous.

Vider ce tuple est donc un acte délibéré, qui demande soit de câbler l'accès
manquant, soit d'acter l'écart par écrit. L'opt-in explicite, lui, n'est pas
bloqué : `JARVIS_VOICE_ARCH=continuous_brain` reste accepté aujourd'hui.

### Échouer bruyamment plutôt que dégrader

- Pile Gemini Live + `continuous_brain` → refus au démarrage de Voice : Gemini
  n'implémente pas les contrôles de sortie sémantiques.
- Fin de tour `manual` + `continuous_brain` → refus au démarrage : le mode
  continu repose sur le découpage de tours du fournisseur.
- Ces deux combinaisons sont aussi refusées par le Control Center à
  l'enregistrement (HTTP 400, message en clair), et signalées dans l'onglet
  Mode vocal si le fichier de réglages les contient déjà.
- Pile sans contrôle de sortie détectée à l'ouverture de session → état `ERROR`,
  trace `voice.arch_unsupported`, retour au fond.

### Où atterrit la télémétrie de latence

Six mesures, définies dans `jarvis/core/latency.py`. Elles passent par le même
journal que le reste : `runtime/trace.jsonl`, donc le panneau **TRC** du Control
Center. Chaque entrée porte `measure` et `elapsed_ms` dans `data`, ce qui les
rend toutes trouvables d'un même filtre.

| Mesure | `kind` de l'évènement | Clé de jointure | Processus |
| --- | --- | --- | --- |
| `speech_started` → premier audio de la surface | `voice.latency.surface_first_audio` | `segment_id` | Voice |
| transcription complète → tour accepté par le cerveau | `voice.latency.brain_turn_accepted` | `correlation_id` | Voice |
| parole demandée → premier audio du cerveau | `voice.latency.first_brain_audio` | `speech_id` | Voice |
| interruption détectée → sortie locale arrêtée | `voice.barge_in` (`stop_latency_ms`) | `speech_id` | Voice |
| travail démarré → première progression publique | `core.brain.latency.first_public_progress` | `work_id` | Core |
| travail démarré → terminé | `core.brain.latency.work_completed` | `work_id` | Core |

Les deux bornes d'une mesure sont toujours prises dans le **même** processus, sur
une horloge monotone : aucune ne traverse la frontière Core/Voice, et le
transport n'y est donc jamais compté. La dernière n'est pas émise pour un travail
en échec ou annulé — une panne n'est pas une durée d'exécution. Ces évènements ne
portent que des identifiants : `LatencyTracker` fabrique lui-même son message à
partir du nom de la mesure, un appelant ne peut pas y glisser de transcription.

### Ce qui n'est pas vérifié

Quatre points, à ne jamais présenter comme acquis :

1. **Aucune recette matérielle complète n'a tourné.** Le mode continu garde le
   micro ouvert pendant que les haut-parleurs jouent ; depuis le 11 septembre
   2026, cet écho est traité par une annulation d'écho WebRTC et une garde
   d'écho (`jarvis/audio/duplex.py`, rapport `docs/fixes/voice-duplex/`), dont
   les marges ne sont validées qu'en simulation. Sur poste, le journal dit quel
   mode tourne (`voice.duplex`) et trace chaque décision de barge-in et chaque
   transcript écarté. Depuis le 18 septembre 2026, `voice.barge_in_pending`,
   `voice.barge_in_confirming`, `voice.barge_in_rejected` et `voice.echo_learned`
   portent les niveaux du détecteur (`near_mic_db`, `near_ref_env_db`,
   `near_floor_db`, `near_coupling_db`, `near_excess_db`, `near_margin_db`,
   `near_warming_up`) : c'est de là que se lisent les marges réelles d'une pièce,
   sur haut-parleurs comme au casque. `legacy` reste le repli half-duplex.
2. **Aucune exécution contre le vrai OpenAI.** Le test de fumée
   `tests/integration/test_live_openai.py` couvre le chemin continu mais reste
   sauté par défaut et n'a pas été lancé.
3. **L'accès du cerveau à l'agenda et aux rappels n'est pas vérifié.** C'est le
   contenu même de la porte ci-dessus.
4. **Rien d'acoustique n'est mesuré pour Solo Owner** (mode propriétaire seul,
   plus bas). Seuil de reconnaissance, latence de confirmation, marges d'écho et
   conservation du début de phrase ne reposent que sur des voix de synthèse, que
   leurs propres fichiers de résultats déclarent « NOT evidence for production
   thresholds » (`docs/results/speaker-benchmark/`). Les valeurs par défaut sont
   **provisoires** jusqu'à la recette poste de travail :
   [`docs/HARDWARE_ACCEPTANCE.md`](HARDWARE_ACCEPTANCE.md) — enrôlement, journée
   en observation, dix scénarios, banc d'essai sur vraies voix (§5), parité
   état-du-travail, session longue, retour arrière.

Sur l'interruption, soyez précis : les tests automatisés prouvent l'ordre arrêt
local → annulation → troncature, et que l'historique ne prétend pas que
l'utilisateur a entendu ce qui a été tronqué. Ils ne prouvent **pas** que le son
cesse dans les haut-parleurs, ni en combien de millisecondes.

## Conversation mode: who may talk to JARVIS

Two independent settings, not to be confused:

- the **voice architecture** (`voice_arch`: `legacy` / `continuous_brain`, see
  above) selects the code path — one turn per press, or a continuous
  conversation;
- the **conversation mode** (`conversation_mode`) says who may produce user
  speech: any captured voice (`open_room`, the historical behaviour) or only the
  enrolled owner (`solo_owner`). It touches neither the architecture, nor the
  voice stack, nor end-of-turn detection (`server_vad` / `semantic_vad`).

In `solo_owner`, another voice must not interrupt JARVIS, become a turn, or count
as useful activity. The near-end detector stays a mere acoustic prefilter; the
authority on identity is a local speaker verifier. The types live in
`jarvis/domain/speaker.py`, settings parsing in `jarvis/v2_config.py`
(`parse_conversation_authorization`).

| Key in `runtime/control-center-settings.json` | Values | Absent or empty |
| --- | --- | --- |
| `conversation_mode` | `open_room`, `solo_owner` | `open_room` |
| `speaker_verification` | `off` (no verifier), `shadow` (it measures and logs, decides nothing), `enforce` (its verdict opens or closes the input) | follows the mode: `enforce` in `solo_owner`, `off` otherwise |
| `owner_buffer_ms` | integer from 500 to 5000: audio kept in memory while identity is confirmed, so the start of the sentence can be replayed | 2500 |

There is no environment variable: an older settings file without these keys gives
exactly the previous behaviour. The `owner_buffer_ms` buffer is distinct from the
short acoustic pre-roll of the duplex capture, and 2500 ms is a starting point
for measurement, not a value tuned on a workstation. The bounds come from this:
below 500 ms the buffer no longer covers a verifier's evidence window and the
start of the sentence would be lost; beyond 5 s, replaying the prefix would delay
the answer far more than the accepted confirmation latency.

### Combinations: rejected, degraded, refused at activation

Three levels, from the strictest to the latest:

1. **Invalid setting — rejected on save** (HTTP 400, nothing is written, plain
   message with a stable code): unknown value, non-integer or out-of-bounds
   buffer, `solo_owner` with `off` or `shadow` (`solo_owner_requires_enforce`:
   nothing would keep other voices out, and JARVIS would pretend to listen only
   to you), `open_room` with `enforce` (`enforce_requires_solo_owner`: nobody to
   keep out). A value hand-written in the file is flagged by the screen
   (`status: invalid`) without blocking saves of other settings.
2. **Observation impossible — degraded** (`open_room` + `shadow` without a usable
   verifier): the conversation stays open, as before, and the reason is shown
   (`speaker_verification_unavailable`).
3. **Solo Owner inapplicable — refused** (`solo_owner` without a verifier,
   without an enrolled owner voice, with a failed verifier, or under the `legacy`
   architecture): the setting is saved, but Voice does not listen in that mode
   and JARVIS does not silently fall back to the open room
   (`solo_owner_unavailable`, `solo_owner_requires_continuous_brain`). This is
   the "refuse and explain" policy of open question 5 of the handoff, enforced
   by Voice since task 07 (see "Solo Owner: only your voice is a turn").

To measure before enforcing, the path is `open_room` + `shadow`, then
`solo_owner` (verification `enforce`) once the measurements are accepted.

The screen reads all of this from `GET /api/settings`, under
`voice.authorization`: stored values (`stored`), effective values (`effective`),
choices and bounds, and the verdict (`status` = `ready` / `degraded` / `refused` /
`invalid`, `code`, `problem`), computed with the same function Voice uses (the
voice architecture included). While Voice runs, `runtime` adds what it actually
applied at its last activation; a refusal only Voice could see overrides the
verdict (`status_source = voice`). Saving goes through `POST /api/settings` with
`{"voice": {"authorization": {"conversation_mode": …, "speaker_verification":
…, "owner_buffer_ms": …}}}` — the same object also accepts the verifier tuning keys
`owner_threshold`, `owner_evidence_ms`, `owner_short_evidence_ms`,
`owner_short_margin` (validated by the same reader as Voice, cross-bounds included);
an empty value resets the key to its default. A refusal answers HTTP 400 with the
plain French message as body and the stable code in the `X-Jarvis-Error-Code`
header (`owner_threshold_invalid`, `owner_short_evidence_invalid`,
`solo_owner_requires_enforce`, …); nothing is written. `owner_profile_path` is
never written from the page (an arbitrary path from a browser could read or, at
enrollment, overwrite any file): it is shown read-only and changed only in the file.

### What the Control Center shows for Solo Owner and echo cancellation

Tab **Mode vocal** of the settings window (button **SET**), block **Qui peut
parler à JARVIS**, right under the architecture. The page only projects: every
verdict comes from the server (`assess_authorization`, the function Voice uses) or
from what Voice itself published; the page never decides who is speaking and never
receives a voiceprint (profile metadata only). The state is read when the window
opens (and by **relire l'état**); settings are read by Voice at start, so after a
change the block shows **Redémarrez Voice pour appliquer** (also shown while Voice
still applies older settings: `restart_required`).

- **Controls.** *Mode de conversation* (`open_room` / `solo_owner`),
  *Vérification du locuteur* (only the values compatible with the mode are
  offered: `off` / `shadow` in the open room, `enforce` in Solo Owner; "Selon le
  mode" = default; changing the mode goes back to the stored value and only
  resets it to the mode default when that stored value would be refused, so
  `open_room` + `shadow` → `solo_owner` → `open_room` keeps the `shadow`),
  *Tampon de rejeu du propriétaire*.
  **Réglages avancés — R&D** (folded): `owner_threshold`, `owner_evidence_ms`,
  `owner_short_evidence_ms`, `owner_short_margin` — measurement starting points,
  change them only after measuring (Tasks 09 and 14). Empty = default.
- **Verdict banner** — the first thing to read:

| Banner | Meaning |
| --- | --- |
| green « prêt · Solo Owner appliqué » | `solo_owner` + `enforce`, verifier ready: only your recognized voice interrupts and becomes a turn. « Constaté par Voice (activation, time) » when Voice confirmed it at its last wake, else « D'après la sonde des réglages » |
| red « refusé · Solo Owner configuré mais NON appliqué » | Solo Owner cannot enforce identity (no engine/model/profile, failed engine, `legacy` architecture, or a `continuous_brain` that Voice would refuse to start — Gemini Live stack, manual turn end: the banner then gives that reason, and the red architecture notice above says the same): Voice does not listen in that mode, no silent open-room fallback. The `problem` and `code` follow; « Constaté par Voice … » when only Voice could see the cause (engine that does not load, verifier lost mid-session: `status_source = voice`) |
| grey « prêt · Salle ouverte, vérification en ombre » | `open_room` + `shadow`: scores are measured and logged (`voice.owner.*`), nothing is filtered. Under « Un tour par appui » the banner adds that nothing is measured (shadow needs the continuous conversation) |
| orange « dégradé · observation dégradée » | shadow requested but nothing is measured: no usable verifier (probe), or Voice has no working verifier (`status_source = voice`, from the worker state) |
| grey « Salle ouverte » | historical behaviour, no identity check |
| red « Réglage invalide » | hand-written invalid value in the settings file; Voice refuses to listen until fixed |

- **Vérificateur de locuteur**: availability and stable `code`, engine
  (`sherpa-onnx/…`), model id, licence and presence, profile (id, `created_at`,
  enrolled speech duration, consistency) — never the voiceprint. While Voice runs,
  *Fil de vérification (Voice)*: the worker's availability and the milliseconds of
  windows dropped because its queue was full (`dropped_ms`, cumulated since Voice
  started; > 0 means the CPU could not keep up). When something is missing, the
  exact command to run is shown (`pip install -e ".[speaker]"`, `owner-voice
  download-model [--force]`, `owner-voice enroll --mic [--replace]` — stop Voice
  first for a microphone enrollment).
- **Valeurs effectives**: every value Voice would apply, with its origin
  (`réglage` = stored, `défaut`), the engine threshold when none is set, and the
  profile file path (read-only).
- **Annulation d'écho** (under the stack's settings):

| State | Meaning |
| --- | --- |
| `active` | requested and LiveKit installed; « Constaté par Voice » once Voice built the canceller |
| `dégradée` · `aec_not_installed` | requested, but LiveKit (AEC3) is not installed: Voice will run with the echo guard only (speak louder than JARVIS to cut him). Install `.[voice]`, restart Voice |
| `dégradée` · `aec_unavailable` | Voice could not build the canceller (library missing or failing to load) — seen by Voice |
| `dégradée` · `aec_failed` | the canceller failed during a session; Voice continues with the guard only until restarted (`voice.duplex`, `duplex_aec_failed` in the trace) |
| `dégradée` · `duplex_capture_unavailable` | the whole duplex capture failed: raw microphone, restart Voice |
| `désactivée` · `aec_disabled` | switched off in the stack's settings (guard only) |
| `sans objet` | « Un tour par appui » closes the microphone while JARVIS speaks — same verdict when the continuous conversation is asked for but Voice would refuse to start it (see the architecture notice) |

Where it comes from: the probe checks only that `livekit.rtc` is installed (the
native library is not loaded by the Control Center); the Voice state is the file
`runtime/.voice_capture` (written by Voice at each wake and at the end of each
session, read only while Voice's heartbeat is fresh) and appears in
`GET /api/settings` → `voice.echo_cancellation` (`configured`, `applicable`,
`installed`, `status`, `code`, `problem`, `status_source`, `runtime`,
`restart_required`) and `voice.authorization.worker`. Counters of dropped
non-owner utterances (`voice.input.non_owner_dropped`, `source = capture |
provider`) are not shown: read them in the trace (TRC panel or
`runtime/trace.jsonl`).

**State as of 12 September 2026 — what is wired, and what is not.** Everything
below is implemented and covered by the automated suite; **nothing has been
measured on the real microphone, with the owner's voice, against the real
provider** — that acceptance is
[`docs/HARDWARE_ACCEPTANCE.md`](HARDWARE_ACCEPTANCE.md) and it is still to be
run. The shipped verifier defaults come from a synthetic benchmark and are
provisional. A local verifier exists
(next section): when `speaker_verification` is not `off` and the engine, model and
owner profile are all usable, Voice (`continuous_brain`) scores the capture as it
comes out of the echo canceller and logs `voice.owner.*` events, without changing
a single byte of what reaches the provider. In the three `dégradée` states of the
table above there is no canceller in the path (`aec_disabled`,
`aec_not_installed` / `aec_unavailable`, `aec_failed`): the verifier then scores
the **raw microphone**, so while JARVIS speaks his own voice stays in the
evidence and the verdict is less reliable than the benchmark suggests. That is by
design — the degraded state is shown rather than the microphone being cut — but
it is a reason to fix the AEC before trusting `speaker_verification = enforce`. The screen reports the real verifier state (`verifier`, plus
`verifier_detail`: engine, model, stable `code`, profile metadata — never the
voiceprint). In `solo_owner`, barge-in and **everything** that reaches the
provider follow the owner — JARVIS speaking (replay buffer, task 06) or silent
(task 07): only your recognized voice becomes a turn (next paragraphs). A Solo
Owner that cannot apply is refused, never silently turned into the open room. The
mode, the verification and the tuning are chosen in the Control Center (tab
**Mode vocal**, block **Qui peut parler à JARVIS**, see above), the API or the file.

### Solo Owner barge-in: who can interrupt JARVIS

With `conversation_mode = solo_owner`, Voice in `continuous_brain` and a usable
verifier, only **your recognized voice** interrupts JARVIS while he speaks:

- someone else talking (or you, before recognition) does **not** lower JARVIS's
  volume and does not cut him — the open-room "drop to 30 %, then cut on the
  provider's confirmation" is off — and is **not sent to the provider** (it
  receives silence), so it cannot become a turn — nor when JARVIS is silent,
  since task 07;
- once the verifier confirms you, JARVIS stops locally at once, without waiting
  for the provider; the provider's cancel/truncate follow, and a refusal on its
  side only degrades the turn (`voice.barge_in_degraded`), never Voice;
- the provider's own speech detection (`speech_started`) never cuts in this mode,
  whether it comes before your recognition, after it, or not at all — it is only
  logged for correlation;
- a recognition while JARVIS is silent stops nothing; interrupting never cancels
  the brain's work.

Expect the cut ≈ 1.7–2 s after you start talking (the engine needs ~1.5 s of
voiced speech, `owner_evidence_ms`), instead of ≈ 0.3–0.5 s in the open room: the
handoff accepts a slower but correct interruption (D07). When someone else was
already talking, recognition takes longer — up to ≈ 4 s on the synthetic
benchmark at the default threshold, because your voice has to take over the
sliding window. The start of your
sentence is not lost: Voice keeps the last `owner_buffer_ms` of cleaned
microphone audio in memory and, right after the local stop and the provider
cancel/truncate, sends the part the provider never received — from your estimated
first syllable (minus 150 ms) — then the live microphone, once, in order.

**Owner replay buffer — memory and tuning.** Only in `solo_owner` (the open room
has no buffer). RAM only, never written to disk or to the trace. Size =
`owner_buffer_ms × input rate × 2 bytes / 1000`: 120 KB for the default 2500 ms at
24 kHz (OpenAI Realtime), 240 KB at 48 kHz. Read at Voice start: restart Voice
after changing it. If your recognition regularly comes later than the buffer, the
oldest part is dropped and `voice.owner.replay` is logged as a warning with
`code = owner_replay_clamped` and `clamped_ms` — raise `owner_buffer_ms` (max
5000). The replay is sent faster than real time; the provider's speech detection
handles it as one utterance and its `speech_started` then marks the replayed
segment (`voice.barge_in.provider_advisory`, `relation = after_owner_stop`,
`replay_ms`).

What the trace shows (`runtime/trace.jsonl`):

| Event | Meaning |
| --- | --- |
| `voice.barge_in.authority` | at activation: `authority = owner` (Solo Owner active); during a session, warning `input = closed`, `code = owner_verifier_unavailable` (verifier lost: input closed, session ends — see below) |
| `voice.barge_in.owner_confirmed` | you interrupted JARVIS: `confirm_ms` (speech start → recognition), `confirm_to_stop_ms`, `onset_to_stop_ms`, `provider_speech_started`, `provider_lead_ms` |
| `voice.barge_in.provider_advisory` | the provider heard speech: `relation = awaiting_owner` (JARVIS kept talking) or `after_owner_stop` (`lag_ms` behind the local stop, `replay_ms` of the replay it heard) |
| `voice.owner.replay` | the start of your sentence was replayed: `owner_onset_ms`, `confirmed_ms`, `stop_stream_ms`, `replay_from_ms` / `replay_until_ms` / `replay_ms`, `already_sent_ms` (audio the provider already had), `clamped_ms` + warning when the buffer was too short, `buffer_ms` — all on the capture clock, no audio |
| `voice.barge_in_pending` / `voice.barge_in_rejected` with `authority = owner` | nearby speech detected / the verifier's candidate ended; volume untouched |
| `voice.authorization_invalid` | at Voice start: the settings file holds an invalid authorization; Voice will refuse to listen until it is fixed |
| `voice.authorization_refused` | Solo Owner refused or suspended: `code`, `phase` (`startup`, `activation`, `session`), French message with the way out — see "Solo Owner: only your voice is a turn" |

**Rollback.** Set `conversation_mode` back to `open_room` (or remove the key) and
restart Voice: barge-in is exactly the previous acoustic one (duck, then cut on
the provider's confirmation), every voice reaches the provider again, and no
`voice.barge_in.authority` event is logged. `speaker_verification = shadow` keeps
measuring without deciding anything. The voice architecture is independent:
`legacy` stays the half-duplex fallback (and refuses Solo Owner).

### Solo Owner: only your voice is a turn

With Solo Owner active, the rule is the same whether JARVIS speaks or is silent:
**only your recognized voice reaches the provider** (OpenAI Realtime). Colleagues
can talk for as long as they like next to you: nothing of what they say is sent,
transcribed, answered or passed to the brain; it does not keep the session alive
(the useful-activity timeout keeps running), creates no acknowledgement and no
work. Your own speech works as before once recognized: addressed sentences
become turns and re-arm the timeout; a sentence that does not look addressed to
JARVIS (long, third person, outside the conversation window) goes to the brain
marked *uncertain*, without re-arming anything (Decision 44). JARVIS never
decides who you are from the words: the identity check comes first.

What to expect:

- **Your turn starts ≈ 1.6–2 s after you start talking** (the verifier needs
  ~1.5 s of voiced speech). Nothing is lost: the start of your sentence is
  replayed from memory the moment you are recognized, then the live microphone.
- **Short replies** (« oui, vas-y », « non merci », « stop JARVIS ») are judged
  once, when you stop talking (after the 600 ms pause that ends your speech),
  against a stricter threshold, then replayed whole: expect the answer to start
  ≈ 0.6–0.8 s after you stop. A lone monosyllable (« oui » alone, under ~600 ms of
  voice) is still too short to recognize and is dropped — say a few more words.
  A short « stop » while JARVIS speaks interrupts him.
- **While someone else talks, JARVIS waits for the verdict before starting a new
  sentence** (≈ 2 s at most per utterance, it might be you), then carries on; it
  never waits indefinitely. Their speech may cancel a pending « je m'en occupe »
  acknowledgement, never create one.
- **Colleague right after you, without a pause**: the first words of their
  sentence (≈ 1 s, at most ≈ 1.2 s) can still be appended to *your* turn before
  the verifier notices the change; they never form a turn of their own. With a
  pause of 600 ms or more between you, nothing of theirs is sent.

**Refused, not faked.** If Solo Owner cannot apply, Voice does not listen at all
in that mode and says why — never a silent fallback to the open room. Each wake
is refused with `voice.authorization_refused` in the trace, the message on
JARVIS's alert, and the Control Center reports the same reason in
`GET /api/settings` → `voice.authorization` (`status: refused`, `code`,
`problem`; `runtime` holds what Voice actually applied while it runs,
`status_source: voice` when only Voice could see the cause):

| `code` | Cause | What to do |
| --- | --- | --- |
| `solo_owner_unavailable` | no verifier engine or model, no enrolled owner voice, or the engine failed (see `verifier` / `verifier_detail`, and `voice.owner.unavailable` in the trace) | install the extra and the model, enroll (`jarvis owner-voice enroll --mic`), or roll back |
| `solo_owner_requires_continuous_brain` | voice architecture `legacy`, or a `continuous_brain` Voice would refuse to start (Gemini Live stack, manual turn end — the banner names which) | choose `continuous_brain` with the OpenAI Realtime stack and automatic turn end, or roll back |
| `solo_owner_capture_unsupported` | the duplex capture has no owner replay buffer (should not happen with a normal install) | restart Voice; report it |
| a settings code (`conversation_mode_unknown`, `solo_owner_requires_enforce`, `owner_buffer_out_of_range`, …) | hand-written invalid value in `runtime/control-center-settings.json` (screen: `status: invalid`); refused already at Voice start | fix the value or remove the keys, then restart Voice |

**Verifier lost during a session.** If the verifier fails while a session is
active, the input is closed at once (nothing the microphone captures is sent),
JARVIS is never switched to the open-room rule, the session goes back to the
background, and the alert says: « Mode Solo Owner suspendu : le vérificateur de
locuteur ne répond plus… ». Wake JARVIS again to retry (the engine gets a new
chance at each wake); if it keeps failing, roll back to `open_room` and restart
Voice.

**Troubleshooting.**

- *JARVIS ignores me*: check `voice.owner.confirmed` / `voice.owner.rejected` for
  your speech. `voice.input.non_owner_dropped` with `source = capture` lists the
  utterances that were not recognized as yours: `reason = non_owner` (judged not
  you, `best_score` below the threshold — re-enroll in the usual position, or
  lower `owner_threshold` carefully), `short_not_owner` (short reply below the
  stricter threshold — raise `owner_short_margin` only after measuring false
  accepts), `insufficient_audio` (too short to judge), `candidate_ms` the length.
- *A colleague's words appear in my turn*: they spoke right after you without a
  pause — see the handover bound above; lower `owner_short_evidence_ms` (shorter
  recent window, faster handover, more risk of cutting your own sentence) only
  after hardware measurement (`docs/HARDWARE_ACCEPTANCE.md`).
- *`voice.input.non_owner_dropped` with `source = provider`*: the provider
  segmented audio outside your recognized speech (should not happen; the trace
  carries only the reason, never the text).

Optional settings for short replies and handover (Control Center **Réglages
avancés — R&D**, the API or the file; read at Voice start; the defaults below were
kept by the task 14 synthetic benchmark — three short replies were still confirmed at
every threshold tried — and are tuned on the workstation with
[`docs/HARDWARE_ACCEPTANCE.md`](HARDWARE_ACCEPTANCE.md)):

| Key | Meaning | Default |
| --- | --- | --- |
| `owner_short_evidence_ms` | minimum voiced speech for a short reply judged at the end of its utterance, and length of the recent window that detects a handover; `0` disables both; 300 up to `owner_evidence_ms` − 1 | 600 |
| `owner_short_margin` | stricter threshold for short replies = `owner_threshold` + margin; handover floor = `owner_threshold` − margin; 0–0.3 | 0.1 |

### Local speaker verifier: engine, model, enrollment

Baseline engine, kept by the task 14 benchmark for its accuracy/cost ratio — **not**
a final choice: only real voices settle it (`docs/HARDWARE_ACCEPTANCE.md` §5).

| | |
| --- | --- |
| Library | `sherpa-onnx` 1.13.8 (+ `sherpa-onnx-core` 1.13.8, bundles ONNX Runtime), Apache-2.0, Windows wheel `cp314-win_amd64` |
| Model | `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx` — 3D-Speaker CAM++ trained on large Chinese + English speaker sets, 16 kHz, 192-dim voiceprint |
| Model source | `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx` (upstream card: ModelScope `iic/speech_campplus_sv_zh_en_16k-common_advanced`) |
| Model license | Apache License 2.0 (ModelScope model card) |
| Model SHA-256 | `aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2` (28 281 164 bytes, matches upstream `checksum.txt`) |
| Code | `jarvis/adapters/sherpa_speaker_embedder.py` (engine, pinned model), `jarvis/adapters/owner_voice_profile.py` (profile file), `jarvis/audio/owner_verifier.py` (rolling window, score, threshold), `jarvis/runtime/owner_voice.py` (probe, factory, CLI) |

The 512-dim English-only VoxCeleb CAM++ export from the same release was tried first
and rejected: it separated neither synthetic nor public sample speakers.

Install (the extra is optional; without it nothing is verified and Solo Owner is
refused):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[speaker]"
.\.venv\Scripts\python.exe -m jarvis owner-voice download-model   # ~28 MB, SHA-256 checked before install
```

**Where things live.** Everything is under the runtime directory
(`JARVIS_RUNTIME_DIR`, default `runtime/`, entirely ignored by Git):
`runtime/speaker-verification/models/<model>.onnx` and
`runtime/speaker-verification/owner-voice-profile.json`. `.gitignore` also ignores
`speaker-verification/`, `owner-voice-profile*.json` and `*.onnx` anywhere in the
repository. The profile is a small JSON file: `profile_id`, engine `name/version`,
model id and SHA-256, embedding dimension, sample rate, enrolled speech duration,
segment count, consistency, `created_at`, and the averaged voiceprint. No
enrollment audio is kept. The voiceprint is biometric: it never appears in the
trace, the terminal, or HTTP payloads. It is not encrypted at rest (open decision);
the file is written atomically, mode 0600 where the OS supports it. The final
rename is retried for about a second when Windows briefly refuses it (an antivirus
or the indexer holding the file); if it still fails, the enrollment stops with
`owner_profile_write_failed` and the previous profile is left intact — never a
half-written voiceprint. The same applies to the model downloads
(`speaker_model_install_failed`) and to the Control Center settings file, whose
save answers HTTP 503 with `X-Jarvis-Error-Code: settings_write_failed` once the
retries are exhausted; its temporary file is deleted in that case, so no API key
is left readable beside the settings.

**Enroll the owner** (the owner must do this; stop Voice first so the microphone is
free). Use the same microphone as Voice, in the usual position, in a quiet room:

```powershell
.\.venv\Scripts\python.exe -m jarvis owner-voice enroll --mic            # reads for 30 s (--seconds N)
.\.venv\Scripts\python.exe -m jarvis owner-voice enroll --wav a.wav b.wav # or from PCM WAV files
.\.venv\Scripts\python.exe -m jarvis owner-voice show                     # status + metadata, exit 0 when ready
.\.venv\Scripts\python.exe -m jarvis owner-voice score test.wav           # replay a file in 100 ms hops (shadow)
.\.venv\Scripts\python.exe -m jarvis owner-voice delete                   # remove the profile
```

Input requirements: PCM WAV 8/16/24/32-bit, any sample rate, mono or multi-channel
(channels are averaged, audio is resampled to 16 kHz); the microphone is recorded
in mono 16 kHz, in memory only. An energy gate keeps voiced frames only; at least
**10 s of speech** is required (`enrollment_too_short` / `enrollment_no_speech`
otherwise), 20–30 s recommended. A low `consistency` (< 0.3) warns about several
voices or heavy noise. An existing profile is never overwritten without
`--replace`. `--profile PATH` (before the sub-command) targets another file (it
must still resolve inside the runtime directory).

Every foreseeable failure of these commands exits 1 with a French message and a
stable code in brackets, never a traceback: no network on `download-model`
(`speaker_model_download_failed`), microphone still held by Voice on
`enroll --mic` (`enrollment_device_unavailable` — stop Voice, the microphone is
not shared), no interactive terminal (`enrollment_aborted`), missing audio
library (`enrollment_audio_unavailable`). Anything else is a real bug and is
still reported as a traceback.

**Turn shadow measurement on**: set `speaker_verification` to `shadow` with
`conversation_mode` `open_room` (Control Center, tab **Mode vocal**, *Vérification
du locuteur* = « En ombre » ; or API `POST /api/settings` with
`{"voice": {"authorization": {"speaker_verification": "shadow"}}}`, or the file),
then restart Voice in `continuous_brain`. At the first wake the trace shows
`voice.owner.engine` (engine, model, profile, threshold, window) — or
`voice.owner.unavailable` with a stable `code` (`speaker_engine_not_installed`,
`speaker_model_missing`, `speaker_model_mismatch`, `owner_profile_missing`,
`owner_profile_corrupt`, `owner_profile_incompatible`, `owner_threshold_invalid`…)
and the capture stays exactly as before. Then `voice.owner.candidate`,
`voice.owner.confirmed` / `voice.owner.rejected` carry scores and durations: one
`candidate` per stretch of sustained near-end speech (JARVIS's echo alone and
keyboard clicks never open one), `confirmed.confirm_ms` = time from the start of
that speech to owner recognition (expect ≈ 1.5–2 s: the engine needs 1.5 s of
voiced speech), `after_non_owner = true` when someone else was talking first,
`rejected.reason` = `non_owner` or `insufficient_audio` (too short to judge).

Optional keys in `runtime/control-center-settings.json` (no environment variable;
empty = default; the first two are also Control Center **Réglages avancés — R&D**
fields, the profile path is shown read-only and changed only in the file):

| Key | Meaning | Default |
| --- | --- | --- |
| `owner_threshold` | decision threshold on the common score scale ]0, 1] | engine default, 0.6 (provisional, task 14) |
| `owner_evidence_ms` | voiced speech per verdict (sliding window, and minimum before the first verdict), 500–4000 | 1500 |
| `owner_profile_path` | profile file; relative paths start at the runtime directory, and the resolved path must stay inside it (otherwise `owner_profile_path_outside_runtime`: the voiceprint is biometric and stays in the git-ignored area) | `speaker-verification/owner-voice-profile.json` |

Score and threshold: `owner_score` is the cosine similarity between the window's
voiceprint and the owner's, clipped to [0, 1] (negative = surely not the owner).
The model card's 0.33 is calibrated on full utterances; on 1–2 s windows impostor
scores reached ~0.45 in our synthetic and public samples while the enrolled voice
stayed above ~0.6. The default is **0.6 since task 14** (it was 0.5): on the
synthetic benchmark (`docs/results/speaker-benchmark/2026-09-12-synthetic.json`,
`engines[].gate_sweep[]`), 0.5 still let the input gate open on 4 of 24 colleague
turns and forward 11.1 s of their speech; 0.6 brings that to 1 turn and 6.7 s for a
confirmation P50 of 1650 ms instead of 1600 ms, at the price of 3 of the owner's 39
turns never forwarded (`owner_gate_miss_rate` 7.7 %); 0.65 — no false opening at
all there — misses one owner turn in ten. It is **provisional**: tune it on the
workstation with real voices, following
[`docs/HARDWARE_ACCEPTANCE.md`](HARDWARE_ACCEPTANCE.md) §5 (evidence:
`docs/results/speaker-benchmark/`, synthetic).

Cost of the production baseline, from
`docs/results/speaker-benchmark/2026-09-12-synthetic-settled.json`
`engines[0].resources` (i7-12700H, one ONNX thread): one voiceprint of a 1.5 s
window 30.1 ms p50 / 46.3 ms p95 (`scoring_hop_ms`, one per 500 ms of new
speech); a hop without scoring 0.25 ms p50 (`hop_ms.p50`); 3.51 % of one core
over the whole replay (`cpu_pct_one_core`); SHA-256 verification + model load
33.1 + 517.6 ms once, on the verifier thread at the first wake (never on the
asyncio loop), and +107.4 MB of steady RSS. The earlier runs of the same code
report up to 865.5 ms of load under contention — treat these as orders of
magnitude, not as a specification, and remember the audio is synthetic.

### Speaker-verification benchmark

Engines, thresholds and evidence windows are compared with
`scripts/benchmark_speaker_verification.py` (`models`, `generate-synthetic`, `run`),
which replays labelled WAV scenarios through the production `SpeakerVerifier` port and
reports FAR / FRR, confirmation latency, overlap handling, threshold sweep + EER, CPU,
RAM and load time as JSON + CSV + Markdown. A second replay (`--gate-thresholds`) runs
the same audio through the **real capture, verifier thread and input gate** and reports
what the provider would actually receive: owner turns forwarded, false openings,
colleague audio leaked at a handover, replays clamped by `owner_buffer_ms`. That block
is what a Solo Owner threshold is chosen on. Usage, manifest format, metric definitions
and how to choose: [`docs/SPEAKER_BENCHMARK.md`](SPEAKER_BENCHMARK.md); the workstation
protocol is [`docs/HARDWARE_ACCEPTANCE.md`](HARDWARE_ACCEPTANCE.md).
Owner recordings stay under `runtime/speaker-verification/benchmark/private/` (ignored);
published results live in `docs/results/speaker-benchmark/`. Synthetic TTS results are
not evidence for production thresholds.

### Reading a session back

`scripts/summarize_voice_trace.py` turns `runtime/trace.jsonl` into the numbers the
acceptance asks for — owner confirmation P50/P95, onset → local stop, replays clamped,
utterances dropped by source and reason, refusals, and the work-state revisions the
brain saw — without opening megabytes of JSONL:

```powershell
.\.venv\Scripts\python.exe scripts\summarize_voice_trace.py runtime\trace.jsonl
.\.venv\Scripts\python.exe scripts\summarize_voice_trace.py runtime\trace.jsonl --json --since 2026-09-12
```

It reads declared scalars only: no transcript, no voiceprint, nothing else ever
reaches its output.

### Speech presentation metrics

`scripts/measure_speech_metrics.py` (implementation `jarvis/testlab/speech_metrics.py`)
reads the Conversation Events journal of Core back and answers the closing questions
of the stale-speech work (task `jarvis-voice-stale-speech-presentation`): does a Live
speech free the mouth when it has been heard, did an answer written for an earlier
question start anyway, how long did a current answer wait in the queue. It never
writes: the database is opened `mode=ro` + `PRAGMA query_only` through the Test Lab
reader (`read_session_events`), the trace through `read_session_trace`.

```powershell
# the reference windows of 18-21/09 and of the 28/09 12:54-12:59Z session
.\.venv\Scripts\python.exe scripts\measure_speech_metrics.py --db data\state\jarvis.sqlite3 --snapshot --baseline
# a new session, compared with the reference windows, with the trace for stalls
.\.venv\Scripts\python.exe scripts\measure_speech_metrics.py --db data\state\jarvis.sqlite3 --snapshot `
    --baseline --window apres=2026-10-01T09:00Z..2026-10-01T10:00Z --trace runtime\trace.jsonl
# one voice session, JSON for an agent
.\.venv\Scripts\python.exe scripts\measure_speech_metrics.py --db data\state\jarvis.sqlite3 --session <id> --json
```

Windows are UTC, end excluded (`--to 2026-09-21` means the end of that day); a speech
belongs to the window where it is first seen. Several windows print side by side
(before/after). Exit code 0 measured, 2 usage, 3 the journal could not be read.

**Snapshot.** `--snapshot` copies the database file **without** its `-wal` into a
temporary folder (`--snapshot-dir` keeps it) and measures the copy: the original is
never opened by SQLite. The WAL view is checked on a second private copy; the tool
warns when it fails `integrity_check` (the stale WAL of 2026-09-28, Issue
`tasks/jarvis-voice-stale-speech-presentation/Issues/journal-wal-corrupt.md`) and when
the WAL holds events the file lacks — then `--snapshot-with-wal` measures that view,
and refuses it if it is malformed. Without a snapshot the live file is read as is and
a failed `quick_check` is reported.

| Metric | Definition | Target |
| --- | --- | --- |
| Live mouth release after quiescence, p95 | `release_after_quiescence_ms` of Live `mouth.speech.completed` with `completion_basis=local_quiescence` | < 1 s |
| `speech_output_stalled` on Live | `voice.speech.output_stalled` lines of the trace with a `live:` correlation; not measured (never "0") without a trace covering the window | 0 |
| Live `delivery_not_complete` at ~30 s | Live `mouth.speech.interrupted` `delivery_not_complete` lasting 29.5–30.5 s: the 30 s safety net, journal side | 0 |
| Outdated formulation started | a `result`/`question`/`error` speech started while a newer turn of its conversation was current, unless its own turn is at least as new or its chain (`parent_event_id`) had already started before that turn. A turn is current from `brain.turn.accepted`; an `uncertain` one only once promoted, i.e. from its first speech (`brain.speech.requested` / `mouth.speech.*` under its correlation — `brain.turn.unpromoted` is not a conversation event) | 0 |
| Held then started | a speech with `mouth.speech.held` that later has `mouth.speech.started` (a re-emission is a new speech) | 0 |
| Current-intent queue wait, p95 | for started speeches neither outdated nor held: start − the latest of queued, end of the speech in progress, end of a floor freeze (`mouth.floor.released`) | < 2 s |
| Relay violations | `brain.speech.requested` joined to `core.brain.notice_relayed` without `kind`, or `ack`/`progress` without `expires_at`. Before the Slice 03 cut-off (`SLICE_03_CUTOFF`, 2026-09-29, or the first typed relay seen if earlier) a relay had no trace kind: `result` requests without work or key are then counted as `legacy_heuristic` (untyped relays) and added to this target; after it that shape is a plain brain answer and never counted | 0 |

Also reported: per surface (`live:` / `realtime:` correlation, else the session's
surface) the terminal status × reason of started and never-started speeches, the
duration started → end by `completion_basis` or reason, `unconfirmed` speeches; held
speeches by reason and verdict (`revalidated_as`, `not_revalidated`,
`held_for_brain_timeout`); the floor taken / released by reason and duration; and on
Live the time from a barge-in to the next speech heard (Issue
`live-barge-in-mutes-incarnation.md`).

**Live pauses between sentences** (sizing of `LIVE_COMPLETION_GRACE_MS`, 500 ms): each
Live speech ended by local quiescence carries on `mouth.speech.completed` the silences
of at least 150 ms (`LIVE_PAUSE_FLOOR_MS`; shorter is block jitter) that audio ended
during the grace: `live_pause_count`, `live_pause_max_ms`, `live_pauses_ms` (first 8).
The tool reports per window the pause p50/p95 (over the kept values), the longest
pause, and the speeches whose longest pause reached 0.8 × the grace — the ones a
slightly longer pause would have ended early. A pause longer than the grace is not
a pause for the mouth: it ends the speech, and the next one starts; it shows only as
Jarvis starting the next answer too early (HV ressenti). Completions recorded before
this measure existed are not counted (`speeches_measured`).

## Configuration des sous-agents

### Contrat backend Agent / CLI

Le backend expose maintenant dans `GET /api/settings` :

- `cli.delegation_mode`: `auto` ou `duplicate` ;
- `cli.delegation_mode_metadata`: libellés, aide et persistance canonique ;
- `cli.behavior.values` et `cli.behavior.fields`: verbosité puis
  politesse/formalité.

`POST /api/settings` accepte la même projection sous `cli`. Il n'enregistre
jamais `delegation_mode` : Auto écrit `agent_routing.enabled=true`, Dupliqué
écrit `false`, sans supprimer les profils ni leurs candidats. Dupliqué
conserve le choix modèle du CLI/appelant et ne signifie jamais deux appels.
L'ancien bloc `routing` reste accepté pendant la migration; envoyer les deux
formes avec des valeurs contradictoires refuse toute l'écriture.

Les préférences de réponse sont stockées sous `agent_behavior`. La valeur
`inherit` n'ajoute aucun octet au prompt. Les autres valeurs passent par la
composition commune `backend.turn.addition` pour Claude et Codex, sur les
routes Agent `ask` et `send` comme sur les jobs possédés. Ajout de tour sauvegardé
et comportement généré partagent une borne de 8 192 caractères, validée avant
toute écriture. Détails et contrat de test : `docs/settings/INDEX.md`.

L'onglet **Agent / CLI** place les réglages techniques avant le comportement et
le catalogue. Le mode **Dupliqué** conserve le modèle du CLI/appelant sans
dupliquer l'exécution. Le mode **Auto** applique à chaque profil le premier
candidat autorisé *et* utilisable. Les profils et recours restent accessibles
sous **Configuration avancée des sous-agents**.

Quatre profils : **Poste de travail** (navigateur, fichiers ouverts), **Code
avancé**, **Sémantique rapide**, **Général** — ce dernier servant aussi de
recours aux autres. Les candidats affichés viennent de `GET
/api/routing/candidates`, qui sonde les CLI installés et demande au fournisseur
sa liste de modèles ; rien n'est écrit en dur dans la page. Un candidat s'ajoute
**en deux temps — le harness, puis un de ses modèles** : une liste unique de tous
les couples harness × modèle devient illisible dès qu'un fournisseur en déclare
vingt. **L'ordre de la liste retenue est la préférence** : le premier disponible
gagne, les suivants sont des recours, et « monter » change le préféré.

Un candidat enregistré qui disparaît (clé retirée, modèle déprécié) reste
affiché, marqué indisponible avec la raison. C'est voulu : un réglage qui
s'efface en silence est pire qu'une erreur.

Le cerveau ne nomme pas de modèle, il nomme un profil, en commençant la
description de chaque sous-agent par `[code]`, `[desktop]`, `[fast]` ou
`[general]`. Ce qu'il demande n'engage rien : un hook `PreToolUse` déclaré au CLI
corrige le modèle avant que l'appel parte.

Pour comprendre un choix :

```powershell
Select-String -Path runtime\trace.jsonl -Pattern 'agent.routing.decided' | Select-Object -Last 5
```

Chaque entrée porte le profil, le modèle demandé, le modèle retenu, la raison
(`preferred`, `fallback`, `general_fallback`, `override`, `compatibility`) et le
verdict de chaque candidat écarté (`model_unavailable`, `missing_capability`,
`unknown_candidate`, `not_allowed`…). `agent.routing.failed` signale un hook en
panne : dans ce cas le CLI a gardé la main, rien n'a été imposé.

Si aucun candidat n'est utilisable pour un profil, le lancement du sous-agent est
refusé, en clair, avec un renvoi aux réglages. C'est le comportement attendu tant
qu'aucun agent capable n'est installé — par exemple pour le profil Poste de
travail si le CLI actif ne pilote pas la machine.

## Auto-développement

Deux crans distincts, **éteints tous les deux à l'installation** :
`self_development.enabled` autorise à construire un candidat,
`self_development.auto_deploy` autorise à le déployer. Le second refuse de
s'allumer seul.

Le plan de construction est un dossier frère `sub-agents` (ou `sous-agents`)
contenant des worktrees git de ce dépôt. `JARVIS_WORKTREE_ROOT` force le chemin.
Ajouter un worktree :

```powershell
git worktree add ..\sub-agents\jarvis-agent-02 -b agent/jarvis-agent-02
```

Un deuxième ou un troisième ne demandent aucun changement : ils sont découverts,
et deux chantiers travaillent alors en parallèle. L'intégration, elle, reste
sérialisée.

Inspecter l'état :

```powershell
curl.exe -s http://127.0.0.1:17654/api/self-dev | ConvertFrom-Json
```

On y lit les deux autorisations, la racine du pool, chaque worktree avec sa
branche, son état propre/sale et son bail éventuel, les chantiers connus, et le
déploiement en cours s'il y en a un. Les fichiers correspondants :

| Quoi | Où |
| --- | --- |
| Baux des worktrees | `runtime/worktree-leases/*.json` |
| Chantiers | `runtime/self-dev/*.json` |
| Verrou d'intégration | `runtime/integration.lock` |
| Déploiement en cours ou passé | `runtime/deployment.json` |
| Demande de rechargement | `runtime/reload.request` |

### Ce qui bloque un déploiement, et pourquoi c'est voulu

- `deploy_primary_dirty` — la copie qui sert a des modifications non validées.
  Validez-les ou mettez-les de côté **vous-même** : JARVIS ne remise ni n'efface
  le travail de personne.
- `deploy_primary_branch` — la copie qui sert n'est pas sur `main`.
- `deploy_primary_diverged` — elle a des commits que le distant n'a pas.
- `deploy_conflict` — le candidat entre en conflit avec `main` : la fusion est
  annulée, le worktree retrouve son état, le chantier doit reprendre. Aucun
  conflit n'est résolu automatiquement.
- `deploy_gate_failed` — les tests refusent le candidat une fois réconcilié.
- `deploy_locked` — une autre intégration est en cours.

### Retour en arrière

Un déploiement n'est confirmé (`committed`) que lorsque Core répond prêt après le
rechargement. Sinon la copie qui sert est **détachée** sur la révision qui
marchait : aucun commit ne disparaît, `main` garde la révision fautive, et c'est
à vous de décider ce qu'on en fait. Revenir ensuite sur `main` une fois le
problème corrigé :

```powershell
git -C C:\Projects\jarvis\jarvis switch main
```

Si quelqu'un a modifié la copie qui sert entre-temps, le retour en arrière
s'arrête en `deploy_rollback_unsafe` plutôt que d'écraser ce travail : le
déploiement reste `blocked` et attend une décision humaine.

Un déploiement interrompu (processus tué au mauvais moment) est repris au
démarrage suivant à partir de `runtime/deployment.json` seul.

N'utilisez jamais `git reset --hard`, `git push --force` ni `git stash` pour
débloquer une de ces situations : rien dans le chemin automatique ne le fait, et
c'est précisément ce qui rend l'auto-modification acceptable.

## Tests

Fast full suite:

```bash
python -W error::ResourceWarning -m pytest -q
```

Tool Brain replay and evaluation (deterministic, no model, a few seconds; part of the fast suite as `tests/unit/test_tool_brain_replay.py`):

```bash
python -m tests.replay.tool_brain_replay
```

Release verifier:

```bash
python scripts/verify_release.py
```

Opt-in real-provider transcription smoke:

```bash
JARVIS_LIVE_OPENAI=1 OPENAI_API_KEY=... python -m pytest -q tests/integration/test_live_openai.py
```

## Mode PRESENTATION : runbook de l'opérateur

PRESENTATION est un **mode**, pas une architecture. Il se choisit dans le
Control Center (sélecteur de gauche, `SIMPLE` / `PRESENTATION`), il change **à
chaud**, et il ne redémarre jamais Voice : `interaction_mode` n'entre pas dans
`VoiceComposition.configuration_id` (Décision D15). Repasser sur `SIMPLE` rend
le comportement d'avant, exactement.

### Ce qu'il faut avoir avant d'entrer en PRESENTATION

| Il faut | Sans quoi |
| --- | --- |
| `python -m jarvis core` démarré | le mode ne peut pas être publié, et Voice reste sur son dernier mode connu |
| une pile vocale **OpenAI** | la salle n'est pas transcrite : la voie ambiante reste sourde, et PRESENTATION n'écoute que l'adresse explicite (voir *Blocages nommés*) |
| le CLI d'agent réglé sur **Claude** | aucune préparation spéculative n'est lancée |
| `scene.enabled` | rien ne peut être préparé à l'écran (un visuel préparé est un objet de scène masqué) |
| une clé Porcupine (facultatif) | le mot d'éveil n'existe pas ; la touche manuelle (`F9` par défaut) suffit à adresser JARVIS |

### Ce qui se passe à l'entrée

Dans cet ordre, et l'ordre est la garantie :

1. la pile d'éveil de SIMPLE est **suspendue** — c'est ce qui ferme le flux
   Porcupine et le retire du registre de propriétaires ;
2. les objets de scène montés par une séance précédente mal terminée sont
   **repris** (archivés) avant qu'un seul objet neuf ne soit posé ;
3. le hub de capture ouvre **l'unique** flux d'entrée du processus ;
4. la mémoire de séance, la voie ambiante, la préparation spéculative, la
   vérification et le tour adressé sont liés à une séance neuve.

À la sortie, l'ordre inverse : la séance est arrêtée (le micro est rendu) puis
la pile d'éveil de SIMPLE est reprise.

### Lire la trace

Tout est dans `runtime/trace.jsonl`. Les natures qui comptent :

| `kind` | Ce que ça dit |
| --- | --- |
| `presentation.runtime.entered` / `.left` | la séance s'est ouverte / fermée, avec le compte de flux d'entrée |
| `presentation.runtime.entry_failed` | **PRESENTATION n'a pas pris le micro.** JARVIS reste adressable, mais n'écoute pas la salle |
| `presentation.runtime.diagnostics` | le relevé périodique (30 s) : file, arriéré, travaux en vol, latence du déclencheur |
| `presentation.runtime.reclaimed` | des objets d'une séance précédente ont été archivés au démarrage |
| `presentation.audio.started` / `.device_lost` | la capture partagée |
| `presentation.ambient.*` | la voie ambiante : segments, transcriptions, refus, surdité |
| `presentation.preparation.*` | les sous-agents de préparation : outils retenus, réponses illisibles, verdicts écartés |
| `presentation.attention.*` | les contradictions jugées, levées ou refusées |
| `voice.presentation.turn_classified` | la situation retenue pour un tour adressé |
| `voice.presentation.turn_failed` | un tour adressé n'a pas pu s'ouvrir, se livrer ou parler |
| `voice.speech.presentation_decided` | ce que la politique de manifestation a fait d'une parole |

Un relevé sain, en pleine séance, ressemble à :

```jsonc
{"kind":"presentation.runtime.diagnostics",
 "data":{"physical_input_owners":1,       // 1, toujours. Autre chose est un défaut.
         "segments_pending":0,            // l'arriéré de transcription
         "analysis_pending":0,
         "enrichment_lag_entries":0,      // le retard de l'analyse sur la parole
         "speculative_in_flight":2,
         "trigger_latency_s":0.004,       // appui -> admission
         "ambient_deaf":false}}
```

### Relevé PRESENTATION dans le Control Center (Slice 10)

Voice écrit le relevé du coordinateur dans `runtime/.voice_presentation`
(`VisualSignalBus.presentation`) à l'entrée, à la sortie, au refus, aux
blocages nommés et à chaque relevé périodique ; il l'efface à l'arrêt de
Voice. `GET /api/status` le rend sous `presentation`, **`null` dès que Voice ne
bat plus**. Des scalaires seulement — jamais de parole de la salle — et une
clé inconnue ou d'un autre type est écartée par le Control Center. Toute valeur
texte est un **code** (sans espace, 64 caractères au plus,
`jarvis/domain/presentation_code.py`) : Voice l'applique à l'écriture, le
Control Center à la relecture, et une phrase devient `null` au lieu d'être
tronquée :

| clé | sens |
| --- | --- |
| `event` | ce qui a fait écrire le relevé : `entered`, `left`, `refused`, `entry_failed`, `blocked`, `tick` |
| `active`, `session_id` | une séance vit-elle, et laquelle |
| `entered`, `entry_failures`, `left`, `last_failure_code` | les compteurs du coordinateur |
| `blockers`, `blocker_code` | blocages nommés (transcription, exécutant) et le premier code |
| `physical_input_owners` | 1 en séance, toujours |
| `ambient_deaf`, `ambient_degraded`, `segments_pending`, `analysis_pending` | la voie ambiante |
| `trigger_latency_s`, `enrichment_lag_s` | latence du déclencheur, retard de l'analyse |
| `speculative_in_flight`, `speculative_free_explicit_slots`, `speculative_staged` | le bassin de préparation |
| `attention_live` | points à vérifier levés et pas encore retirés |
| `ts` | l'heure d'écriture (Voice) |

### Ligne de temps de la conversation (Slice 10)

La vue **CNV** montre pourquoi JARVIS s'est tu, a préparé, a été interrompu ou
a levé un point :

- lane *Jarvis · voix* : une parole retenue par la politique,
  `mouth.speech.superseded` `reason=presentation_withheld`, qui solde la
  demande du cerveau et se lit « retenue (présentation) » ;
- lane *Sous-agents* : chaque préparation, un bloc *Presentation Preparation*,
  fini, en échec (`status` `failed`/`timeout`) ou arrêté (`preempted`/`retired`) ;
- lane *Jarvis · voix*, rail de gauche : les repères
  `Mode présentation · entered|left|entry_refused|entry_failed` et
  `Point à vérifier levé|retiré`.

Aucun de ces événements ne porte la parole de la salle. Contrat :
`docs/conversation-events.md`, *Presentation events*.

### Diagnostic rapide

| Symptôme | Où regarder | Cause fréquente |
| --- | --- | --- |
| JARVIS n'entend rien du tout | `presentation.runtime.entry_failed` | un autre processus tient le micro, ou la pile d'éveil de SIMPLE ne s'est pas suspendue |
| JARVIS répond mais ne prépare rien | `ambient_deaf: true` dans le relevé | pas de transcription (pile non OpenAI, clé absente, fournisseur en panne) |
| rien n'est jamais préparé | `presentation.runtime.blocked` (code `presentation_runner_unavailable`) | le CLI d'agent n'est pas Claude. Dit **une fois**, à la première entrée en PRESENTATION — pas au démarrage, pour ne pas remplir la trace d'un opérateur qui reste en SIMPLE |
| `segments_pending` monte sans redescendre | `presentation.ambient.*` | la transcription est plus lente que la parole ; les segments les plus vieux sont jetés et comptés |
| `trigger_latency_s` grimpe | relevé + `explicit_address.stale` | la boucle d'évènements est chargée ; l'appui est **servi quand même**, jamais jeté |
| une commande visuelle ne dit rien | `voice.speech.presentation_decided` | c'est le comportement attendu : D09, le silence est un succès |
| JARVIS pose une question au lieu de montrer | `voice.presentation.turn_classified` | deux ressources également ancrées : il demande laquelle |
| **le Control Center dit PRESENTATION et il n'y a aucune ligne `presentation.runtime.*`** | `interaction.mode.observed` / `interaction.mode.ignored` | **le discriminant est là et nulle part ailleurs.** `.observed` : Voice a bien vu le mode, donc regardez `entry_failed` ou `entry_refused` juste après. `.ignored` : l'évènement est arrivé abîmé, le code dit lequel. **Ni l'un ni l'autre** : Voice n'a jamais reçu le changement — flux `/v1/events` coupé, ou processus Voice démarré avant ce commit |
| PRESENTATION est refusée avant même de prendre le micro | `presentation.runtime.entry_refused`, code `presentation_architecture_unsupported` | l'architecture vocale est « un tour par appui » (`voice_arch=legacy`) : aucun tour adressé ne peut s'y ouvrir, donc le micro n'est pas pris. Choisissez une architecture continue |
| les préparations s'arrêtent, puis reprennent par à-coups | `speculative_in_flight` au plafond dans le relevé + `presentation.speculative.preempted` | le bassin est plein (3 places par défaut, dont 1 réservée à l'explicite : 2 sous-agents spéculatifs). C'est la conception : le spéculatif est sacrificiel, et un tour adressé préempte. Rien à faire ; si cela gêne, voir *Bassin de préparation* ci-dessous |
| « montre-moi ça » ne change pas l'écran | `voice.presentation.turn_failed`, code `presentation_reuse_without_screen` | la ressource réutilisée n'était pas un objet de scène : elle a servi, mais il n'y avait rien à dessiner. Voir *Limites connues* |

### Ce qui n'est jamais écrit

Aucun audio brut n'est conservé, nulle part. La parole de la salle vit dans
l'ensemble de travail **en mémoire**, bornée, et disparaît au retrait de la
séance. Elle n'entre dans aucune ligne de trace : les lignes portent des
identifiants, des comptes et des codes — y compris celles du sous-agent de
préparation, dont l'entrée n'est **pas** recopiée par le CLI comme elle l'est
pour les profils ordinaires.

PRESENTATION écrit sur le disque à **deux** endroits, et les deux se disent :

1. `runtime/presentation-staged-objects.json` — des identifiants d'objets de
   scène et rien d'autre, qui n'existe que pour pouvoir les supprimer ;
2. **la scène elle-même** (`data/state/scene.sqlite3`), quand une préparation
   demandée par un tour explicite monte un visuel masqué. Le `title` et le
   `summary` de cet objet viennent du sous-agent, donc d'un modèle qui a lu de
   la parole de la salle : ce ne sont pas des identifiants. Ils sont bornés,
   ils sont masqués jusqu'à ce qu'on les demande, et ils sont **repris** — à la
   fin de la séance par `retire()`, après un arrêt brutal par le registre
   ci-dessus, au démarrage suivant de Voice. C'est ce qui rend D13 vraie ici :
   pas l'absence d'écriture, mais la reprise de ce qui a été écrit.

### Bassin de préparation

Deux clés facultatives de `runtime/control-center-settings.json`, sans variable
d'environnement ni champ dans le Control Center. Elles sont lues au démarrage
de Voice.

| Clé | Sens | Défaut |
| --- | --- | --- |
| `presentation_speculative_pool` | nombre **total** de sous-agents de préparation simultanés, réserve comprise, de 1 à 8 | 3 |
| `presentation_reserved_explicit_slots` | places de ce total que seul un tour explicite peut prendre ; doit rester inférieur au bassin | 1 |

Le défaut donne donc 2 sous-agents spéculatifs et 1 place explicite. Chaque
sous-agent est un processus Claude CLI. Avant d'élargir le bassin, comptez sa
mémoire résidente sur le poste.

Une valeur illisible, un bassin hors de 1 à 8, une réserve négative, ou une
réserve qui ne laisse aucune place au spéculatif font retomber **les deux**
clés sur leurs défauts. La trace le dit en une ligne :
`presentation.speculative.pool_setting_invalid` (code
`presentation_speculative_pool_invalid`, avec les clés écartées). Corrigez la
valeur, puis redémarrez Voice.

### Blocages nommés

- **Pile vocale Gemini Live** : pas de transcription ambiante. La clé
  disponible dans le processus Voice est celle du fournisseur de la pile, et
  Gemini n'offre pas de transcription de WAV par ce chemin. PRESENTATION
  démarre, prend le micro, répond à l'adresse explicite — et la voie ambiante
  reste sourde, ce que `ambient_deaf` dit dans le relevé. La ligne
  `presentation.runtime.blocked` (code `presentation_transcription_unavailable`) le dit
  **à la première entrée en PRESENTATION**, une seule fois — pas au démarrage, pour
  qu'un opérateur qui reste en SIMPLE n'ait pas à le lire à chaque lancement.
- **CLI d'agent Codex** : pas de préparation spéculative. `--tools` et le mode
  restreint sont des arguments du CLI Claude ; `back_brain_worker` refuse déjà
  le spéculatif pour la même raison.
- **`memory_search` et les outils de scène** ne sont pas atteignables par un
  sous-agent de préparation : le profil restreint refuse tout serveur MCP.
  Une préparation lit le web et les fichiers, pas la mémoire canonique.

### Revenir en arrière

Choisir `SIMPLE` dans le Control Center suffit, et prend effet immédiatement :
la séance est retirée, le micro est rendu à la pile d'éveil de SIMPLE, et la
mémoire de séance est vidée. Aucun redémarrage n'est nécessaire, et il n'y a
rien à nettoyer à la main.

### Validation de bout en bout (Slice 11)

Ce que les machines ont prouvé, et ce qu'elles n'ont pas prouvé.

- **Matrice déterministe** : `tests/integration/test_presentation_scenarios.py`
  (scénarios 1 à 12 de `docs/04-testing-and-quality.md`, identité SIMPLE,
  balayage d'une phrase plantée dans tous les puits durables, latence sous
  charge). À lancer seule, en avant-plan : `pytest tests/integration/test_presentation_scenarios.py`.
- **Vie privée** : `voice.transcript_dropped` ne porte que `reason`, `code` et
  `chars`, dans tous les modes (`tests/unit/test_dropped_transcript_privacy.py`).
  Un segment écarté ne laisse jamais ses mots à `trace.jsonl`, qui n'a pas de rotation.
- **Latence du tour explicite** : sur doubles, médiane de 5 répétitions de
  12 tours, avec fournisseur lent et deux préparations en cours. Le test
  garantit un p50 chargé au plus `max(10 %, 5 ms)` au-dessus du p50 au repos
  et un p95 chargé sous 20 ms (plafond absolu). Mesure sur ce PC (10 exécutions) :
  p50 4,5 à 6,2 ms au repos, 4,7 à 7,3 ms en charge ; p95 5,5 à 9,4 ms au repos,
  6,0 à 10,2 ms en charge. **La mesure sur l'hôte réel (Core et Control Center
  vivants, vrai micro) n'est pas faite** : c'est un point humain de
  `HV-PRESENTATION-E2E-01`, sous-contrôle PRIORITY. Relever alors
  `addressed_admission_latency` (`elapsed_ms`) dans `runtime/trace.jsonl`, avec
  et sans parole ambiante.
- **Limites connues** : `docs/presentation-mode.md`, section « Known limitations ».

## Tool Brain: roll-out, checks and roll-back

The Tool Brain (a dedicated decider of UI-tool calls and their timing, contract
[tool-brain-contracts.md](tool-brain-contracts.md) section 18) ships **off**. One setting
governs everything, `JARVIS_TOOL_BRAIN` (read when Core starts; see the table in *Configuration*).
Moving up is a decision of the Human after acceptance, never an automatic step.

| Step | Setting | What happens | Move on when |
|---|---|---|---|
| 0 (default) | unset or `off` | nothing is built; Jarvis calls the UI tools itself | |
| 1 | `JARVIS_TOOL_BRAIN=shadow` | it decides and records, executes nothing, Jarvis keeps the screen; a violet **Tool Brain** lane appears on the conversation timeline (dock **CNV**) once it acted | a few days of real use: every decision is readable on the timeline, failures are rare, nothing it "would apply" is surprising |
| 2 | `JARVIS_TOOL_BRAIN=active` | queue + executor; after one completed, healthy decision it owns the screen, Jarvis's screen-action tools answer `ui_delegated`, irreversible actions go through the guardrails | the perceived synchronization with the voice is accepted (see the Human checks of the S10 handoff) |

Needs: the configured CLI is Claude with a native executable (`claude.exe`), `JARVIS_TOOL_BRAIN_MODEL` (default `haiku`) usable
with your login. Each decision is one tool-less model call, about 3.4 s and under one cent (measured, contract 18.4);
without the CLI the Tool Brain is `unavailable`, backs off and Jarvis keeps the screen.

**Check it before trusting it** (no live Jarvis needed; the first two lines are free):

```bash
# deterministic replay of the eight documented traces + outage cases; exit code 1 on any failure
.venv/Scripts/python.exe -m tests.replay.tool_brain_replay
# isolated Core on a temp root and an ephemeral port (never 17653/17654): shadow, active, decider killed, timeline lane
.venv/Scripts/python.exe scripts/tool_brain_live_session.py --out <empty dir>
# the same scenarios against the real model (paid: about 10 calls, under 10 cents)
.venv/Scripts/python.exe -m tests.replay.tool_brain_replay --live --max-calls 12 --out <empty dir>
# the isolated Core with the real model deciding (paid: about 2 calls)
.venv/Scripts/python.exe scripts/tool_brain_live_session.py --decider model --scenario active --out <empty dir>
```

**Roll back**: set `JARVIS_TOOL_BRAIN=shadow` (or remove it, or `off`) and restart Core. Ownership goes back to Jarvis at once
(the arbiter publishes `jarvis_direct` when Core stops; a missing or stale `runtime/tool-brain-ownership.json` means Jarvis, at
most 20 s after a crash). The action queue is in memory: nothing to clean. If the Tool Brain misbehaves **while running**, you
do not need to act: two failed decisions in a row, an unavailable decider or an unwritable ownership file already hand the
screen back (reason `decider_failing`, `decider_unavailable`, `publish_failed`), visible as a warning dot on the Tool Brain lane,
and it waits 60 s before taking it again.

**When something looks wrong**: the lane shows the wake, the decision (outcome, number of actions), one bar per action
(queued to executed, cancelled, invalidated or failed, with the code) and every ownership change; click an entry for the ids.
Arguments, URLs and reasoning are never written to the log. Journal lines `tool_brain.*` in `runtime/trace.jsonl` carry the codes.

## Manual workstation acceptance

Solo Owner and the Core work state have their own runnable protocol,
[`docs/HARDWARE_ACCEPTANCE.md`](HARDWARE_ACCEPTANCE.md) (owner enrollment, shadow
measurement, the ten scenarios with their trace events and pass/fail criteria,
benchmark on real recordings, server vs semantic VAD, work-state parity, long
session, how to choose the final defaults, rollback). It is **not executed**: it
needs the owner's voice and real colleagues.

For the rest, follow `docs/ACCEPTANCE_STATUS.md`. It is intentionally explicit about checks that cannot be proven in a headless build sandbox: real microphone/speaker, real OpenAI latency, Chrome camera permissions and physical Barehands gestures.

The `continuous_brain` voice architecture adds its own workstation gate, listed in the same document and **not executed**: headphones, normal speakers, keyboard noise, background speech, interruption while Jarvis speaks, a long brain job while the user keeps talking, `Jarvis Mute` during a job, and waking again once the job has completed. Record whether speaker-to-mic echo retriggers the VAD; if it does, keep `legacy` rather than masking the result.

## Context enrichment cost (Slice 08, session-context-recording)

The enrichment worker ([session-context.md](session-context.md#enrichment-worker-slice-08))
calls the Claude CLI in the restricted, tool-less `speculative_analysis`
profile, one fresh process per call, model `JARVIS_CONTEXT_ENRICHMENT_MODEL`
(default `haiku`). The cost is the provider's own `total_cost_usd`, logged on
every round (`core.context_enrichment.round`: `cost_usd`, `usage_*`,
`total_cost_usd` since Core start) and on every screenshot description
(`core.context_enrichment.screenshot_described`); `ContextEnrichmentWorker.status()`
carries the running total.

The enrichment CLI runs with `MAX_THINKING_TOKENS=0` (PM decision). Measured
on 2026-10-01 after the QA rework, `haiku` through Claude Code, 1.2 K input
tokens: summary round **0.0017–0.0019 $**, 1.5–1.8 s API time (2.7–4.7 s
wall, process start included), **0 thinking tokens**; screenshot description
0.0013 $. The same round with the CLI's default thinking: 3 691 thinking
tokens, 0.020 $, 32 s — ten times the cost. `usage_thinking_tokens` on every
round trace shows it stays at 0.

Prompt cache (QA rework, measured 2026-10-01, CLI 2.1.286, `haiku`): a round
near the prompt bound (10.9 KB, ≈ 4 200 input tokens) is above the model's
cache minimum, so the CLI writes a prompt cache; each round is a fresh
process with a different prompt, so that cache is never read. On a Claude
subscription the CLI picks a **one-hour** cache, billed at 2× the input
price: **0.0093 $** per full round (4 207 cache-write tokens, 172 output).
The enrichment CLI therefore runs with `CLAUDE_CODE_PROMPT_CACHE_TTL=5m`
(billed 1.25×): **0.0064 $** per full round (4 202 cache-write tokens, 225
output), −31 %. Claude Code has no switch that removes the write in `-p`
mode: `DISABLE_PROMPT_CACHING=1` still wrote 4 200 cache tokens. Small rounds
(≈ 1.2 K tokens, below the cache minimum) write no cache and stay at
0.0017–0.0019 $. `usage_cache_creation_input_tokens` and
`usage_cache_read_input_tokens` are on every round trace.

Upper bound by cadence: at most one round every 90 s while evidence keeps
arriving (45 s of quiet, 120 s max wait), i.e. ≤ 40 rounds/hour, plus at most
two screenshot descriptions per round. Expected cost: **≈ 0.09–0.20 $ per
hour of continuously transcribed meeting** (0.003–0.005 $ per round measured
in Slice 11, 30–40 rounds/h while speech keeps arriving), **≈ 0.38 $/h worst
case** (40 rounds × a full 4 200-token prompt at 0.0064 $ = 0.26 $, plus 80
screenshot descriptions × 0.0015 $ = 0.12 $, measured on a small test image —
full-screen images cost more; ≈ 0.49 $/h with the one-hour cache); nothing
when no evidence arrives (the worker only polls the ledger). A batch that is paid but cannot be written is
not paid again: its output is kept and only the write is retried for 15 min,
then the worker is `stuck` (at most one paid retry per hour). Turn it off
with `JARVIS_CONTEXT_ENRICHMENT=0`.

