# 03 - Implementation strategy

1. Blind-audit live repository and resolve canonical owners.
2. Land Board/Session contracts and backward-compatible default-Board migration.
3. Persist Board state/references and Board-scoped interaction mode.
4. Add SessionManager and (session,board) conversation bindings.
5. Add explicit Brain lifecycle and atomic Board switch/Voice authority.
6. Add jarvis-console MCP tools through shared metadata/catalog.
7. Add simple Control Center Boards control.
8. Extend existing BackgroundEventLedger/alerts with Board attribution/navigation.
9. Run restart, migration, session-reset, background-work, UI/MCP parity and voice-authority E2E tests.

Keep existing new_conversation behavior compatible until the canonical Session operation is proven.
