# Decision Log

1. 2026-09-12 — The user-facing “Aiguillage” page is removed; backend routing remains an implementation detail unless another product need emerges.
2. 2026-09-12 — Technical settings are visually and structurally prioritized over personality settings.
3. 2026-09-12 — Auto/Dupliqué is the primary sub-agent mode control, but exact runtime semantics must be taken from live code rather than guessed.
4. 2026-09-12 — Voice settings are split into top-level sub-tabs/categories because the current page is too dense.
5. 2026-09-12 — Catalogs should be explorable/comparable and should distinguish usable models from relevant-but-unavailable candidates.
6. 2026-09-12 — Pricing/capability/tag metadata may be added only with explicit provenance/freshness; unknown is preferable to fabricated certainty.
7. 2026-09-14 — `Auto` is the projection of `agent_routing.enabled=true`. `Dupliqué` is compatibility/inheritance (`false`): preserve caller/CLI model, execute only the requested sub-agent, never fan out.
8. 2026-09-14 — Delegation mode changes model selection only. Existing profile candidates remain persisted while Dupliqué is active.
9. 2026-09-14 — Verbosity and politeness/formality use an `inherit` default. They remain hidden until Slice 02 provides one tested central runtime consumer; persisted placebo fields are forbidden.
10. 2026-09-14 — Voice category IDs and exact mapping are canonical in `settings-ia-contract.json`; compatibility voice settings are projected without automatic persistence migration.
