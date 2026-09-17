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
Apparence (couche de thèmes) et Expérimental (Barehands en mode test).

Un principe la traverse : **la page ne connaît aucun réglage**. Le serveur
décrit ce qui existe — les piles vocales, leurs champs, les CLI, leurs modes,
les raccourcis — et la page se contente de l'afficher. Ajouter une option se
fait donc dans `jarvis/runtime/voice_stack.py` ou `cli_catalog.py`, pas dans le
HTML. Corollaire : un champ visible est un champ réellement transmis au
fournisseur, et il n'apparaît que lorsqu'il s'applique — les réglages de silence
disparaissent en fin de tour manuelle, les options Gemini n'existent pas sous
OpenAI.

### Mode vocal

En tête de l'onglet, **Architecture** choisit le déroulé d'une conversation :
« Un tour par appui » (`legacy`) ou « Conversation continue (jusqu'à F9) »
(`continuous_brain`). Le choix est rangé dans `voice_arch` de
`runtime/control-center-settings.json` et passe devant `JARVIS_VOICE_ARCH` ;
laissé sur « Par défaut », Voice suit la variable, puis le défaut calculé (voir
« Deux architectures vocales »). Une combinaison que Voice refuserait —
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
`barehands_test_mode.enabled` dans `runtime/control-center-settings.json` ; il
reste actif au prochain chargement de la page. Route dédiée, comme les
raccourcis : `GET /api/barehands` (état + présence des assets) et
`POST /api/barehands` (`{"enabled": true|false}`, refus HTTP 400 avec code
stable `barehands_*`, rien d'écrit). Événements : `settings.barehands`,
`settings.barehands.rejected`.

Activé, la page ouvre la webcam et suit les mains **dans le navigateur**
(MediaPipe Hand Landmarker, WASM + modèle `hand_landmarker.task`), sans service
cloud ni serveur Barehands. Chaque main détectée affiche un jeton rond qui suit
le bout de l'index (image vue en miroir, 12 % de bord ignoré pour atteindre les
coins). Retour visuel : le jeton grossit et l'élément visé est cerné au survol ;
l'anneau se remplit pendant le rapprochement pouce-index et le jeton se fige
pour viser ; au pincement franc, une onde marque le clic. Le clic rejoue la
séquence souris (`pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`)
sur l'élément sous le jeton : boutons du dock, onglets, cases, cartes Agents,
fermeture de fenêtre. Seuils (`JarvisBarehandsCore.DEFAULTS`) : pincé sous 0,28
de la taille de paume, relâché au-dessus de 0,42 (hystérésis), deux images de
confirmation, 450 ms d'anti-rebond, un seul clic par pincement. Le jeton suit
la couleur d'accent du thème (`--omega-accent` sous Omega, `--accent` sinon).

Arrêt : interrupteur coupé, caméra refusée, absente, occupée ou débranchée,
modèle absent, erreur du suivi, fermeture de la page. Dans tous les cas, un seul
chemin (`teardown`) arrête les pistes caméra, ferme le modèle, retire la vidéo,
les jetons et le survol ; un toast et l'onglet disent pourquoi. Un démarrage
encore en vol quand on éteint rend la caméra dès qu'elle arrive.

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

#### Procédure de test manuel (caméra réelle)

1. Assets présents : `python scripts/bootstrap_third_party.py --verify` rend 0.
2. Lancer le Control Center (`python -m jarvis control-center`), ouvrir
   `http://127.0.0.1:17654/` dans Chrome. Depuis un worktree, en parallèle d'un
   JARVIS déjà lancé : `JARVIS_UI_PORT=17655`, `JARVIS_VISUALIZER_ENABLED=0`,
   `JARVIS_BAREHANDS_VENDOR_DIR=<dépôt principal>\third_party\barehands\vendor`.
3. SET → Expérimental → cocher l'interrupteur. Attendu : invite caméra, puis
   toast « Barehands actif » et pastille `MAINS · TEST` en bas à gauche.
4. Montrer une main : un jeton suit l'index ; deux mains, deux jetons.
   Survoler un bouton du dock : jeton agrandi, bouton cerné.
5. Rapprocher lentement pouce et index : anneau qui se remplit, jeton figé.
   Pincer franchement sur le bouton Trace : le panneau s'ouvre (onde de clic).
   Rester pincé : aucun second clic. Rouvrir puis repincer : nouveau clic.
6. Ouvrir SET, changer d'onglet et cocher une case au pincement.
7. Couper l'interrupteur au pincement : jetons retirés, voyant caméra éteint,
   toast « Barehands arrêté ». Recharger la page : toujours éteint.
8. Réactiver, recharger : le mode test repart seul. Refuser la caméra dans
   Chrome (icône de l'adresse) puis recharger : toast « Caméra refusée »,
   aucune surimpression, message dans l'onglet.
9. Débrancher la webcam pendant le suivi : « Caméra coupée », tout est retiré.

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
| `JARVIS_ACTIVE_TIMEOUT_S` | useful-inactivity timeout of an ACTIVE voice session; default 90. `0` = jamais : seule la touche de réveil (F9) ou « Jarvis mute » met fin à la conversation. Toute autre valeur doit être >= 5. Le champ « Délai d'inactivité » des réglages du Control Center passe devant |
| `JARVIS_AGENT_CLI` | `claude` (default) or `codex` |
| `JARVIS_CLAUDE_MODEL` | model passed to `claude --model`; empty means the CLI default |
| `ANTHROPIC_API_KEY` | lists the real Claude models; the CLI itself can run on a subscription |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Gemini Live voice and its model list |
| `JARVIS_MEMORY_DIR` | canonical Markdown root |
| `JARVIS_RUNTIME_DIR` | transient signal/log directory |
| `JARVIS_CONFIRMATION_TIMEOUT_S` | pending write confirmation expiry |
| `JARVIS_LOG_LEVEL` | diagnostic level |
| `JARVIS_LOG_CONTENT` | opt-in raw content logging; default false |
| `JARVIS_AUDIO_SAMPLE_RATE` | microphone capture sample rate |
| `JARVIS_AUDIO_INPUT_DEVICE` | explicit input device name (exact/substring match; missing configured device fails clearly) |
| `JARVIS_AUDIO_OUTPUT_DEVICE` | explicit output device name or PortAudio index for Realtime Voice |
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
| `JARVIS_UI_PORT` | port du Control Center joint par Voice (défaut 17654) |
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
  `interrupted` ; seul l'utilisateur l'archive ;
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
| après un redémarrage de Core, une étoile affiche « état inconnu depuis le redémarrage » | normal pendant la grâce (60 s) : l'état de travail de Core est reparti vide, le Control Center n'a pas encore redit ses sous-agents | attendre ; si le Control Center tourne, l'état revient en ~30 s au plus. Sinon l'étoile passe « interrompu » avec un signal à la fin de la grâce |
| une étoile passe « interrompu » avec le signal « non revu après le redémarrage de Core » alors que le sous-agent tournait | le Control Center n'a rien renvoyé pendant la grâce (arrêté, ou Core injoignable pour lui : `work.ingress_unavailable` dans sa trace) | vérifier le Control Center ; dès qu'il redit ce travail, l'étoile reprend son état et le signal est retiré |
| après un arrêt brutal du **Control Center**, des étoiles restent « en cours » | le Control Center n'a pas été relancé (Core n'a aucun délai d'expiration pour lui), ou la nouvelle instance ne joint pas Core (`work.ingress_unavailable` dans sa trace) | relancer le Control Center : sa première connexion à Core interrompt les anciens sous-agents en une seconde environ |

### Scène constellation : redémarrages et « état inconnu »

La scène est enregistrée sur disque ; l'état des travaux de Core ne l'est pas.
Voici ce qui se passe à chaque redémarrage (détail : `docs/ARCHITECTURE.md`,
« Restart reconciliation »).

| Ce qui redémarre | Ce que montre la scène |
| --- | --- |
| **le navigateur** (rechargement de la page) | la même scène, relue d'un coup, puis les changements au fil de l'eau |
| **Core**, le Control Center restant allumé | les étoiles encore en cours passent un instant à « état inconnu depuis le redémarrage » (anneau pointillé pâle, point atténué, badge « ? ») ; le Control Center redit l'état de ses sous-agents en 30 s au plus, et chaque étoile reprend son vrai état, sans signal |
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

Core sert la scène par trois routes (jeton de `runtime\core.token`, comme
`/v1/work/snapshot`) ; le navigateur passe toujours par le Control Center, qui
n'a pas besoin du jeton côté page (`docs/ARCHITECTURE.md`, « Scene transport ») :

| Control Center | Core | Rôle |
| --- | --- | --- |
| `GET /api/scene` | `GET /v1/scene/snapshot` | instantané complet : `scene_id`, `epoch`, `revision`, `snapshot` |
| `GET /api/scene/patches?scene_id=…&epoch=…&after=N&wait_s=25` | `GET /v1/scene/patches` | attente longue des patchs après la révision `N` (25 s au plus côté Control Center, 30 s côté Core) |
| `POST /api/scene/commands` | `POST /v1/scene/commands` | une commande de scène ; côté Control Center l'acteur est toujours `user` |

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
`data/state/scene.sqlite3` (sous `JARVIS_DATA_ROOT`), à côté de
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
mode WAL), sans rien changer au contenu. Aucune copie de la scène n'est faite. Seul un fichier **absent** fait créer une nouvelle scène ;
un fichier vide (0 octet) ou sans table est refusé. Que faire selon
`data.code` :

| Code | Cause | Action |
| --- | --- | --- |
| `schema_newer` | fichier écrit par une version plus récente de JARVIS | revenir à cette version (ou attendre sa mise à jour) ; ne pas supprimer le fichier |
| `schema_unknown` | version illisible, ou fichier qui n'est pas une base de scène | vérifier qu'aucun autre fichier n'a été copié à cet emplacement |
| `corrupted` | fichier vide ou tronqué, illisible par SQLite, contenu invalide, ou `scene.sqlite3-wal` présent sans `scene.sqlite3` | Core arrêté, déplacer le fichier **et** `scene.sqlite3-wal` / `-shm` s'ils existent hors de `data/state/`, les garder pour analyse, redémarrer Core : une scène vide est recréée |
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

Le cerveau conversationnel (Claude CLI) peut lire et composer la scène par dix
outils MCP du serveur `jarvis-display` : trois lectures, `scene_inspect` (toute la
scène en lignes compactes), `scene_query` (trouver des objets par filtres) et
`scene_get` (lire le détail d'un objet), la capture exceptionnelle
`scene_capture`, puis `scene_create_object`,
`scene_update_object`, `scene_set_visibility`, `scene_link`, `scene_unlink` et
`scene_add_artifact` (artefacts, voir « Scène constellation : les artefacts »).

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
l'écran » : le cerveau peut appeler `scene_capture`. Ce n'est pas une copie
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
« Réaffiche tout » passe par `scene_set_visibility` avec `scope: "all_hidden"` :
le serveur réaffiche un par un tout ce qui est masqué au moment de l'appel et
rend les comptes, en 15 s au plus (au-delà : `deadline_reached`, et le reste à
rappeler) ; il n'existe pas de « tout masquer ». Quand la scène a bougé
depuis la dernière lecture du cerveau, les résultats de commande listent ce qui
a changé (apparu, archivé, masqué ou réaffiché, état), dix lignes au plus.
Il agit toujours comme acteur `brain`. **Aucun outil n'archive ni n'épingle** :
l'archivage reste à l'utilisateur (et Core le refuse au cerveau de toute façon).
Détail technique : `docs/ARCHITECTURE.md`, « Brain display MCP ».

**Activer.** Interrupteur `scene.enabled`, éteint par défaut, dans
`runtime/control-center-settings.json` (pas encore d'écran de réglage, il
arrive au Slice 11) :

```json
{ "scene": { "enabled": true } }
```

ou par l'API du Control Center, `POST /api/settings` avec
`{"scene": {"enabled": true}}` (lecture : `GET /api/settings`, bloc `scene`,
`source` = `settings` ou `env`). `JARVIS_SCENE_ENABLED=1` (ou `0`) dans
l'environnement du Control Center l'emporte sur le fichier. **Effet au prochain
démarrage du cerveau** (bouton Redémarrer de l'agent, ou redémarrage de JARVIS) :
le CLI lit ses serveurs MCP et sa consigne système à son lancement. Une
conversation reprise (`--resume`) voit les outils tout de suite mais garde la
consigne système enregistrée à son premier tour ; un redémarrage complet de
JARVIS ouvre une conversation neuve qui a la consigne. Éteint, le cerveau est
lancé exactement comme avant.

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
| `agent.start` dit `display_mcp: false` alors que l'interrupteur est vrai | cerveau pas redémarré, ou `JARVIS_SCENE_ENABLED=0` | redémarrer l'agent ; lire `GET /api/settings` → `scene.source` |
| `scene.display_mcp_unconfigured` (avertissement) | Control Center lancé sans coordonnées de Core (hors `python -m jarvis control-center`) | lancer par la commande normale |
| `agent.display_mcp_failed` (erreur, panneau ERR) | `runtime/display-mcp.json` non inscriptible | corriger les droits du dossier runtime, redémarrer l'agent ; la voix marche sans l'écran en attendant |
| `mcp_servers` montre `jarvis-display` en `failed` | interpréteur introuvable, paquet `mcp` absent (`pip install -e .[mcp]`), variable d'environnement invalide | lancer à la main la commande de `runtime/display-mcp.json` avec son `env` : l'erreur s'affiche |
| erreur d'outil `core_unreachable` / `command_not_sent` | Core arrêté ou jeton absent | démarrer Core ; rien n'a été appliqué |
| erreur d'outil `core_refused` avec `401` | Core redémarré, jeton relu mais toujours refusé | vérifier `JARVIS_CORE_TOKEN_FILE` du Control Center et de Core |
| erreur d'outil avec `reason=runtime_owned` | le cerveau a voulu retirer un lien de parenté entre étoiles ou le lien d'un signal de tâche | normal : ces liens sont au runtime ; masquer le signal, ou l'archiver depuis le Control Center |
| erreur d'outil `Arguments inconnus refusés` | le modèle a inventé un argument (`archived`, `pinned_by_user`…) | normal : rien n'est parti ; `display.tool_failed` code `unknown_argument` nomme les champs |
| le cerveau décrit un écran qui n'est plus à jour | il n'a pas relu la scène dans le tour | chercher `mcp__jarvis-display__scene_inspect` dans le tour de la trace ; les résultats de commande portent `scene_changed` quand la scène a bougé |
| erreur d'outil `scene_unavailable` | scène refusée par Core | voir « Scène constellation : fichier et refus » |
| erreur d'outil avec `reason=pinned_by_user` | objet épinglé par l'utilisateur | normal : le cerveau ne le déplace pas |
| erreur d'outil avec `reason=scene_full` | 512 objets actifs | archiver des objets terminés ; le cerveau ne peut pas |
| `display.tool_failed` niveau erreur `display_internal_error` | défaut du serveur | remonter le message (type et texte) |
| erreur d'outil `scene_query (near) … reason=unplaced` | l'objet de référence n'a pas encore de géométrie enregistrée (placement automatique pas encore fait par une page) | normal : ouvrir le Control Center le place en quelques secondes ; sinon `scene_get` |
| erreur d'outil `scene_query (explains) … reason=object_archived` | l'objet a été archivé | normal : rien à expliquer dans la scène active |
| le cerveau répond « je ne vois que le titre » d'un artefact | cerveau lancé avant le Slice 09, ou conversation reprise avec l'ancienne consigne | redémarrer l'agent ; la trace doit montrer `mcp__jarvis-display__scene_get` et `display.read` |
| erreur d'outil `attach_artifact refusé … reason=object_archived` | l'utilisateur a archivé l'étoile du travail | normal : pas d'artefact pour un travail rangé, rien n'a été envoyé |

Tous les appels laissent `display.tool` / `display.read` (lectures `scene_query`
et `scene_get` : noms des filtres ou identifiants, comptes) / `display.tool_refused` /
`display.tool_failed` dans `runtime/trace.jsonl` (identifiants et issues, jamais
le texte des notes ni un chemin de fichier). `display.server_stopped` n'apparaît
que si la session se termine proprement : un arrêt du cerveau tue d'ordinaire le
serveur sans cet événement, ce n'est pas une panne. Les actions d'affichage sont silencieuses à l'oral : le
cerveau ne décrit pas ce qu'il place.

### Scène constellation : ce que l'on voit dans le Control Center

Quand `scene.enabled` est vrai (voir « outils d'affichage du cerveau » pour
l'activer), la page du Control Center dessine la scène **par-dessus le visage**
(circuit imprimé ou Omega) et **sous toutes les commandes** : barre du haut,
dock, panneaux, pastilles, réglages, notifications, menu contextuel et
Barehands restent cliquables au-dessus. L'interrupteur est relu à chaque
sondage de `/api/status` (chaque seconde) : l'allumer ou l'éteindre agit sur la
page ouverte sans la recharger. Éteint, la page est exactement celle d'avant :
aucun calque, aucune requête de scène.

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
les étoiles à gauche du visage, un enfant près de son parent, un signal contre
son étoile, les résultats à droite. La page **enregistre ce placement une seule
fois dans Core** (commande `set_geometry`, `placed_by = resolver`, journalisée
`scene.command`) : après un rechargement, dans un autre onglet ou après un
redémarrage, la disposition est identique. Un objet placé par le cerveau ou par
vous, ou épinglé, n'est jamais déplacé par la page. Avec plusieurs onglets
ouverts, un seul à la fois (un onglet visible) enregistre les placements.

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

**Dépanner.**

| Symptôme | Cause probable | Action |
| --- | --- | --- |
| aucune scène alors que l'interrupteur est vrai | page servie avant la mise à jour, ou `JARVIS_SCENE_ENABLED=0` | recharger la page ; `GET /api/status` → bloc `scene` (`enabled`, `source`) |
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
| ouvrir les actions | clic droit, appui long, ou clic sur l'objet déjà sélectionné | touche Menu ou Maj+F10 |
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

- En capsule (forme par défaut) : sa catégorie puis son titre, près de l'étoile.
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
   transcript écarté. `legacy` reste le repli half-duplex.
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
sa liste de modèles ; rien n'est écrit en dur dans la page. **L'ordre des cases
cochées est la préférence** : le premier disponible gagne, les suivants sont des
recours.

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

Release verifier:

```bash
python scripts/verify_release.py
```

Opt-in real-provider transcription smoke:

```bash
JARVIS_LIVE_OPENAI=1 OPENAI_API_KEY=... python -m pytest -q tests/integration/test_live_openai.py
```

## Manual workstation acceptance

Solo Owner and the Core work state have their own runnable protocol,
[`docs/HARDWARE_ACCEPTANCE.md`](HARDWARE_ACCEPTANCE.md) (owner enrollment, shadow
measurement, the ten scenarios with their trace events and pass/fail criteria,
benchmark on real recordings, server vs semantic VAD, work-state parity, long
session, how to choose the final defaults, rollback). It is **not executed**: it
needs the owner's voice and real colleagues.

For the rest, follow `docs/ACCEPTANCE_STATUS.md`. It is intentionally explicit about checks that cannot be proven in a headless build sandbox: real microphone/speaker, real OpenAI latency, Chrome camera permissions and physical Barehands gestures.

The `continuous_brain` voice architecture adds its own workstation gate, listed in the same document and **not executed**: headphones, normal speakers, keyboard noise, background speech, interruption while Jarvis speaks, a long brain job while the user keeps talking, `Jarvis Mute` during a job, and waking again once the job has completed. Record whether speaker-to-mic echo retriggers the VAD; if it does, keep `legacy` rather than masking the result.
