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
centrée, fermée par un clic à l'extérieur ou par `Échap`. Elle a cinq onglets.

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

### CLI agent

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
| `JARVIS_ACTIVE_TIMEOUT_S` | useful-inactivity timeout of an ACTIVE voice session; default 90 |
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
| Retour au fond | fin de réponse, mute, délai, panne | mute, délai d'activité utile, panne irrécupérable |

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

Trois points, à ne jamais présenter comme acquis :

1. **Aucune recette matérielle n'a tourné.** Micro, haut-parleurs, casque, écho
   acoustique, redéclenchement du VAD par les haut-parleurs, barge-in réellement
   audible : rien de tout cela n'a été mesuré. Le mode continu garde le micro
   ouvert pendant que les haut-parleurs jouent, et **cet écho n'est traité par
   aucun logiciel ici** ; `legacy` reste le repli half-duplex.
2. **Aucune exécution contre le vrai OpenAI.** Le test de fumée
   `tests/integration/test_live_openai.py` couvre le chemin continu mais reste
   sauté par défaut et n'a pas été lancé.
3. **L'accès du cerveau à l'agenda et aux rappels n'est pas vérifié.** C'est le
   contenu même de la porte ci-dessus.

Sur l'interruption, soyez précis : les tests automatisés prouvent l'ordre arrêt
local → annulation → troncature, et que l'historique ne prétend pas que
l'utilisateur a entendu ce qui a été tronqué. Ils ne prouvent **pas** que le son
cesse dans les haut-parleurs, ni en combien de millisecondes.

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

Follow `docs/ACCEPTANCE_STATUS.md`. It is intentionally explicit about checks that cannot be proven in a headless build sandbox: real microphone/speaker, real OpenAI latency, Chrome camera permissions and physical Barehands gestures.

The `continuous_brain` voice architecture adds its own workstation gate, listed in the same document and **not executed**: headphones, normal speakers, keyboard noise, background speech, interruption while Jarvis speaks, a long brain job while the user keeps talking, `Jarvis Mute` during a job, and waking again once the job has completed. Record whether speaker-to-mic echo retriggers the VAD; if it does, keep `legacy` rather than masking the result.
