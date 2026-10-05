# Slice execution order

1. `00-project-manager` — readiness/orchestration gate.
2. `01-contract-reconciliation` — live repository + cross-handoff audit.
3. `02-interaction-mode-contract` — canonical effective Presentation mode semantics.
4. `03-control-center-mode-ui` — visible mode control and state feedback.
5. `04-ambient-presentation-lane` — consume ambient speech as non-authoritative context.
6. `05-presentation-working-set` — fresh tail + bounded enriched context/prepared resources.
7. `06-background-intelligence-arbitration` — speculative work, priority and preemption.
8. `07-manifestation-policy` — decide none/speech/display/attention.
9. `08-tool-brain-integration` — semantic display intent -> Tool Brain.
10. `09-scene-prefab-integration` — prepared/on-demand visuals through canonical scene/prefab runtime.
11. `10-observability-attention` — timeline events and discreet fact-check attention surface.
12. `11-end-to-end-hardening` — deterministic scenario suite, regression/performance/privacy hardening.

Slices 08 and 09 have external freshness dependencies. The Project Manager may delay only those adapters if their owning handoffs are not ready; core Presentation semantics should continue where safe.
