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

## Realtime voice timbre

`OPENAI_REALTIME_VOICE` (or "Voix JARVIS" in Control Center settings) selects
the Realtime timbre. The default is `cedar`, the low and level one of the two
gpt-realtime voices; `marin` is its brighter counterpart. `ash`, `verse`,
`ballad`, `echo`, `sage`, `alloy`, `coral` and `shimmer` are also accepted. The
persona itself lives in `JARVIS_PERSONA` in `jarvis/adapters/openai_realtime.py`.

Voice reads both settings at startup only: restart the Voice runtime after a
change.

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

The Control Center **Settings** panel lists the audio devices exposed by PortAudio. Select an input and an output, then use **Tester micro + sortie**: Jarvis records two seconds in the exact Realtime Voice format (24 kHz mono), requires a detected microphone signal, and replays the captured audio through the selected output. Save the selection and restart the Voice runtime to apply it to conversations and Porcupine.

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

`JARVIS_BOARD_TOKEN` is an internal per-launch secret normally created by `dev_start.py`; do not persist it.

## Diagnostics

Runtime logs are JSONL in the runtime directory. With default privacy settings, content fields are redacted. Useful fields include state/event names, durations and exception class.

When troubleshooting provider errors, first run health, then inspect diagnostic event names/error classes. Avoid turning on content logging unless required and remove those logs afterwards.

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

Ouvrir la console de debug pendant qu'une tâche vocale tourne **l'interrompt** :
la console prend la main sur la session, l'agent piloté est arrêté. C'est
volontaire, mais le tour vocal est débloqué immédiatement avec un message
prononçable (`agent.console_interrupt`, niveau `warning`) au lieu d'attendre le
délai complet.

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
