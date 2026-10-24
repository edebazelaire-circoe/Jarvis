# Testing and Quality

## Per-Slice policy

Implementation Slices receive lightweight QA only:

- review/static inspection;
- build/type/syntax checks where relevant;
- narrow runtime smoke checks;
- targeted single-test execution only when debugging a specific defect.

Do **not** launch the full unit test suite at Slice boundaries.

## Final validation

Slice 06 owns the complete unit suite once, plus integration and E2E acceptance in the same final validation phase. Run unit and E2E concurrently when isolation/resources allow.

## Core acceptance themes

- no canonical/derived confusion;
- no secret leakage;
- loadout writes preserve deny-by-default/private-scope rules;
- unavailable CodeGraph is shown as unavailable rather than falsely active;
- Memory Center candidate decisions still confirm and preserve conflict/error handling;
- semantic/Tencent restart semantics stay truthful;
- keyboard and screen-reader navigation remain functional;
- one canonical editable home per setting.

Any regression caused by this task is blocking and cannot be accepted as an Issue.
