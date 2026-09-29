# 04 - Testing and quality

QA doctrine:
- every implemented Slice gets qa-verification;
- code changes add code-review;
- user-visible/runtime behavior adds runtime-validation;
- agent/tool/MCP/runtime changes add agent-trace-analysis with real traces;
- current-Slice regressions block completion;
- Human validation happens only after maximal machine validation.

Required proof: domain/persistence migration tests; A/B/A conversation binding tests; new Session preserves Board/task state; exactly one speech authority; inactive work survives and cannot speak; MCP real-server/catalog parity; Boards UI/API tests; cross-Board notification attribution and restart/absence tests; regressions for voice, scene, interaction mode, task alerts, and agent restart.
