# Voice lifecycle: Off / Sleep / Active (product contract)

**Status:** contract, level 3 (implementation `jarvis/runtime/voice_lifecycle.py` + conformance tests).
**Introduced:** task `jarvis-presentation-edition-v1-2`, Slice 05.
**Builds on:** [chat.md](chat.md) › *Voice channel* (chat lock), [product-install.md](product-install.md) › *Launcher*,
[settings/voice-audio.md](settings/voice-audio.md) (wake word section), [OPERATIONS.md](OPERATIONS.md) (wake word
install and trace codes).

The **application** lifecycle and the **voice** lifecycle are two things. Opening JARVIS (the launcher, or
`core` + `control-center` in development) means JARVIS runs: Core, the Control Center and the Chat are available.
The voice is a separate, optional surface with three product states. They are a **projection** of internal states
that already exist; no second state machine is added.

| Product state | What is true | Internal facts it is projected from |
| --- | --- | --- |
| **Off** | the user chose « voix coupée »; the Voice process is not started (or has stopped); no microphone and no wake listener are open | `voice_lifecycle.preference == "off"` in `control-center-settings.json`; no Voice heartbeat |
| **Sleep** (default) | Voice runs in `background`, waiting for a wake: the manual key (F9 by default) always; the spoken wake word only when the `wake_word` block enables it **and** its engine is present on this machine | Voice heartbeat fresh, `.voice_runtime.runtime_state == "background"` |
| **Active** | a voice session is open (`connecting` or `active`), the Chat is locked (`chat_input_locked`, unchanged) | `.voice_runtime.runtime_state in {connecting, active}` |

When an active interaction ends, Voice returns to `background` by its existing rules (idle timeout, key, « Passer au
chat »): that is Sleep again. With GPT-Live (Duplex) that product state **Sleep** has two levels, IDLE then SLEEP,
described in the next section. Transitions and degraded reasons are said, never guessed:

| `state` | `code` | Meaning |
| --- | --- | --- |
| `starting` | `voice_starting` | Sleep wanted, the launcher started Voice, no heartbeat yet |
| `stopping` | `voice_stopping` | Off wanted, Voice still beats (it releases within a second) |
| `degraded` | `voice_provider_key_missing` | no key for the provider of the chosen voice stack: Voice is **not started** (no crash loop) |
| `degraded` | `voice_configuration_invalid` | the voice architecture/stack cannot be resolved (same check as Voice) |
| `degraded` | `voice_crash_loop` | Voice died `MAX_RESTARTS` times and was abandoned; switching Off then on again retries |
| `degraded` | `voice_runtime_error` | Voice reports `error` |
| `degraded` | `voice_not_launched` | the launcher runs without Voice (`JARVIS_LAUNCH_VOICE=0`) |
| `degraded` | `voice_preference_unreadable` | the stored block is present but unreadable: Voice is held (no microphone) until the user switches |
| `not_running` | `voice_not_running` | no launcher (development, `full` edition) and no Voice heartbeat: the voice is on, but Voice must be relaunched by hand (a fact, not a failure) |
| `off` | `voice_off` | user choice |

## Active, IDLE and SLEEP with GPT-Live (user request 2026-10-29)

Off / Sleep / Active above is the **product** contract (what the user can switch and what the Control Center says).
With GPT-Live (`voice_architecture` Duplex) the product state **Sleep** (`runtime_state == "background"`, no provider
session) is refined into two **rest levels** held by the Voice process
([`jarvis/domain/voice_rest.py`](../jarvis/domain/voice_rest.py)); `VoiceLifecycleState` is unchanged, so Core, the
Chat lock and the lifecycle projection above read exactly what they read before. The level is published as
`.voice_runtime.rest_level` (`idle` / `sleep`, `null` outside `background`) and in `.voice_state`.

| Level | Provider session | Local microphone | What reopens a session | Orb (`.voice_state`) |
| --- | --- | --- | --- | --- |
| **ACTIVE** | open (billed) | the session's | — | `waiting` / `listening` / `thinking` / `speaking` |
| **IDLE** | **closed** | open: wake word, key and **speech detector** | « Hey Jarvis » / F9 (always first), **the user speaking** (VAD, owner voice if Solo Owner), the end of a whole task | `idle` (the usual rest look; nothing is shown as listening without an address) |
| **SLEEP** | closed | open: wake word and key only | « Hey Jarvis » / F9, the end of a whole task. **Not** speech | `sleep` (gray) |

Transitions (delays are settings, see below; defaults 10 s and 30 s):

1. **ACTIVE → IDLE** after `idle_timeout_s` (10 s) without the user speaking nor JARVIS speaking
   (`PersistentVoiceRuntime.check_timeout`, ticked every second). The session is closed (`mute(IDLE)`), so the provider
   stops billing. What used to hold a session open is now bounded: the delay restarts while the user speaks or an
   output plays, but a « safe point » that never comes (sensor unknown, immediate continuation pending) holds it at
   most `IDLE_SAFE_POINT_MAX_S` (15 s), and the brain working no longer holds it at all (the end of the task wakes
   the voice, below).
2. **IDLE → ACTIVE by speech.** While IDLE the wake listener's own microphone stream also feeds a local detector
   ([`jarvis/audio/idle_speech.py`](../jarvis/audio/idle_speech.py)): an adaptive-floor energy gate, at least 4 voiced
   frames out of 8 (80 ms each). With Solo Owner configured, only the owner's voice (the local speaker verifier)
   confirms; without a verifier Solo Owner disables this path (`idle_speech_needs_owner_verifier`) instead of falling
   back to the open room. On confirmation the run loop waits `SPEECH_WAKE_GRACE_S` (1 s): if « Hey Jarvis » (or F9)
   arrives in that time it is handled as a wake, with its greeting — **the wake word always takes precedence**.
   Otherwise `activate(trigger="speech")` reopens the session and hands it the **buffered speech** (1.2 s of lead-in
   plus everything heard while the session connected, at most 6 s, resampled to the session rate and queued ahead of
   the live microphone, `SoundDeviceRealtimeAudio.prime_input`) so the first words are not lost. No greeting, and it
   does not push SLEEP back: the usual addressing decides whether the speech was for JARVIS (otherwise 10 s later the
   session closes again).
3. **IDLE → SLEEP** after `sleep_timeout_s` (30 s) of **total** inactivity — measured from the last real engagement
   (a wake, an addressed turn, JARVIS speaking), so 20 s after entering IDLE with the defaults. The orb turns gray
   and the speech detector is disarmed: from now on only « Hey Jarvis », F9 or the end of a whole task reopens.
   A session closed by an explicit user mute (key, « Passer au chat »), by an error or by a Board switch rests
   directly in SLEEP.
4. **IDLE / SLEEP → ACTIVE by the end of a whole task.** While the voice rests, `CompletionWatcher`
   ([`jarvis/runtime/completion_watch.py`](../jarvis/runtime/completion_watch.py)) keeps the Core event stream open
   and retains one thing: a durable brain `result` / `error` speech request (`is_task_completion_speech`). Voice then
   opens a session (`activate(trigger="completion")`, no greeting, SLEEP clock restarts) and
   `SpeechScheduler.announce_missed_result` says it with the same speech id, bound to the new session's current
   intent. Then the normal timers apply. Exception kept from Decision 33: what the user muted by hand is not caught
   up by a surprise wake (the watcher stays quiet after an explicit mute until the next wake).

### Notifications: whole tasks only

Voice and Control Center report **only the end of a whole task**, never a sub-task nor an intermediate step, and
never the start of a task.

- Voice: `claude_local._push_notice` publishes the relay of a finished background task only when no other work is
  running (`AgentTaskTracker.whole_task_finished`: no running non-shell, non-ephemeral task). A sub-task finishing
  while the work continues is journaled `agent.unsolicited_result` with `held_subtask: true` and says nothing.
  Acknowledgements and progress are transient speech kinds and never wake the voice.
- Control Center: `agent.subagent.finished` carries `whole_task`; `background_events._classify` signals a successful
  completion (badge, toast) only when it is true (an older trace without the field counts as whole). A failure is
  always signalled: a task never dies in silence.

### Settings

`voice_architecture.config` (Duplex): `idle_timeout_s` (default 10, 5 to 3600) and `sleep_timeout_s` (default 30,
strictly greater than `idle_timeout_s`, at most 86400); Settings › Voice & audio › Conversation. Migration on read, no
schema bump (`voice_architecture_config.migrate_rest_timeouts`): a stored block with no `sleep_timeout_s` and
`idle_timeout_s` absent or equal to the old default (60 s, which closed the session) reads as 10 / 30; any other
`idle_timeout_s` is kept as the user's choice with SLEEP 20 s after it (30 s at least). The stored block is rewritten
only by the next save of the settings. The other architectures keep the single rest.
`JARVIS_IDLE_SPEECH=0` disables the speech-reopen path (wake word, key and end of task remain).

Limits: the speech detector lives in the openWakeWord own-stream detector (`OwnStreamWakeWordBackend`); with Porcupine or
no spoken wake word IDLE has no speech reopen (it still gives the orb its IDLE look for 20 s, then SLEEP).

## The one persisted preference

Block `voice_lifecycle` at the root of `runtime/control-center-settings.json` (no SQLite table, no migration):

```json
{"schema_version": 1, "preference": "sleep"}
```

- `sleep` is the default: a fresh profile (block **absent**) starts wake-ready.
- A block **present but unreadable** (not an object, another schema version, a value such as `"Off"`) reads as
  preference `unreadable` with a `problem` code (`voice_lifecycle_block_malformed`,
  `voice_lifecycle_stored_version_unreadable`, `voice_lifecycle_preference_invalid`). Every reader treats it like Off
  for the microphone: the launcher holds Voice (`voice_preference_unreadable`), Voice refuses to start or releases,
  the projection is `degraded` with a readable message, journaled once (`voice.lifecycle.state`, level warning, with
  `problem`). The switch rewrites a valid choice (QA rework m1).
- `off` survives every restart: nothing rewrites it but the user.
- Strict write (`apply_preference`): exactly `{"preference": "off" | "sleep"}`; refusals `voice_lifecycle_bad_payload`,
  `voice_lifecycle_preference_invalid` (header `X-Jarvis-Error-Code`). An unreadable stored block is **replaced**: it
  holds one choice only, and rewriting it is the way out.

## Who applies it

- **Launcher** (`product_launcher.py`): before starting Voice, `launch_decision` (preference, then the provider key
  through the same path Voice uses: `resolve_voice_composition` → stack → `credentials.secret_for`, `.env` included).
  Not wanted → Voice is *held* with its code, published in `launcher.json` (`roles.voice.held`), journaled
  `launcher.voice_held`. During the watch it re-reads the preference every `VOICE_GATE_EVERY_S` (1 s; the key only
  while Voice is not running): Off → `voice_stopping`, stop request, `child_stopped`; Sleep → `voice_released`,
  Voice started again (an abandoned Voice gets a fresh restart budget). A Voice exit while it is not wanted is not a
  crash (`voice_exited_held`). A Voice exit with code 0 is not a crash either, even when the Off that caused it was
  too short for the launcher to see (Off→Sleep in 0.25 s): `voice_exited_clean`, no crash restart consumed, and Voice
  is started again according to the **current** preference (QA rework m2). More than `VOICE_CLEAN_EXITS_MAX` (10)
  clean exits in 120 s still abandon it, so a Voice that would exit 0 in a loop does not spin forever.
  While Voice stops (`stop_role`, at most 15 + 5 s, measured 0.5 s) the watch loop waits (QA m3, accepted).
- **Without the launcher** (development, the `full` edition the user runs daily through `project jarvis`): the
  preference still applies to Voice itself (Off stops it, an unreadable block holds it), but nothing relaunches Voice
  after Sleep: the switch reads « à relancer » and the message says to relaunch Voice (or JARVIS); the Chat stays
  available. `project jarvis` and the user's scripts are unchanged (QA rework m4).
- **Voice** (`jarvis/app.py`): with `off` (or an unreadable block) persisted it exits 0 before composing anything
  (`voice.lifecycle.start_refused_off`); while running, `voice_lifecycle.run_until_released` returns on the launcher's
  stop request **or** on `off`, and the `finally` closes the session and the microphone (`voice.close()`,
  `voice.lifecycle.released` with `reason`). This also works without the launcher (development).
- **Quit** (« Quitter JARVIS »): Control Center, Voice, then Core receive their stop request
  (`JARVIS_STOP_REQUEST_FILE`; Voice reads it since this Slice), 15 s grace, then `terminate`; each Job Object is
  closed, which ends Remotion, MCP servers and CLI children; ports are freed with their process.

## Surfaces

- `GET /api/voice/lifecycle` and the `voice_lifecycle` block of `GET /api/status`: `voice_lifecycle.project(...)`,
  `{preference, state, code, message, managed, voice_online, runtime_state, provider_key{present, provider, label,
  code}, wake{manual_key, manual_armed, voice_word{configured, provider, keyword, available, code, message, armed}},
  problem}`. Never optimistic: the answer to a POST is the projection re-read (`starting` / `stopping` until Voice's
  heartbeat confirms). The key value never leaves the server.
- `POST /api/voice/lifecycle` `{"preference": "off"|"sleep"}`: writes the block (`_write_settings`, other keys and
  secrets preserved), journals `voice.lifecycle.preference_saved {before, after, managed}`.
- JARVIS wheel (`control_center_jarvis_wheel.js`): line **Voix activée**, a `menuitemcheckbox` checked unless Off;
  its note is the server state (`coupée · OFF`, `veille · SLEEP`, `en conversation`, `démarrage…`, `arrêt…`,
  `indisponible`, `à relancer`) and its detail the message and code. Checked only for a readable `sleep`; with an
  unreadable choice a click writes `sleep`. One POST per click, 8 s deadline, a refusal is a toast plus
  `jarvis_wheel.voice_power_failed`.
- Main journey (V1.2 Slice 06): the Presentation home and Settings › Aide et assistance show a **Voix** line,
  `voiceLineOf(facts)` of the wheel module (Coupée / En veille / En conversation / Démarrage… / Arrêt… / Indisponible /
  À relancer, a plain hint, the code kept in the projection) with a button that calls the same `toggleVoice`; it is
  redrawn on the wheel's `jarvis:voice-line` event, never from a local state.
  The button is the useful action (`actionKind`, QA S06 m5): key missing gives Ajouter la cle vocale (Settings >
  Connexions > Fournisseurs); Voice not launched on this machine or unreadable configuration gives no button (the message
  says why); a crash loop keeps Couper la voix (what its message asks); otherwise switch off / on.
- Settings › Voix & audio › Mot d'éveil: `GET/POST /api/wake-word` carry `engine` (`voice_lifecycle.wake_engine`).
  Enabled but engine missing (`wake_package_missing`, `wake_model_missing`, `wake_model_mismatch`,
  `wake_porcupine_key_missing`, `wake_porcupine_package_missing`) shows « Moteur absent » and that only the key wakes
  JARVIS; it is never shown as plainly enabled.
- Readiness window: line `voice` (group computer, never required): Off → optional, Sleep/Active → ready with the
  wake means, key missing → action needed with `open_connections`, other degraded → optional with its code.
- Diagnostics: `voice.lifecycle.state` (Control Center, once per change of state/code), `voice.lifecycle.*` (Voice),
  `launcher.voice_held|voice_released|voice_stopping|voice_exited_held|voice_gate_failed` (launcher log and journal).

## Chat under every voice state

The Chat works in Off and Sleep (`chat_writable` for `absent` and `background`, [chat.md](chat.md)). Sending text
never changes the voice preference, never starts Voice, never opens a microphone, and a text turn's answer is never
spoken (`speech_withheld_text_channel`). In Active the Chat stays locked exactly as before.

## Greeting on the first wake

User feedback 2026-10-29: woken after start, JARVIS said nothing until spoken to. The first session a Voice process
opens from a wake (wake word or key) now says one fixed French sentence
([`jarvis/domain/voice_greeting.py`](../jarvis/domain/voice_greeting.py)): « Oui, monsieur. Voulez-vous reprendre
« <Board title> » ? » when the active Board is a named one, « Oui, monsieur. Je suis en ligne. » otherwise (default
Board, unreadable `GET /v1/boards/active`, title over 80 characters). Never on later wakes of the same process, a
`rebind_board` reopening or a stack switch hand-off; still nothing is opened before the wake.

It goes through `SpeechScheduler.greet`: an `ACK` with `system.notification` provenance carrying Core's current
speech source, held until Core announces it and dropped after `GREETING_TTL_S` (8 s,
`voice.speech.greeting_dropped`). A request spoken right after the wake moves Core's intent on and supersedes it
(`stale_source`). `JARVIS_VOICE_GREETING=0` turns it off.

## Wake word engine (HD-V12-01)

Internal V1.2 builds ship openWakeWord (CC BY-NC-SA models) so Sleep arms the spoken wake word; this is a
**production blocker** (P1) to replace before any commercial release ([release.md](release.md) › *Build channels*).
The package side is [windows-packaging.md](windows-packaging.md) › *Channels* (`build --channel internal`).

Default of a **blank profile** (no `wake_word` block), decided by one question,
`wake_word_install.installed_build_ships_engine()` (read once per process, `wake_word_settings.baseline`): is this
an installed product (product marker `jarvis-product.json` next to the code) whose package manifest declares the
wake word models (`runtime-manifest.json` › `models.wake_word`, written only by the internal build)?

| Machine | `installed_build_ships_engine` | Blank profile |
| --- | --- | --- |
| installed product, **internal** build | true | « Hey Jarvis » armed in Sleep (`enabled: true`, `openwakeword`, `hey_jarvis`), **plus** F9; Settings say « actif par défaut » |
| installed product, **production** build (manifest without `models`) | false | F9 only (`enabled: false`); unchanged |
| development checkout, `full` edition of the developer's machine (no product marker) | false, always | `DEFAULT_ENABLED = False` unchanged: nothing new listens, even with the `wakeword` extra and verified models |

The distinction is the product marker and what the package declares, never the edition setting nor the files
found on disk. The user turns the spoken wake word off in Settings › Voix & audio › Mot d'éveil: the written block
then wins over the default. A present but unreadable block always gives the safe defaults (disabled), never the
armed default.

**A broken engine is said, never silent** (QA S05b MA1). The default does not depend on the engine files being
present: if a model is missing or altered, or the Python package is gone, in an internal build (at any later start),
the setting stays enabled and the engine status (`voice_lifecycle.wake_engine`) carries a stable code
(`wake_model_missing`, `wake_model_mismatch`, `wake_package_missing`) with its message: the Mot d'éveil page shows
« Moteur absent », the readiness « Voix » line adds that message and the code, the voice word is not armed, and F9
still wakes. It never falls back to « Aucun mot de réveil vocal n'est activé ». `build_package.py verify` (and the
installer's repair) report the altered package.

## Conformance

`tests/unit/test_voice_lifecycle.py` (preference, launch matrix, hot toggle, quit, Voice self-release, projection,
routes, wake engine, readiness line), `tests/unit/test_chat_text_ingress.py::test_chat_in_off_or_sleep_reaches_the_brain_without_touching_voice`,
`tests/unit/test_jarvis_wheel_js.py::test_the_voice_switch_projects_the_server_state_and_never_the_hoped_one`,
`tests/unit/test_jarvis_wheel_browser.py` (switch in Chrome), `tests/unit/test_wake_word_settings_ui.py` and
`tests/unit/test_wake_word_settings_browser.py` (engine missing), `tests/unit/test_wake_word_installed_default.py`
(blank-profile default per machine).
