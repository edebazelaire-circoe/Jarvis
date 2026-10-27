# Discussion source — reconstructed

> Reconstructed from the current project conversation because the host did not expose a complete verbatim transcript for every voice turn. This file records only decisions and requests actually expressed; it does not invent missing answers.

## Baseline carried forward
The first Presentation Edition task established: Presentation-only product policy, internal state under AppData, `CONTEXT_GLOBAL` inside that root, internal working documents in AppData, `Documents/Jarvis` as export-only, bounded agent writes, CIRCOE Mail/Calendar + Drive + IGuard seam, private runtimes/installer, Windows-first productionization and later macOS/Linux work.

## Amendments clarified after the first task
- The full Jarvis Settings area should remain available, including transcription and technical controls, because they are useful when debugging on another person's machine.
- On application launch, Jarvis should normally be running but voice should be in Sleep, callable by wake word. Explicit Voice Off remains available in Settings. Closing the application should stop Core and the rest of the local runtime.
- The same product must remain usable through chat; voice Sleep/Off must not make the whole project unusable.
- The default interface should be simpler for a non-expert user even though advanced Settings remain available.
- Jarvis must be conditioned much more strongly around Presentation work: interview, documentary research, conceptualization and production. It must not become a general agent that edits the Jarvis project or writes arbitrary code. Remotion/prefab code used to generate presentations remains allowed.
- A Board is a project. A project may contain several presentations. Reopening the Board must feel like resuming the project: Jarvis knows the purpose, objectives, progress, decisions and next useful step.
- Jarvis should take durable project notes instead of relying on the old conversation alone.
- Research must use the already implemented organic agent architecture rather than a simplistic single web-search response. The Research Lead should orchestrate research agents and use delegation, communication, adversary and QA relations when useful.
- Research should run in the background while the main Jarvis conversation/interview continues.
- Research agents must have access to the shared documentary base and must inspect what already exists before launching redundant research.
- Existing research has a freshness problem: a 2025 research note about rapidly changing OpenAI models cannot be treated as current in 2026. Reuse must account for dates, source freshness and topic volatility.
- Substantial research should produce one or more clean, durable documents attached to the Board/Dossier, so later presentation generation can reuse the research instead of repeating it.
- Add a simple bug-report button. In the prototype, collect the error/diagnostic context, let AI prepare a concise bug report, package the Jarvis AppData context as a ZIP, then send it to the configured developer/support destination or leave a transferable bundle.
- macOS execution matters even if development is done from Windows. The implementation should be portable and validated through macOS CI; a real Mac is still needed before declaring the release supported.

## Product usage model restated
The initial user experience is deliberately simple: open or resume a Presentation project, discuss it by voice or chat, research and structure the subject, use connected company/document tools where helpful, produce durable source material, create/edit one or more presentations, present/render/export. Mail and calendar remain useful secondary capabilities, but Presentation is the product center of gravity.