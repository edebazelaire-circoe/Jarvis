# Task 10 - Integrate visualizer, launcher and health diagnostics

## Goal

Faire de la V1 un produit testable en une commande avec face visuelle et diagnostics clairs.

## Context

The voice loop must remain primary. Visual components are optional consumers and must not make Jarvis fragile.

## Scope
### In Scope
- Charger `/caveman` et `/coding-guideline`.
- ai-visualizer pinned integration.
- Runtime bus path wiring.
- One-command dev launcher.
- Component process supervision.
- Health report.
- Graceful shutdown.
- Clear missing-component diagnostics.

### Out of Scope
- Production installer.
- Auto-update.
- Desktop packaging.

## Dependencies

Tasks 01-09 complete.

## Implementation Steps

1. Configure visualizer to read Jarvis runtime bus.
2. Add launcher for core + Barehands + visualizer.
3. Generate session token at launch and pass securely.
4. Add health checks for mic, OpenAI config, memory, board, visualizer.
5. Make UI components optional/degradable.
6. Implement shutdown cleanup.
7. Add README run instructions.

## Files Likely Touched

- `scripts/dev_start.*`
- `jarvis/app.py`
- `jarvis/diagnostics/health.py`
- visualizer config
- README

## Architecture Constraints

No background auto-update. No secret in process command line if avoidable. A failed UI child must not stop core voice process.

## Testing Requirements

- Launch with all components.
- Launch with Barehands intentionally unavailable.
- Launch with visualizer unavailable.
- Graceful Ctrl-C cleanup.
- Runtime signal files cleaned/recovered.

## Acceptance Criteria

- Single command launches usable V1.
- Health output identifies failed component.
- Voice remains usable without visual components.
- Face follows idle/listening/thinking/speaking.

## Documentation Updates

Update runbook and troubleshooting section.

## Handoff Notes

Prefer simple process orchestration over Docker/Electron for V1 unless existing repo already mandates one.
