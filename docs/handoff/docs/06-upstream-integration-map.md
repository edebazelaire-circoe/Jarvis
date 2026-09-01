# 06 - Upstream integration map

## fullstack-agent

Use as reference only.

Useful concepts:

- guided setup ;
- separate components ;
- start/update ergonomics.

Do not import its wizard as the Jarvis runtime architecture.

## backtalk

Reference files/features worth studying:

- `backtalk/ears.py`: microphone capture, VAD, audio-device recovery ;
- `backtalk/ptt.py`: global push-to-talk ;
- `backtalk/mouth.py`: streaming speech and audio output ;
- `backtalk/signals.py`: state/waveform publication ;
- `backtalk/main.py`: interruption and confirmation UX ;
- `backtalk/brain.py`: study streaming/cancellation, but do not keep Claude-specific brain as core.

V1 integration rule: either keep upstream as a clearly licensed external dependency or reimplement the small required contracts. Do not accidentally copy AGPL code into a differently licensed core without recording it.

## barehands

Use as external browser/UI component.

Required changes before V1 acceptance:

- pin commit ;
- remove runtime CDN imports ;
- vendor Three.js ;
- vendor MediaPipe JS/WASM/model ;
- add CSP ;
- add session-token auth on mutating command endpoint ;
- keep path/media jail tests ;
- preserve localhost binding.

Jarvis talks to it through `BoardClient`, not imports.

## ai-visualizer

Can be used almost directly.

For V1, keep the file-signal bus because it is low-risk and fast to integrate. Place files in a dedicated Jarvis runtime directory rather than inside source trees.

Expected mapping:

- Jarvis `idle` -> visualizer `idle`
- `listening`/`transcribing` -> `listening`
- `thinking`/`awaiting_confirmation` -> `thinking` plus optional alert
- `speaking` -> `speaking`
- `error` -> `.voice_alert`

## ai-memory-vault

Use as UX inspiration, not runtime dependency.

Keep Markdown source of truth. V1 memory code belongs to Jarvis core/adapters with explicit index rebuild semantics.
