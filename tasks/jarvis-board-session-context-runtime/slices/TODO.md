# Slice execution plan

00 PM readiness gate -> 01 Board/Session contract -> 02 persistence + workspace scoping + mode -> 03 SessionManager + per-Board bindings -> 04 Brain lifecycle/switch/Voice -> 05 MCP -> 06 Control Center Boards UI -> 07 Board-attributed alerts/absence -> 08 E2E rollout.

Slice 00 must resolve valid Workspace Task Types before dispatch. Task is done when UI and MCP can create/select/manage Boards, one Session can traverse Boards, new Session resets conversation without changing Board/task state, only active Board can speak, background work survives, modes restore, alerts identify their source Board, and legacy state migrates safely.
