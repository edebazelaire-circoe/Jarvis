# Execution log

Reserved for implementation agents. Record durable execution notes here as work is actually performed.

## 2026-09-30 — Slice 00 (agent 0)

- Handoff mirrored from Drive (39 files, JSON verified, Google-Doc escaping removed).
- Blind audit + resolved architecture (`docs/06-resolved-architecture.md`), `## Slice 00 contract` appended to SLICE 01–08.
- Baseline at `96a9396`: 322 unit failures from merge `b8c3ba1` losses → D0 fix branch `fix/main-merge-loss-2026-09-30` (in progress). Task branch to be rebased onto it before Slice 01.
- Decisions D0, D-TT, D1–D12, Q2, Q3 recorded in `slices/00-project-manager/READINESS.md`.

## 2026-09-30 — Slice 01 (implémenteur)

- Docs seulement : `docs/mcp/plugins.md` créé (contrat cible plugins + `jarvis-tools`, bornes et codes d'ARCH §5–§9), `docs/mcp/tool-contract.md` amendé (§1 ancres rafraîchies, barehands 16, ligne `jarvis-tools` ; §2 descripteur externe ; §3 ; §4.3 exception Codex + disponibilité plugin ; §5.3 ; §8 routes de gestion, aucune route d'exécution au CC).
- Écarts ARCH relevés (non corrigés, remontés à agent 0) : `CORE_ADAPTER_IMPORT_EXCEPTIONS` vit dans `tests/unit/test_v2_architecture.py:35`, pas `core/v2_app.py` ; la pose des cibles MCP par agent est `_configure_agent` (`control_center.py:1205`).
- `tests/unit/test_mcp_catalog.py` : erreur de collecte `READY_SETTLE_S` (D0, préexistant), aucun code touché.
- Rework QA (Slice 01) : EVIDENCE.md ; ancres historiques de tool-contract revérifiées ; E10 (révocation RFC 7009 best-effort), `stop()` ≤ 5 s, sens plugin d'`advertised` ; E9 corrigé en `codex_local.py:253-273` (ma lecture 252-272 était fausse).
