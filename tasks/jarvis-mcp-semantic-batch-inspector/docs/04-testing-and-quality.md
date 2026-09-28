# Testing and quality


## Gates
Every implemented Slice: `qa-verification`; code changes: `code-review`; visible/runtime behavior: `runtime-validation`; MCP/prompt/routing/agent-runtime changes: `agent-trace-analysis` with real evidence.


## Domain tests
Canonical constellation explicit links both directions; signal-owner fallback; archived exclusion; bounded/unbounded depth; plural kinds; deterministic bounded selection; UI/domain parity fixtures; failed full-batch leaves revision untouched; successful batch increments exactly once; one patch contains all intended ops; relative translation preserves offsets and common delta; deterministic boundary behavior; explicit unplaced handling; pin/archive/update authority parity.


## MCP tests
One semantic multi-object batch causes one Core command POST; no `best_effort` result for atomic promises; correct required/optional input schema; concrete output contracts; actual FastMCP `tools/list` matches catalog; deprecations explicit; final tool count/context budget compliant; refusals never claim success.


## Control Center API/UI tests
Read-only deterministic list/detail; correct conditional availability; no secret leakage; search/tabs/collapse/detail/schema renderer; keyboard/focus/responsive/reduced motion; clear loading/error/empty states.


## Runtime validation
Compare actual advertised MCP list to inspector, execute representative semantic hide/translate/archive/pin, prove one MCP call -> one Core command -> one revision, verify coherent scene transition, and capture compact/detailed inspector in supported themes where possible.