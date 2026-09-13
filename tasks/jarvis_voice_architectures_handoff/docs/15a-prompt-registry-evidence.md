# Task15A — prompt registry and override foundation

Accepted foundation, 2026-09-13. This slice adds inspection and persistence
contracts only. Actual provider/CLI send sites and the Settings editor remain
Task15B/15C work.

## Delivered contract

- `PromptRegistry` owns stable layer IDs, source provenance, applicability,
  channel, operation, editability, declared variables, default/effective
  revisions and deterministic static/render fingerprints.
- Fourteen programs model the current Simple, Front Brain, legacy,
  continuous-brain, Duplex, reflex, verbatim, Luna and Claude/Codex invocation
  shapes without flattening distinct provider channels into one invented prompt.
- Dynamic conversation data, observations, tool schemas and hard runtime rules
  remain read-only. Provider-internal instructions are reported as unavailable.
- Safe user additions and the shared persona are the only editable layers.
  Overrides use a bounded versioned document, retain their base revision, reject
  stale or concurrent edits, preserve unrelated settings and reset by removing
  only the selected entry.
- Persistence diagnostics contain IDs, result codes and fingerprints only.
  Successful persistence is labelled `saved_only`; it is not reported as sent
  or acknowledged.

## Quality evidence

- Prompt registry, provenance and adversarial override review: **51 passed**.
- Broadened compatibility gate covering prompt resolution, reflex, Front Brain,
  Live, delegation, backend worker, app and architecture paths: **333 passed**.
- Python compilation and `git diff --check`: clean.
- Independent override review reported no open P1/P2 finding.

## Remaining acceptance boundary

Task15 is not complete at this point. Task15B must make the resolved object the
source used at each actual send site and record sent/render fingerprints without
prompt text. Task15C must expose the relevant programs, provenance, effective
values, conflicts and edit/reset operations in Settings. Those slices must also
preserve the distinction between saved, sent and provider-acknowledged state.
