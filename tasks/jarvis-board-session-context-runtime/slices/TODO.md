# Slice execution plan

00 PM readiness gate -> 01 Board/Session contract -> 02 persistence + default Board + Board-scoped mode -> 03 SessionManager + per-Board bindings -> 04a Board agent pool (Control Center) -> 04b switch transaction + speech authority + Voice rebind -> 05 MCP -> 06 Control Center Boards UI -> 07 Board-attributed alerts/absence -> 08 E2E rollout.

Amended at Slice 00: Slice 04 split into 04a (folder `04-brain-voice-switch`) and 04b (folder `04b-switch-speech-authority`); architecture in `docs/06-resolved-architecture.md`; Task Type gate waived.

Task is done when UI and MCP can create/select/manage Boards, one Session can traverse Boards, new Session resets conversation without changing Board/task state, only active Board can speak, background work survives, modes restore, alerts identify their source Board, and legacy state migrates safely.

- [x] 00
- [x] 01 (machine QA complete; Human checks pending)
- [x] 02 (machine QA complete; Human checks pending)
- [x] 03 (machine QA complete; Human checks pending)
- [x] 04a (machine QA complete; Human checks pending)
- [x] 04b (machine QA complete; Human checks pending)
- [x] 05 (machine QA complete; Human checks pending)
- [x] 06 (machine QA complete; Human checks pending)
- [x] 07 (machine QA complete; Human checks pending)
- [x] 08 (machine QA complete; Human checks pending)
