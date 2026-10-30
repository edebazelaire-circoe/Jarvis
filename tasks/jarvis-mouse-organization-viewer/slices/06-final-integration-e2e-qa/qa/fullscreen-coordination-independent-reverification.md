# Independent F2 coordination re-verification

Reviewed root `dc0c5036` (source `1340ca56`), integrated into QA at `e60e9d42`.
Only the affected overlay probe expectations/output destinations changed to
match PM's explicit policy. Historical red JSON/PNG/JUnit and
`overlay-coexistence-review.md` remain intact. No product edits by QA.

## Source review

- SceneViewer.prepare refuses an armed/needs_gesture fullscreen intent with
  explicit French instructions before opening a native modal, including a
  local arm without a remote command ID. Active browser fullscreen refusal is
  preserved.
- The canonical fullscreen controller's optional synchronous beforePrompt
  dependency invokes Scene.closeViewer, which delegates to the existing viewer
  owner's close seam. It runs before old prompt replacement, focus capture,
  prompt construction/showPopover and countdown setup. Owner abort/disposal,
  clocks/history cleanup and anchor focus remain in the viewer owner.
- Existing callback-absent controller behavior stays unchanged. Callback
  failure logs and propagates through the existing error path; no inert prompt
  or automatic requestFullscreen is introduced. New pure tests explicitly
  cover order, ID-less arms, no automatic request, error/log path and admission
  states. Existing controller cases retain callback-absent coverage.
- No new fullscreen controller, bus, protocol message, backend route, geometry
  write, z-index repair or copied prompt markup. Docs describe the selected
  precedence policy and canonical lifecycle accurately.

## Actual independent runtime

Main venv, actual isolated Core/SQLite/Control Center and production command
poll/controller, real CDP input; no fetch substitute, model or live runtime.
Only the prepared three-case probe was run: **3 passed in28.18seconds**,
`overlay-coexistence-reworked.xml`.

1. Remote prompt armed before scene double-click: viewer admission refused,
   actual French feedback visible, prompt still hit-testable/actionable. Real
   Go click enters actual browser fullscreen on the canonical scene host;
   scene open refuses while fullscreen; exit then ordinary viewer/Escape and
   focus return work.
2. Canonical request during native viewer: owner closes before prompt; native
   viewer is no longer open, both Go/Cancel centers hit correctly and focus
   is on Go. Real Cancel removes the arm. Ordinary viewer reopening/Escape
   restores anchor focus and no browser fullscreen enters automatically.
3. Ordinary panel closure, normal Settings Escape/admission boundary and
   retained nonmodal Studio inspector work; attempted outside focus cannot
   escape native viewer. Studio retained state remains acceptable preservation.

Reworked evidence uses separate names:
`fullscreen-armed-before-viewer-reworked.json`,
`fullscreen-request-during-viewer-reworked.json`,
`ordinary-panels-settings-studio-viewer-reworked.json`,
`fullscreen-viewer-admission-refused-reworked.png`,
`fullscreen-prompt-during-viewer-reworked.png`. I visually inspected the latter:
ordinary canonical prompt is clearly visible/actionable, native viewer absent,
Go focus visible. Each test kept real scene revision unchanged and produced
zero Runtime exceptions. No broader campaign/full-suite repeat.

The implementer's separate actual provider AbortSignal observation (one
mount/one abort, entries cleared) is reviewed as supplementary author evidence;
it is not recounted as an independent execution here. The owner cleanup path
it exercises is unchanged canonical ObjectViewer disposal, also independently
tested in S03/S05.

F2's reported inert-prompt defect is resolved under the selected policy in
this independent code/runtime review. Recommend PM accepting this scoped
rework. Other broad-gate failure dispositions and final Human review remain
separate gates; this does not label the entire release suite all-pass.
