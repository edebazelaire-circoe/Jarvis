# Decision log

## Baseline decisions inherited from Presentation Edition V1
- Installed Jarvis state is per-user under the platform's application-data root; on Windows the target is `%LOCALAPPDATA%/CIRCOE/Jarvis`.
- `CONTEXT_GLOBAL` is permanent Jarvis personal context inside that internal root.
- Working documents remain internal; `Documents/Jarvis` contains explicit exports only.
- Presentation Edition allows only Presentation Boards in the product surface and at enforcement boundaries; Assistant/Meeting code stays in the shared repository.
- General filesystem/shell authority is not a product capability.

## 2026-10-26 — Full Settings retained
User correction: do not strip Control Settings or transcription settings from the installed product. They are valuable for remote/field debugging. Usability work must simplify the normal path through grouping/progressive disclosure, not by deleting controls.

## 2026-10-26 — Voice startup lifecycle
Normal launch: services start and voice is Sleep with wake-word detection armed. Explicit persisted Voice Off is honored. Closing the application stops the local Jarvis runtime. Chat remains usable while voice is Sleep or Off and must not silently reactivate microphone/TTS.

## 2026-10-26 — Presentation product brain, not developer brain
Jarvis can research, interview, conceptualize, mail/schedule through approved connectors and author presentations. It must not modify the Jarvis source repository or perform arbitrary software development. Presentation code generation is allowed only through bounded Presentation/Remotion/prefab capability paths.

## 2026-10-26 — Board equals project
A Board is the durable project boundary and can own multiple presentations and documents. Reopening it must restore project continuity without relying on the previous conversation transcript.

Decision: use existing `summary.md` as the canonical project digest convention because Board hydration already reads it every turn. Detailed documents live beside it in Board memory/Dossier.

## 2026-10-26 — Existing research stack is the foundation
Research Lead, research/web-research roles, Work Methods, background agents and relations already exist. V1.2 reinforces and validates this behavior; it does not introduce another orchestrator.

## 2026-10-26 — Search existing knowledge before new research
Research first inspects Board memory/Dossier, global/Jarvis knowledge and connected shared sources relevant to the question. Only missing or stale material triggers new external research.

## 2026-10-26 — Freshness is explicit
Previous research is classified for reuse based on `checked_at`/source dates, topic volatility and the user's request. Outcomes are reuse, partial refresh, or full refresh. No universal TTL is invented.

## 2026-10-26 — Research leaves a reusable document
Substantial research produces a clean Board document with findings, sources, dates, uncertainty and freshness metadata. Current architecture makes Board memory/Dossier the preferred owner of revisable project documents; creating a new registry Artifact kind is not part of this amendment unless a later audit proves it is required.

## 2026-10-26 — Bug reporting is a product feature
Add “Report a problem”: collect diagnostic context, generate an evidence-based AI report, create a ZIP snapshot of the Jarvis AppData context, exclude/redact credentials and secrets, then send through a configured support channel or preserve a manual bundle. The support recipient is configuration, not guessed/hard-coded.

## 2026-10-26 — macOS portability is active work
Windows remains the first physical release path, but V1.2 makes macOS buildable/testable in CI. Platform-specific paths and packaging must use adapters rather than branches. A real-Mac acceptance pass is mandatory before claiming macOS support.