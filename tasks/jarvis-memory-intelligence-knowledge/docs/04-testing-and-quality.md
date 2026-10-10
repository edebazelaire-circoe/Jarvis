# Testing and Quality

Every implemented Slice gets qa-verification. Code changes add code-review. Runtime/user-visible behavior adds runtime-validation. Agent prompts, tools, memory injection, knowledge loadouts or routing add agent-trace-analysis with real trace evidence.

A regression caused by the current Slice is blocking. Human validation never substitutes for machine QA. Frontend work uses /impeccable and a Claude Work Agent when supported; coding agents use /caveman and /coding-guideline.

UX gate: an independent critic agent must navigate settings and the Memory Center like a real user, modify safe controls, search/read memory, inspect provenance and derived state, understand disabled/degraded modes, and report confusing or impossible actions. Findings are fixed or explicitly escalated before completion.  
