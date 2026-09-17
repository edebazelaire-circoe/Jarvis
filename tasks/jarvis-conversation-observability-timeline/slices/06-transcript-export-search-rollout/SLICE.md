# Slice 06 — Add readable transcript/export/search and end-to-end rollout gates

## Goal

Make canonical events useful outside the timeline and prove the complete observability path.

## Context

Users need readable transcript access, search, and machine-readable export, but these must stay derived from canonical events.

## Canonical Concepts

- plain readable transcript projection
- JSON/JSONL export of canonical events
- search over safe user-visible content and metadata
- session retention/recovery validation
- documentation/rollout

## Scope

### In Scope

- Implement derived projections and search.
- Prove crash/restart fidelity and trace joins end to end.
- Add documentation and rollout gates.

### Out of Scope

- Semantic LLM summarization of transcript.
- Raw-audio archive.

## Dependencies

03, 04, 05

## Implementation Steps

1. Implement deterministic transcript renderer from events.
2. Implement machine-readable export and bounded search.
3. Add end-to-end fixture with interruption, Brain activity, tool/sub-agent span, failure/restart.
4. Run QA composition including agent-trace-analysis.
5. Document operations, storage size/retention and privacy/redaction boundaries.

## Files Likely Touched

- `jarvis/runtime/*conversation*`
- `jarvis/runtime/control_center.py`
- `tests/integration/*`
- `docs/*`

## Architecture Constraints

- Readable transcript must be reproducible from exported events.
- Search must honor redaction/visibility rules.

## Automated Validation

- E2E crash/restart test.
- Export→reimport/reconstruct equivalence test.
- Search redaction tests.
- Release verification.

## Acceptance Criteria

- Text transcript matches canonical visible event sequence.
- Export supports offline reconstruction.
- Search finds user-visible data without surfacing forbidden fields.
- All QA gates pass.

## Documentation Updates

Promote the Conversation Event contract and timeline usage to canonical docs; add operational recovery/export instructions.

## Handoff Notes

Keep implementation evidence and material planning corrections in `LOG.md`. Current-Slice regressions are blocking.
