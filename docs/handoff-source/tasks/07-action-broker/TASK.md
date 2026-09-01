# Task 07 - Implement ActionBroker and confirmation flow

## Goal

Mettre une frontiere de securite explicite entre le modele et toute action modifiant l'etat.

## Context

La V1 interdit le shell et n'autorise que des actions metier enregistrees.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- Risk classes.
- Allowlist registry.
- Confirmation state.
- PTT response to pending confirmation.
- Deny-by-default and timeout.
- `board_present` safe action.
- `memory_append` confirmed action.

### Out of Scope
- Destructive filesystem actions.
- OS commands.
- Remote account actions.

## Dependencies

Tasks 02-06 complete.

## Implementation Steps

1. Define policy table.
2. Implement ActionBroker.
3. Route provider tool requests through broker.
4. Implement pending-confirmation lifecycle with turn correlation.
5. Accept exact normalized approvals only.
6. Deny timeout/interruption/stale approval.
7. Publish awaiting-confirmation state.

## Files Likely Touched

- `jarvis/security/policy.py`
- `jarvis/core/actions.py`
- `jarvis/domain/actions.py`
- tests

## Architecture Constraints

No adapter may bypass ActionBroker for mutations. A confirmation is bound to one action id and expires. Safe reads can bypass confirmation only if policy explicitly says so.

## Testing Requirements

- Exact yes/no parsing.
- `yesterday`/ambiguous phrase rejection.
- Stale approval rejection.
- Action id binding.
- Unknown action forbidden.
- No general shell registered.

## Acceptance Criteria

- `board_present` can execute without confirmation.
- `memory_append` pauses and requests confirmation.
- Denial/timeout never writes.
- No mutation path exists outside broker in V1 tools.

## Documentation Updates

Document policy matrix.

## Handoff Notes

Do not add an auto-approve mode in V1.
