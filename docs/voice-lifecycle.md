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
chat »): that is Sleep again. Transitions and degraded reasons are said, never guessed:

| `state` | `code` | Meaning |
| --- | --- | --- |
| `starting` | `voice_starting` | Sleep wanted, the launcher started Voice, no heartbeat yet |
| `stopping` | `voice_stopping` | Off wanted, Voice still beats (it releases within a second) |
| `degraded` | `voice_provider_key_missing` | no key for the provider of the chosen voice stack: Voice is **not started** (no crash loop) |
| `degraded` | `voice_configuration_invalid` | the voice architecture/stack cannot be resolved (same check as Voice) |
| `degraded` | `voice_crash_loop` | Voice died `MAX_RESTARTS` times and was abandoned; switching Off then on again retries |
| `degraded` | `voice_runtime_error` | Voice reports `error` |
| `degraded` | `voice_not_launched` | the launcher runs without Voice (`JARVIS_LAUNCH_VOICE=0`) |
| `degraded` | `voice_not_running` | no launcher (development) and no Voice heartbeat |
| `off` | `voice_off` | user choice |

## The one persisted preference

Block `voice_lifecycle` at the root of `runtime/control-center-settings.json` (no SQLite table, no migration):

```json
{"schema_version": 1, "preference": "sleep"}
```

- `sleep` is the default: a fresh profile starts wake-ready. A missing, malformed or foreign-version block reads as
  `sleep` with a `problem` code (`voice_lifecycle_block_malformed`, `voice_lifecycle_stored_version_unreadable`,
  `voice_lifecycle_preference_invalid`): **only a readable `off` turns the voice off**.
- `off` survives every restart: nothing rewrites it but the user.
- Strict write (`apply_preference`): exactly `{"preference": "off" | "sleep"}`; refusals `voice_lifecycle_bad_payload`,
  `voice_lifecycle_preference_invalid`, `voice_lifecycle_foreign_version` (header `X-Jarvis-Error-Code`).

## Who applies it

- **Launcher** (`product_launcher.py`): before starting Voice, `launch_decision` (preference, then the provider key
  through the same path Voice uses: `resolve_voice_composition` → stack → `credentials.secret_for`, `.env` included).
  Not wanted → Voice is *held* with its code, published in `launcher.json` (`roles.voice.held`), journaled
  `launcher.voice_held`. During the watch it re-reads the preference every `VOICE_GATE_EVERY_S` (1 s; the key only
  while Voice is not running): Off → `voice_stopping`, stop request, `child_stopped`; Sleep → `voice_released`,
  Voice started again (an abandoned Voice gets a fresh restart budget). A Voice exit while it is not wanted is not a
  crash (`voice_exited_held`).
- **Voice** (`jarvis/app.py`): with `off` persisted it exits 0 before composing anything
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
  `indisponible`) and its detail the message and code. One POST per click, 8 s deadline, a refusal is a toast plus
  `jarvis_wheel.voice_power_failed`.
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

## Wake word engine (HD-V12-01)

Internal V1.2 builds may ship openWakeWord (CC BY-NC-SA models) so Sleep can arm the spoken wake word; this is a
**production blocker** to replace before any commercial release ([release.md](release.md)). Packaging is not changed
by this contract: see the Slice 05 notes for what the package must add.

## Conformance

`tests/unit/test_voice_lifecycle.py` (preference, launch matrix, hot toggle, quit, Voice self-release, projection,
routes, wake engine, readiness line), `tests/unit/test_chat_text_ingress.py::test_chat_in_off_or_sleep_reaches_the_brain_without_touching_voice`,
`tests/unit/test_jarvis_wheel_js.py::test_the_voice_switch_projects_the_server_state_and_never_the_hoped_one`,
`tests/unit/test_jarvis_wheel_browser.py` (switch in Chrome), `tests/unit/test_wake_word_settings_ui.py` and
`tests/unit/test_wake_word_settings_browser.py` (engine missing).
