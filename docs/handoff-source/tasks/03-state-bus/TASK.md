# Task 03 - Implement state machine and file signal bus

## Goal

Implementer le cycle d'etat Jarvis et un `StatePublisher` compatible avec la philosophie ai-visualizer.

## Context

Le file bus est retenu pour la V1 car il decouple fortement l'UI tout en restant trivial a diagnostiquer.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- State machine typed.
- FileStatePublisher in dedicated runtime dir.
- Mapping to `.voice_state`, waveform placeholder and alert.
- Atomic writes where useful.
- Stale cleanup on startup/shutdown.

### Out of Scope
- Pas de visualizer UI dans cette task.
- Pas de WebSocket.

## Dependencies

Task 02 complete.

## Implementation Steps

1. Define legal transitions.
2. Implement state transition service.
3. Implement file publisher adapter.
4. Map extended Jarvis states to upstream-compatible visual states.
5. Add alert/error signal.
6. Clean runtime files on normal shutdown and startup recovery.

## Files Likely Touched

- `jarvis/domain/events.py`
- `jarvis/core/session.py`
- `jarvis/adapters/file_state_bus.py`
- `tests/unit/test_state_machine.py`

## Architecture Constraints

UI compatibility is adapter behavior, not domain behavior. Core state enum may be richer than visualizer state vocabulary.

## Testing Requirements

- All allowed transitions tested.
- Illegal transitions fail with diagnostic.
- File output contract test.
- Interrupted/crashed stale state recovery test.

## Acceptance Criteria

- State machine deterministic.
- Runtime files are outside source repo state.
- Visualizer-compatible files can be generated without UI running.

## Documentation Updates

Document exact runtime file contract.

## Handoff Notes

Keep room for future WebSocket publisher without changing core.
