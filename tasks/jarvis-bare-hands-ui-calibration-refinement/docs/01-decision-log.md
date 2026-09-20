# Decision log

1. Bare Hands is a first-class main-screen control, not primarily a Settings/Experimental feature.
2. The main control is a slightly larger square button with a hand icon, using the existing Jarvis HUD visual language.
3. OFF is strongly dimmed/grey.
4. SLEEP is normal Jarvis blue with no extra emphasis.
5. ACTIVE is brighter electric blue with a subtle glow. The earlier green-active idea was explicitly rejected.
6. Normal click opens a visual three-state selector for OFF/SLEEP/ACTIVE; it is not a conventional text dropdown and not a blind cycle.
7. The button must mirror state changes from every source: UI, voice/MCP, C-wake, inactivity, errors/recovery.
8. Right-click menu entries are Settings, Calibration, Help/Gestures, Diagnostics.
9. No activation item is duplicated in the right-click menu.
10. Separate Tutorial entry is removed.
11. Tools are removed from Settings and exposed in a fast left-side palette.
12. V1 palette uses only the current installed tools: pointer, pan, select.
13. Palette is fixed vertical on the left in this refinement; moving/docking/horizontal orientation is deferred.
14. Settings is configuration only; lifecycle and current tool selection are not primary Settings controls.
15. Help/Gestures becomes a small airy visual card/window with hand diagrams rather than a dense text/debug block.
16. Diagnostics is a quick entry to the existing recorder/replay feature, not a new diagnostic implementation.
17. The separate Tutorial flow is removed; Calibration now also teaches the interactions.
18. Calibration is full-screen over a blurred/darkened Jarvis scene and has no centered modal card.
19. Step title and instruction are large and placed high; the center is reserved for demonstration/exercise.
20. Virtual hands are simple schematic/robotic line art, not realistic anatomy.
21. Blue is the normal guidance color; green may be used briefly for successful recognition.
22. A calibration step has a minimum reading/presentation phase before it can start.
23. For gesture/posture steps, no measurement timeout burns while the user is inactive; the active test starts only once the user actually engages after the reading delay.
24. Target step reveals targets after the reading delay.
25. Window step reveals the practice frame after the reading delay and begins on a valid capture.
26. Final step sequence: rest, C, primary pinch, secondary pinch, target pinch, window manipulation, completion.
27. C illustration must clearly show thumb + index forming the C.
28. Target calibration must visually show thumb-index pinch, not a pointing finger.
29. Window manipulation step has two sub-steps: one-hand edge/corner move, then two-hand compatible-zone resize.
30. Window practice must reuse the real Bare Hands target/capture/scene geometry semantics.
31. Existing contextual interaction semantics from `docs/barehands-contracts.md` and the prior `jarvis-bare-hands-v1` task are not reopened by this refinement.
32. No new tools or gesture-action bindings are introduced here.
