# 00 - Overview

**Goal**: preserve the mature Presentation Studio/Slidecar effort and integrate a local Remotion-first presentation pipeline into Jarvis, with correctly modeled assets, exports, prefab compatibility and voice-first editing.

**Audience**: Project Manager, Core/runtime implementers, frontend implementers, agent/tooling implementers, QA and Human acceptance.

**Inputs**: final branch code and documentation, original handoff Slices and LOG, current main branch, canonical artifacts/prefabs/boards/plugins contracts, Remotion upstream docs and current tested versions, user decisions reconstructed in `grill-session.md`.

**Main actions**: independent audit and gate; define engine/plugin/storage contracts; install local Remotion capability; embed Player, optionally launch Studio; bridge current score/cues/control changes and subagent source edits; align catalog, source/derived artifact links, Board access, export and runtime tests.

**Output**: one installable, testable, default Remotion workflow from voice request to editable full-screen preview to optional Studio to self-contained export, with existing Slidecar data untouched and experimental user access preserved. Full handoff documentation and QA evidence.

**Non-goals**: rewriting the original 23 Slices while another agent finishes; replacing the Board, Session, Prefab or Tool Brain owner; embedding full `node_modules` per slide; automatically converting all Slidecar prefabs to React; promising arbitrary HTML interactivity survives deterministic video rendering; auto-promoting drafts; auto-updating prefab pins; doing paid media generation; blanket internet access from generated code; claiming that a PDF/MP4 is editable source.

**Quality criteria**: no baseline regressions; no silent engine fallback; restart/install/repair reproducible; source edits visible in preview without MP4 render; Board reference resolution and frozen export correctness; strict security; runtime trace evidence for commands/cues and Human sign-off for real voice, Windows launch/dual-screen and visual quality.
